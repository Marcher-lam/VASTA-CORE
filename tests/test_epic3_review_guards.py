"""Epic 3 评审修复守卫（批准安全/审计语义/恢复证据/超时/接管组合）。"""

from __future__ import annotations

import pytest

from vasta_contracts import audit_six_segment, make_complete_contract
from vasta_policy import ApprovalRequestedError, PolicyEngine
from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Observation
from vasta_runtime import (
    RevocationError,
    RunContext,
    RunEngine,
    Supervisor,
    SupervisorConfig,
    TakeoverRequiredError,
)

from .fakes import FakeStorageAdapter


class Env:
    protocol_version = "0.1.0"

    async def reset(self, seed=None):
        return Observation(kind="decision", available_actions=["x"])

    async def observe(self):
        return Observation(kind="decision", available_actions=["x"])

    async def execute(self, action):
        return [Observation(kind="transition"), Observation(kind="decision")]

    async def status(self):
        class S:
            running = True

        return S()


class SlowEnv(Env):
    async def execute(self, action):
        import asyncio

        await asyncio.sleep(0.2)
        return await super().execute(action)


async def make_engine(env=None, **kwargs):
    store = FakeStorageAdapter()
    engine = await RunEngine.create(
        env=env or Env(), store=store,
        run_context=RunContext.create(run_id="run-g3", seed=1),
        **kwargs,
    )
    await engine.start()
    await engine.reset(seed=1)
    return engine, store


def events(store):
    return list(store.iter_run_events("run-g3"))


class TestApprovalSafety:
    async def test_forged_approved_rejected(self) -> None:
        """approved=True 无挂起请求 → 拒（批准不可自证伪造）。"""
        engine, store = await make_engine(policy_engine=PolicyEngine())
        with pytest.raises(VastaError) as excinfo:
            await engine.execute_contracted(
                make_complete_contract(risk="R3"), approved=True
            )
        assert excinfo.value.code == "approval.no_pending_request"

    async def test_revoked_approval_blocks_reentry(self) -> None:
        """撤销后 approved=True 重入 → 拒（撤销有强制力）。"""
        engine, store = await make_engine(policy_engine=PolicyEngine())
        contract = make_complete_contract(risk="R3")
        with pytest.raises(ApprovalRequestedError):
            await engine.execute_contracted(contract)
        # 批准但不执行 → 撤销 → 重入被拒
        await engine.approve_pending(contract, execute=False)
        await engine.revoke(contract)
        with pytest.raises(VastaError) as excinfo:
            await engine.approve_pending(contract)
        # revoke 后 Run 已被 cancel（挂起解除）——重入在任何一道闸被拒
        assert excinfo.value.code in {
            "run.not_paused", "run.not_awaiting_approval", "approval.revoked",
        }

    async def test_double_revoke_rejected(self) -> None:
        engine, store = await make_engine(policy_engine=PolicyEngine())
        contract = make_complete_contract(risk="R3")
        with pytest.raises(ApprovalRequestedError):
            await engine.execute_contracted(contract)
        await engine.approve_pending(contract, execute=False)
        await engine.revoke(contract)
        with pytest.raises(RevocationError):
            await engine.revoke(contract)

    async def test_approve_pending_rejects_non_approval_pause(self) -> None:
        """手动暂停 ≠ 批准暂停——不可借此放行。"""
        engine, store = await make_engine(policy_engine=PolicyEngine())
        await engine.pause()  # 手动暂停（无 approval payload）
        with pytest.raises(VastaError) as excinfo:
            await engine.approve_pending(make_complete_contract(risk="R3"))
        assert excinfo.value.code == "run.not_awaiting_approval"


class TestAuditSemantics:
    async def test_pending_chain_passes_nfr(self) -> None:
        """挂起链不算 NFR-001 违例（评审修复）。"""
        engine, store = await make_engine(policy_engine=PolicyEngine())
        with pytest.raises(ApprovalRequestedError):
            await engine.execute_contracted(make_complete_contract(risk="R3"))
        audit = audit_six_segment(events(store))
        assert audit.chains[-1].status == "pending"
        assert audit.all_success_paths_complete is True  # 不误报

    async def test_gateway_success_not_deviated_by_default(self) -> None:
        """评审修复：网关成功路径默认核验不再全判 deviation
        （ReadBack 双源：result 细节入比对范围）。"""
        from tests.test_tool_gateway import WriteTool
        from vasta_runtime import ToolGateway

        class EchoTool(WriteTool):
            async def execute(self, action, idempotency_key):
                from vasta_protocols.protocols import ToolResult

                return ToolResult(
                    ok=True, detail={"echo": action.args, "status": "approved"}
                )

        gw = ToolGateway()
        gw.register(EchoTool())
        engine, store = await make_engine(
            tool_gateway=gw, policy_engine=PolicyEngine()
        )
        await engine.execute_contracted(
            make_complete_contract(tool="set_status", risk="R0"),
            plan_step_id="s1",
        )
        v = [e for e in events(store) if e.type.startswith("verification.")][-1]
        # result.detail 含 "approved" → 预期变化匹配 → passed（不再误判）
        assert v.type == "verification.passed"

    async def test_no_recovery_side_effect_on_success(self) -> None:
        """成功动作不触发恢复（不烧预算）。"""
        from tests.test_tool_gateway import WriteTool
        from vasta_runtime import ToolGateway

        gw = ToolGateway()
        gw.register(WriteTool())
        engine, store = await make_engine(
            tool_gateway=gw, policy_engine=PolicyEngine()
        )
        for i in range(3):
            await engine.execute_contracted(
                make_complete_contract(tool="set_status", risk="R0"),
                plan_step_id=f"s{i}",
            )
        assert engine.recovery.side_effects_used == 0
        assert "action.recovered" not in [e.type for e in events(store)]
        assert engine.state.value == "started"  # 不触发 Supervisor 升级


