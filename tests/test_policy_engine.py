"""Story 3.3：策略引擎四态与 fail-closed（FR-033，AD-12）。"""

from __future__ import annotations

import pytest

from vasta_contracts import audit_six_segment, make_complete_contract
from vasta_policy import (
    ApprovalRequestedError,
    PolicyDecision,
    PolicyEngine,
    fail_closed_fallback,
)
from vasta_protocols.protocols import Action, Observation, ToolManifest, ToolResult
from vasta_runtime import PolicyOutcome, RunContext, RunEngine, ToolGateway

from .fakes import FakeStorageAdapter


class ToolEnv:
    protocol_version = "0.1.0"

    def __init__(self) -> None:
        self.execute_count = 0

    async def reset(self, seed=None):
        return Observation(kind="decision", available_actions=["x"])

    async def observe(self):
        return Observation(kind="decision", available_actions=["x"])

    async def execute(self, action: Action):
        self.execute_count += 1
        return [Observation(kind="transition"), Observation(kind="decision")]

    async def status(self):
        class S:
            running = True

        return S()


class WriteTool:
    protocol_version = "0.1.0"

    def __init__(self, *, name="set_status", risk="R2"):
        self.manifest = ToolManifest(
            name=name, version="1", risk=risk, read_only=False, idempotent=True
        )
        self.execute_count = 0

    async def dry_run(self, action):
        from vasta_protocols.protocols import DryRunResult

        return DryRunResult(allowed=True)

    async def execute(self, action, idempotency_key):
        self.execute_count += 1
        return ToolResult(ok=True)

    async def read_back(self, action):
        return Observation(kind="external")

    async def compensate(self, detail):
        return ToolResult(ok=True)


def gateway_with(risk: str) -> ToolGateway:
    gw = ToolGateway()
    gw.register(WriteTool(risk=risk))
    return gw


async def make_engine(**kwargs):
    store = FakeStorageAdapter()
    engine = await RunEngine.create(
        env=ToolEnv(), store=store,
        run_context=RunContext.create(run_id="run-p", seed=1),
        **kwargs,
    )
    await engine.start()
    await engine.reset(seed=1)
    return engine, store


def events(store):
    return list(store.iter_run_events("run-p"))


class TestDefaultRiskMapping:
    async def test_r0_r1_r2_allow(self) -> None:
        for risk in ("R0", "R1", "R2"):
            engine, store = await make_engine(policy_engine=PolicyEngine())
            await engine.execute_contracted(make_complete_contract(risk=risk))
            cleared = [e for e in events(store) if e.type == "action.policy_cleared"]
            assert cleared[-1].payload["decision"] == "allow"
            assert cleared[-1].payload["risk_effective"] == risk

    async def test_r4_denied(self) -> None:
        engine, store = await make_engine(policy_engine=PolicyEngine())
        with pytest.raises(Exception, match="拒绝"):  # noqa: B017
            await engine.execute_contracted(make_complete_contract(risk="R4"))
        denied = [e for e in events(store) if e.type == "action.policy_denied"][-1]
        assert denied.payload["risk_effective"] == "R4"
        env: ToolEnv = engine.env  # type: ignore[assignment]
        assert env.execute_count == 0

    async def test_unknown_risk_fail_closed(self) -> None:
        engine = PolicyEngine()
        decision = engine.decide(make_complete_contract(), "R9")
        assert decision.decision == "deny"


class TestRequestApproval:
    async def test_r3_requests_approval_and_pauses(self) -> None:
        engine, store = await make_engine(policy_engine=PolicyEngine())
        env: ToolEnv = engine.env  # type: ignore[assignment]
        with pytest.raises(ApprovalRequestedError):
            await engine.execute_contracted(make_complete_contract(risk="R3"))

        assert engine.state.value == "paused"  # 暂停等待人工
        assert engine.checkpoint is not None
        assert env.execute_count == 0
        types = [e.type for e in events(store)]
        assert "action.approval_requested" in types
        assert types[-1] == "run.paused"
        paused = [e for e in events(store) if e.type == "run.paused"][-1]
        assert paused.payload["approval"]["risk"] == "R3"

    async def test_approved_r3_executes_after_resume(self) -> None:
        engine, store = await make_engine(policy_engine=PolicyEngine())
        with pytest.raises(ApprovalRequestedError):
            await engine.execute_contracted(make_complete_contract(risk="R3"))
        await engine.resume()  # 人工确认后恢复
        await engine.execute_contracted(
            make_complete_contract(risk="R3"), approved=True
        )
        types = [e.type for e in events(store)]
        assert "action.approved" in types
        assert "action.executed" in types
        approved = [e for e in events(store) if e.type == "action.approved"][-1]
        assert approved.payload["via"] == "human-local"
        # 一次逻辑执行：两条 contracted（首次挂起 + 批准重入）各自可追溯，
        # 但 executed 只有一次；批准重入链六段完整。
        audit = audit_six_segment(events(store))
        assert audit.complete >= 1
        executed = [e for e in events(store) if e.type == "action.executed"]
        assert len(executed) == 1


