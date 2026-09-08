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

from vasta_contracts import ActionContract, ContractIncompleteError, missing_segments
from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action, Observation, Verifier

from .budget import BudgetExceededError
from .observation import TerminalObservationError


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
    ) -> list[Observation]:
        """契约化执行写动作：六段链全部落事件（NFR-001）。"""
        self._require_started("execute_contracted")  # noqa: SLF001
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

        # ── 策略段（3.1 最小：默认放行；3.3 四态引擎）──
        check = policy_check or (lambda _c: PolicyOutcome(decision="allow"))
        outcome = check(contract)
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

        # ── 守卫与预算（与 step 同语义）──
        try:
            self.collector.ensure_actable()  # noqa: SLF001
        except TerminalObservationError as exc:
            raise VastaError(code="run.terminal", message=str(exc)) from exc
        escalation = self.supervisor.check_loop(self._last_signature, action)  # noqa: SLF001
        if escalation is not None:
            await self._escalate(escalation)  # noqa: SLF001
        try:
            self.tracker.check()  # noqa: SLF001
        except BudgetExceededError as exc:
            await self._safe_stop(reason=exc.kind.value, safe_stop=True)  # noqa: SLF001
            raise

        # ── 执行段 ──
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

        # ── 核验段：注册表聚合（3.4 组合核验器接线）──
        registry = verifiers or {}
        outcomes: list[str] = []
        unregistered: list[str] = []
        evidence = {"contract_ref": contract_sha, "tool": contract.tool}
        for name in contract.verify_with or []:
            verifier = registry.get(name)
            if verifier is None:
                unregistered.append(name)
                continue
            result = await verifier.verify(f"sha256:{contract_sha}", evidence)
            outcomes.append(result.outcome)
        aggregate, detail = _aggregate_outcomes(outcomes, unregistered)
        await self._emit(  # noqa: SLF001
            f"verification.{aggregate}",
            {"tool": contract.tool, "verify_with": contract.verify_with,
             "outcomes": outcomes, **detail},
        )
        return observations


__all__ = ["ContractedMixin", "PolicyDeniedError", "PolicyOutcome"]