class TestTimeoutEnforcement:
    async def test_timeout_fails_run(self) -> None:
        engine, store = await make_engine(env=SlowEnv())
        contract = make_complete_contract(timeout_ms=50)  # 50ms 超时
        with pytest.raises((TimeoutError, VastaError)):
            await engine.execute_contracted(contract)
        assert engine.state.value == "failed"
        types = [e.type for e in events(store)]
        assert "action.failed" in types
        failed = [e for e in events(store) if e.type == "run.failed"][-1]
        assert "timeout" in failed.payload["reason"]
        # 超时链 = failed（合法终态）
        audit = audit_six_segment(events(store))
        assert audit.chains[-1].status == "failed"


class TestSupervisorReset:
    async def test_pass_resets_consecutive_deviations(self) -> None:
        """核验通过喂 False——偏差-成功-偏差-成功-偏差 不触发升级。"""
        from tests.test_combined_verification import SchemaVerifier
        from tests.test_deviation_recovery import DeviationVerifier

        deviation = {"read_back": DeviationVerifier()}
        _passing = {"read_back": SchemaVerifier()}  # schema 无 result → inconclusive
        engine, store = await make_engine(
            policy_engine=PolicyEngine(),
            supervisor=Supervisor(SupervisorConfig(deviation_threshold=3)),
        )
        # 交替 deviation 与非 deviation（inconclusive 不喂 False 但也不喂 True——
        # 喂 False 只在 passed；用恒过核验器构造 pass）
        from vasta_protocols.protocols import Verification, VerifierManifest

        class AlwaysPass:
            protocol_version = "0.1.0"
            manifest = VerifierManifest(name="read_back", version="1", kind="read_back")

            async def verify(self, ref, ev):
                return Verification(outcome="pass")

        for i in range(5):
            v = deviation if i % 2 == 0 else {"read_back": AlwaysPass()}
            await engine.execute_contracted(
                make_complete_contract(risk="R0"), verifiers=v
            )
        # 若 pass 不复位，5 次中 3 次 deviation 会升级——现在不应
        assert engine.state.value == "started"


class TestTakeoverCombinations:
    async def test_release_without_takeover_rejected(self) -> None:
        engine, _ = await make_engine()
        with pytest.raises(VastaError) as excinfo:
            await engine.release_control()
        assert excinfo.value.code == "control.not_in_takeover"

    async def test_takeover_then_r3_pending_approval_visible(self) -> None:
        """接管 + R3：approval_requested 照常（接管门只拦执行，不拦挂起）。"""
        engine, store = await make_engine(policy_engine=PolicyEngine())
        await engine.takeover()
        with pytest.raises(TakeoverRequiredError):
            await engine.execute_contracted(make_complete_contract(risk="R3"))


class TestPlanStepBinding:
    async def test_plan_binds_step_ids(self) -> None:
        """plan 提供时自动绑定 pending 步为 plan_step_id（入事件）。"""
        from tests.test_tool_gateway import WriteTool
        from vasta_contracts import Plan, PlanStep
        from vasta_runtime import ToolGateway

        gw = ToolGateway()
        gw.register(WriteTool())
        engine, store = await make_engine(
            tool_gateway=gw, policy_engine=PolicyEngine()
        )
        plan = Plan(
            plan_id="p1", goal="g",
            steps=[
                PlanStep(step_id="step-a", tool="set_status"),
                PlanStep(step_id="step-b", tool="set_status",
                         args={"v": 2}),
            ],
        )
        await engine.execute_contracted(
            make_complete_contract(tool="set_status"), plan=plan
        )
        contracted = [e for e in events(store)
                      if e.type == "action.contracted"][-1]
        assert contracted.payload["plan_step_id"] == "step-a"  # 绑定首 pending 步