class TestDegrade:
    async def test_degrade_decision_recorded_and_executes(self) -> None:
        def degrade_rule(contract, risk):
            if contract.tool == "set_status":
                return PolicyDecision(decision="degrade", basis="影子模式降级")
            return None

        engine, store = await make_engine(policy_engine=PolicyEngine([degrade_rule]))
        await engine.execute_contracted(make_complete_contract())
        cleared = [e for e in events(store) if e.type == "action.policy_cleared"][-1]
        assert cleared.payload["decision"] == "degrade"  # 降级路径入事件
        assert "action.executed" in [e.type for e in events(store)]


class TestFailClosed:
    async def test_broken_engine_r2_plus_denied(self) -> None:
        class Broken:
            def decide(self, contract, risk):
                raise RuntimeError("policy db down")

        engine, store = await make_engine(policy_engine=Broken())  # type: ignore[arg-type]
        for risk in ("R2", "R3", "R4"):
            with pytest.raises(Exception, match="fail-closed"):  # noqa: B017
                await engine.execute_contracted(make_complete_contract(risk=risk))
        denied = [e for e in events(store) if e.type == "action.policy_denied"]
        assert all(d.payload.get("fail_closed") for d in denied)
        env: ToolEnv = engine.env  # type: ignore[assignment]
        assert env.execute_count == 0

    async def test_broken_engine_low_risk_degraded_allow(self) -> None:
        class Broken:
            def decide(self, contract, risk):
                raise RuntimeError("down")

        engine, store = await make_engine(policy_engine=Broken())  # type: ignore[arg-type]
        await engine.execute_contracted(make_complete_contract(risk="R0"))
        cleared = [e for e in events(store) if e.type == "action.policy_cleared"][-1]
        assert cleared.payload["degraded"] is True  # 降级路径入事件
        assert "fail-closed" not in cleared.payload["basis"] or True
        assert cleared.payload["basis"] == "策略引擎不可用，低风险放行（降级路径）"

    def test_fallback_pure_function(self) -> None:
        assert fail_closed_fallback("R3").decision == "deny"
        assert fail_closed_fallback("R1").decision == "allow"
        assert fail_closed_fallback("R1").degraded is True


class TestEffectiveRiskDrivesPolicy:
    async def test_manifest_r3_overrides_declared_r0(self) -> None:
        """AD-4×FR-033：策略看清单 effective 风险，不看契约自报。"""
        gw = gateway_with(risk="R3")
        engine, store = await make_engine(policy_engine=PolicyEngine(), tool_gateway=gw)
        with pytest.raises(ApprovalRequestedError):
            await engine.execute_contracted(make_complete_contract(risk="R0"))
        requested = [e for e in events(store) if e.type == "action.approval_requested"][-1]
        assert requested.payload["risk"] == "R3"  # 清单值，非自报 R0


class TestBackwardCompat:
    async def test_callable_still_works(self) -> None:
        engine, store = await make_engine(policy_engine=PolicyEngine())
        with pytest.raises(Exception):  # noqa: B017
            await engine.execute_contracted(
                make_complete_contract(),
                policy_check=lambda _c: PolicyOutcome(decision="deny", reason="拒绝"),
            )
        assert "action.policy_denied" in [e.type for e in events(store)]

    async def test_no_engine_default_allow(self) -> None:
        engine, store = await make_engine()
        await engine.execute_contracted(make_complete_contract(risk="R3"))
        cleared = [e for e in events(store) if e.type == "action.policy_cleared"][-1]
        assert cleared.payload["basis"] == "default_allow_3.1"
        assert cleared.payload["risk_effective"] == "R3"

    async def test_gateway_denied_policy_leaves_no_executed(self) -> None:
        gw = gateway_with(risk="R4")
        engine, store = await make_engine(policy_engine=PolicyEngine(), tool_gateway=gw)
        with pytest.raises(Exception):  # noqa: B017
            await engine.execute_contracted(make_complete_contract(risk="R2"))
        types = [e.type for e in events(store)]
        assert "action.executed" not in types
        tool = gw._tools["set_status"]  # noqa: SLF001
        assert tool.execute_count == 0
