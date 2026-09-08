"""契约化执行路径（FR-030/031，Story 3.1）：六段链落事件。

链：before（既有观察）→ 契约 JSON 先落 CAS（AD-3）→ `action.contracted`
→ `action.policy_cleared`（3.1 默认放行/可注入；四态引擎属 3.3）
→ `action.executed` → after（观察照常采集，带 last_action）
→ `verification.{passed|deviated|inconclusive|errored}`（核验器注册表聚合）。

缺段 → `action.policy_denied`{phase:contract} + ContractIncompleteError，
被拒动作不触环境、不耗预算。幂等键/补偿为预留字段（Stage 3 激活）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from vasta_contracts import (
    ActionContract,
    ContractIncompleteError,
    Plan,
    VerificationPipeline,
    missing_segments,
)
from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action, Observation, Verifier

from .budget import BudgetExceededError
from .gateway import ToolNotRegisteredError
from .observation import TerminalObservationError
from .recovery import (
    RecoveryInput,
    RecoveryLimitExceededError,
)
from .state import RunState


@dataclass(frozen=True)
class PolicyOutcome:
    """3.1 最小策略结果（四态引擎在 Story 3.3 替换本 Callable）。"""

    decision: str  # allow | deny
    reason: str = "default_allow_3.1"


PolicyCheck = Callable[[ActionContract], PolicyOutcome]


class PolicyDeniedError(VastaError):
    def __init__(self, reason: str, *, phase: str = "policy") -> None:
        super().__init__(
            code="policy.denied",
            message=f"动作被策略拒绝（{phase}）: {reason}",
            retryable=False,
        )
        self.reason = reason
        self.phase = phase


def _aggregate_outcomes(outcomes: list[str], unregistered: list[str]) -> tuple[str, dict[str, Any]]:
    """核验聚合：任一 deviation → deviated；任一 system_error → errored；
    其余（含空注册表/未注册名）→ inconclusive；全 pass → passed。"""
    detail: dict[str, Any] = {}
    if unregistered:
        # 声明的核验器未全部运行——不得宣称 pass
        detail["unregistered"] = unregistered
        return "inconclusive", detail
    if not outcomes:
        return "inconclusive", {"reason": "no_verifiers_configured"}
    if "system_error" in outcomes:
        return "errored", detail
    if "deviation" in outcomes:
        return "deviated", detail
    if outcomes and all(o == "pass" for o in outcomes):
        return "passed", detail
    return "inconclusive", detail


class ContractedMixin:
    """挂载于 RunEngine（同包内访问其执行设施）。"""

    async def execute_contracted(
        self,
        contract: ActionContract,
        *,
        policy_check: PolicyCheck | None = None,
        verifiers: Mapping[str, Verifier] | None = None,
        plan_step_id: str = "default",
        approved: bool = False,
        plan: Plan | None = None,
        confirm: bool = False,
    ) -> list[Observation]:
        """契约化执行写动作：六段链全部落事件（NFR-001）。

        confirm：接管模式（takeover）下需 True 才放行（FR-052）。"""
        self._require_started("execute_contracted")  # noqa: SLF001
        await self._takeover_gate("execute_contracted", confirm)  # noqa: SLF001
        self.context.require_replay_adapter(self.env)  # noqa: SLF001
        action = Action(tool=contract.tool, args=contract.args)

        # ── 契约段：缺段即拒（不执行、不耗预算）──
        missing = missing_segments(contract)
        if missing:
            await self._emit(  # noqa: SLF001
                "action.policy_denied",
                {
                    "phase": "contract",
                    "tool": contract.tool,
                    "missing_segments": missing,
                    "basis": "FR-031 必填段缺失",
                },
            )
            raise ContractIncompleteError(missing)

        # AD-3：契约 JSON 先落盘校验，事件才引用
        contract_sha = await self.store.save_artifact(  # noqa: SLF001
            contract.model_dump_json().encode("utf-8"),
            mime="application/json",
            source="action.contract",
            tenant_id=self.config.tenant_id,  # noqa: SLF001
            project_id=self.config.project_id,  # noqa: SLF001
        )
        await self._emit(  # noqa: SLF001
            "action.contracted",
            {
                "tool": contract.tool,
                "risk": contract.risk,
                "contract_ref": contract_sha,
                # 预留字段（AD-11/FR-038，Stage 3 激活）
                "idempotency_key": contract.idempotency_key,
                "compensation": contract.compensation,
            },
        )

        # ── 工具注册与分类（前置：策略判定需要 effective 风险，AD-4×FR-033）──
        risk_effective: str | None = None
        read_only: bool | None = None
        if self.tool_gateway is not None:  # noqa: SLF001
            try:
                read_only, risk_effective = self.tool_gateway.classify(contract.tool)
            except ToolNotRegisteredError as exc:
                await self._emit(  # noqa: SLF001
                    "action.policy_denied",
                    {"phase": "tool", "tool": contract.tool,
                     "basis": "工具未在网关注册（清单缺失）"},
                )
                raise VastaError(
                    code="tool.not_registered",
                    message=f"工具 {contract.tool!r} 未注册，写动作不执行",
                ) from exc
        effective_risk = risk_effective or contract.risk  # 无网关时以自报为准

        # ── 策略段（优先级：显式 callable（3.1 兼容）> policy_engine > 默认放行）──
        if policy_check is not None:
            outcome = policy_check(contract)
            if outcome.decision != "allow":
                await self._emit(  # noqa: SLF001
                    "action.policy_denied",
                    {"phase": "policy", "tool": contract.tool, "basis": outcome.reason},
                )
                raise PolicyDeniedError(outcome.reason)
            await self._emit(  # noqa: SLF001
                "action.policy_cleared",
                {"tool": contract.tool, "decision": "allow", "basis": outcome.reason},
            )
        elif self.policy_engine is not None:  # noqa: SLF001
            await self._apply_policy_decision(
                contract, effective_risk, approved=approved
            )
        else:
            await self._emit(  # noqa: SLF001
                "action.policy_cleared",
                {"tool": contract.tool, "decision": "allow",
                 "basis": "default_allow_3.1", "risk_effective": effective_risk},
            )

        # ── 守卫与预算（与 step 同语义）──
        try:
            self.collector.ensure_actable()  # noqa: SLF001
        except TerminalObservationError as exc:
            raise VastaError(code="run.terminal", message=str(exc)) from exc
        escalation = self.supervisor.check_loop(self._last_signature, action)  # noqa: SLF001
        if escalation is not None:
            await self._escalate(escalation)  # noqa: SLF001
        # AD-11：重放命中不是新动作——预算闸对其放行（结果仍由网关缓存返回）
        is_replay = (
            self.tool_gateway is not None  # noqa: SLF001
            and self.tool_gateway.is_replay(  # noqa: SLF001
                self.config.run_id, plan_step_id, action  # noqa: SLF001
            )
        )
        if not is_replay:
            try:
                self.tracker.check()  # noqa: SLF001
            except BudgetExceededError as exc:
                await self._safe_stop(reason=exc.kind.value, safe_stop=True)  # noqa: SLF001
                raise

        # ── 执行段（网关路径 / env 直连路径），之后统一走 after+核验段 ──
        if self.tool_gateway is not None:  # noqa: SLF001
            observations = await self._execute_via_gateway(
                contract, action, plan_step_id=plan_step_id,
                risk_effective=risk_effective, read_only=read_only,
            )
        else:
            try:
                observations = await self.env.execute(action)  # noqa: SLF001
            except Exception as exc:
                await self._emit(  # noqa: SLF001
                    "action.failed",
                    {"tool": contract.tool, "phase": "execution",
                     "error": f"{type(exc).__name__}: {exc}"},
                )
                await self.fail(f"env_error:{type(exc).__name__}")  # noqa: SLF001
                raise
            self.tracker.record_action()  # noqa: SLF001
            self._last_action = action  # noqa: SLF001
            await self._emit(  # noqa: SLF001
                "action.executed",
                {"tool": contract.tool, "ok": True},
            )

        # ── after 段：观察照常采集（带 last_action）──
        for obs in observations:
            await self._record_observation(obs, action=action)  # noqa: SLF001

        # ── 核验段（3.4：VerificationPipeline 替代内联注册表循环）──
        pipeline = VerificationPipeline(dict(verifiers) if verifiers else None)
        evidence: dict[str, Any] = {
            "contract_ref": contract_sha,
            "tool": contract.tool,
            "after_observation": observations[-1] if observations else None,
            "expected_changes": (contract.prediction.changes if contract.prediction else []),
        }
        # 网关路径：ToolResult 原始响应已落 CAS——回读入 evidence（INV-06：
        # 核验器读独立证据，不依赖执行模型自评）
        executed_events = [
            e for e in self.store.iter_run_events(self.config.run_id)  # noqa: SLF001
            if e.type == "action.executed"
        ]
        if executed_events and "result_ref" in executed_events[-1].payload:
            import json as _json

            result_raw = await self.store.get_artifact(  # noqa: SLF001
                executed_events[-1].payload["result_ref"]
            )
            evidence["result"] = _json.loads(result_raw)
        aggregate, detail = await pipeline.run(
            contract.verify_with or [], f"sha256:{contract_sha}", evidence
        )
        verification_event = await self._emit(  # noqa: SLF001
            f"verification.{aggregate}",
            {"tool": contract.tool, "verify_with": contract.verify_with, **detail},
        )
        if aggregate == "deviated":
            # FR-037：偏差 → 依赖计划失效 + 有界恢复分派（不盲目重试放大）
            recovery_payload = await self._on_deviation(
                contract, plan=plan,
                verification_seq=verification_event.seq,
                contract_ref=contract_sha,
            )
            if recovery_payload:
                # 已达恢复上限 → fail(safe_stop)，payload 带偏差上下文
                await self.fail("recovery_limit", safe_stop=True)  # noqa: SLF001
                raise RecoveryLimitExceededError(
                    recovery_payload["attempts"], "max_side_effects"
                )
        return observations

    async def _on_deviation(  # noqa: SLF001（同包 mixin 访问引擎设施）
        self,
        contract: ActionContract,
        *,
        plan: Plan | None,
        verification_seq: int,
        contract_ref: str,
    ) -> dict[str, Any] | None:
        """偏差联动（Story 3.5）：计划失效 + 故障分类 + 恢复分派。

        返回 None = 已分派可继续；返回 payload dict = 恢复预算耗尽
        （调用方转安全停止）。事件：plan.invalidated / action.recovered。"""
        invalidated: list[str] = []
        if plan is not None and plan.status == "active":
            affected = plan.invalidate(
                reason=f"verification deviation at seq {verification_seq}"
            )
            invalidated = [s.step_id for s in affected]
            await self._emit(
                "plan.invalidated",
                {
                    "plan_id": plan.plan_id,
                    "reason": f"偏差（契约 {contract_ref[:12]}…，核验 seq {verification_seq}）",
                    "invalidated_steps": invalidated,
                },
            )
        # 偏差喂 Supervisor（FR-053 联动：连续 M 次触发升级）
        escalation = self.supervisor.note_deviation(True)  # noqa: SLF001
        if escalation is not None:
            await self._escalate(escalation)  # noqa: SLF001
        # 故障分类 + 恢复分派（最小规则版：以核验偏差 + 工具结果为证据）
        incident = RecoveryInput(
            tool_ok=True,
            read_back_ok=False,
            verification_deviated=True,
        )
        try:
            decision = self.recovery.decide(incident)
        except RecoveryLimitExceededError:
            return {"attempts": self.recovery.side_effects_used}  # type: ignore[return-value]
        await self._emit(
            "action.recovered",
            {
                "tool": contract.tool,
                "attempt": decision.attempt,
                "fault_class": decision.fault_class,
                "action": decision.action,
                "reason": decision.reason,
                "invalidated_steps": invalidated,
                "verification_seq": verification_seq,
                "recovery": self.recovery.payload(),
            },
        )
        return None


    async def _apply_policy_decision(  # noqa: SLF001（同包 mixin 访问引擎设施）
        self,
        contract: ActionContract,
        effective_risk: str,
        *,
        approved: bool,
    ) -> None:
        """四态策略（FR-033/AD-12，Story 3.3）：含 fail-closed 回退与批准闭环。"""
        from vasta_policy import ApprovalRequestedError, fail_closed_fallback

        try:
            decision = self.policy_engine.decide(contract, effective_risk)
        except Exception:
            decision = fail_closed_fallback(effective_risk)  # AD-12

        basis = decision.basis
        if decision.decision == "deny":
            await self._emit(
                "action.policy_denied",
                {"phase": "policy", "tool": contract.tool, "basis": basis,
                 "risk_effective": effective_risk,
                 "fail_closed": "fail-closed" in basis},
            )
            raise PolicyDeniedError(basis)
        if decision.decision == "request_approval":
            if approved:
                await self._emit(
                    "action.approved",
                    {"tool": contract.tool, "risk": effective_risk,
                     "via": "human-local", "basis": basis},
                )
                return
            await self._emit(
                "action.approval_requested",
                {"tool": contract.tool, "risk": effective_risk, "basis": basis},
            )
            cp = self._build_checkpoint()
            self._checkpoint = cp
            self.tracker.pause()  # 等待人工批准期间墙钟不计费
            await self._transition(
                RunState.PAUSED,
                "run.paused",
                {"checkpoint": cp.model_dump(mode="json"),
                 "approval": {"tool": contract.tool, "risk": effective_risk,
                              "basis": basis}},
            )
            raise ApprovalRequestedError(contract.tool, effective_risk, basis)
        # allow / degrade：降级路径必录事件（degraded 标志）
        await self._emit(
            "action.policy_cleared",
            {"tool": contract.tool, "decision": decision.decision, "basis": basis,
             "risk_effective": effective_risk, "degraded": decision.degraded},
        )

    async def _execute_via_gateway(  # noqa: SLF001（同包 mixin 访问引擎设施）
        self,
        contract: ActionContract,
        action: Action,
        *,
        plan_step_id: str,
        risk_effective: str | None,
        read_only: bool | None,
    ) -> list[Observation]:
        """网关执行路径（AD-4/11，Story 3.2）。

        - ToolResult 原始响应先落 CAS（FR-010）再入事件；
        - replay 命中不计预算（重复请求非新动作）；
        - after 段为合成 observation.external（引用 result_sha，带 last_action）。
        """
        try:
            result = await self.tool_gateway.execute(
                run_id=self.config.run_id,
                plan_step_id=plan_step_id,
                action=action,
            )
        except Exception as exc:
            await self._emit(
                "action.failed",
                {"tool": contract.tool, "phase": "execution",
                 "error": f"{type(exc).__name__}: {exc}"},
            )
            await self.fail(f"tool_error:{type(exc).__name__}")
            raise
        result_sha = await self.store.save_artifact(
            result.model_dump_json().encode("utf-8"),
            mime="application/json",
            source="tool.response",
            tenant_id=self.config.tenant_id,
            project_id=self.config.project_id,
        )
        if not result.replayed:  # 首次执行才计预算（AD-11）
            self.tracker.record_action()
        self._last_action = action
        await self._emit(
            "action.executed",
            {
                "tool": contract.tool,
                "ok": result.ok,
                "replayed": result.replayed,
                "risk_declared": contract.risk,
                "risk_effective": risk_effective,  # AD-4：清单强制
                "read_only": read_only,
                "result_ref": result_sha,
            },
        )
        after_obs = Observation(
            kind="external",
            artifact_refs=[result_sha],
            detail={
                "source": "tool",
                "tool": contract.tool,
                "ok": result.ok,
                "replayed": result.replayed,
            },
        )
        # 不在此记录——由 execute_contracted 统一走 after 段（含 last_action）
        return [after_obs]


__all__ = ["ContractedMixin", "PolicyDeniedError", "PolicyOutcome"]
