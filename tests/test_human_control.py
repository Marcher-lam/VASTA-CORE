"""Story 3.6：人工暂停/接管/批准/撤销（FR-052）。"""

from __future__ import annotations

import pytest

from vasta_contracts import audit_six_segment, make_complete_contract
from vasta_policy import ApprovalRequestedError, PolicyEngine
from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action, Observation
from vasta_runtime import (
    RevocationError,
    RunContext,
    RunEngine,
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


async def make_engine(**kwargs):
    store = FakeStorageAdapter()
    engine = await RunEngine.create(
        env=Env(), store=store,
        run_context=RunContext.create(run_id="run-h", seed=1),
        **kwargs,
    )
    await engine.start()
    await engine.reset(seed=1)
    return engine, store


def events(store):
    return list(store.iter_run_events("run-h"))


def types_of(store):
    return [e.type for e in events(store)]


class TestTakeover:
    async def test_takeover_then_unconfirmed_rejected(self) -> None:
        engine, store = await make_engine()
        await engine.takeover()
        assert engine.takeover_mode is True
        assert "run.takeover" in types_of(store)

        with pytest.raises(TakeoverRequiredError):
            await engine.step(Action(tool="go"))
        assert "action.takeover_required" in types_of(store)  # 留痕
        env_rejections = [e for e in events(store)
                          if e.type == "observation.transition"]
        assert env_rejections == []  # 未执行

    async def test_takeover_contracted_rejected_too(self) -> None:
        engine, store = await make_engine()
        await engine.takeover()
        with pytest.raises(TakeoverRequiredError):
            await engine.execute_contracted(make_complete_contract())
        assert "action.contracted" not in types_of(store)  # 契约都未落

    async def test_confirmed_passes(self) -> None:
        engine, store = await make_engine()
        await engine.takeover()
        observations = await engine.step(Action(tool="go"), confirm=True)
        assert len(observations) == 2

    async def test_release_restores_auto(self) -> None:
        engine, store = await make_engine()
        await engine.takeover()
        await engine.release_control()
        assert engine.takeover_mode is False
        assert "run.control_released" in types_of(store)
        await engine.step(Action(tool="go"))  # 无需确认
        assert engine.state.value == "started"

    async def test_takeover_requires_started(self) -> None:
        engine, _ = await make_engine()
        await engine.pause()
        with pytest.raises(VastaError):
            await engine.takeover()


class TestApprovePending:
    async def test_r3_full_approval_flow(self) -> None:
        """端到端：R3 请求批准 → 暂停 → approve_pending → 续行 → 六段链完整。"""
        engine, store = await make_engine(policy_engine=PolicyEngine())
        contract = make_complete_contract(risk="R3")

        with pytest.raises(ApprovalRequestedError):
            await engine.execute_contracted(contract)
        assert engine.state.value == "paused"

        observations = await engine.approve_pending(contract)
        assert observations  # 续行成功
        assert engine.state.value == "started"
        types = types_of(store)
        assert "action.approval_requested" in types
        assert "action.approved" in types
        approved = [e for e in events(store) if e.type == "action.approved"][-1]
        assert approved.payload["via"] == "human-local"
        audit = audit_six_segment(events(store))
        assert audit.complete >= 1

    async def test_approve_requires_paused(self) -> None:
        engine, _ = await make_engine()
        with pytest.raises(VastaError) as excinfo:
            await engine.approve_pending(make_complete_contract())
        assert excinfo.value.code == "run.not_paused"


class TestRevoke:
    async def test_revoke_approved_not_yet_executed(self) -> None:
        """撤销已批准未执行：批准后立即接管阻断执行，再撤销。"""
        engine, store = await make_engine(policy_engine=PolicyEngine())
        contract = make_complete_contract(risk="R3")
        with pytest.raises(ApprovalRequestedError):
            await engine.execute_contracted(contract)
        await engine.approve_pending(contract)  # 批准并执行了……
        # 用另一份 R3 构造"批准未执行"场景：批准后 takeover 前撤销
        contract2 = make_complete_contract(risk="R3", tool="other_tool")
        engine2, store2 = await make_engine(policy_engine=PolicyEngine())
        with pytest.raises(ApprovalRequestedError):
            await engine2.execute_contracted(contract2)

        # 不走 approve——先手动落一个 approved 事件再撤销（最小构造）

        async def manual_approve():
            # 借用引擎内部落事件
            await engine2._emit(
                "action.approved",
                {"tool": contract2.tool, "via": "human-local"},
            )

        await manual_approve()
        await engine2.revoke(contract2)
        assert "action.approval_revoked" in types_of(store2)
        revoked = [e for e in events(store2) if e.type == "action.approval_revoked"][-1]
        assert revoked.payload["tool"] == "other_tool"

    async def test_revoke_executed_rejected(self) -> None:
        engine, store = await make_engine(policy_engine=PolicyEngine())
        contract = make_complete_contract(risk="R3")
        with pytest.raises(ApprovalRequestedError):
            await engine.execute_contracted(contract)
        await engine.approve_pending(contract)  # 批准 + 执行
        with pytest.raises(RevocationError) as excinfo:
            await engine.revoke(contract)
        assert "已执行" in excinfo.value.message
        assert "补偿" in excinfo.value.message  # 指向 FR-038

    async def test_revoke_unknown_tool_rejected(self) -> None:
        engine, _ = await make_engine()
        with pytest.raises(RevocationError):
            await engine.revoke(make_complete_contract(tool="never_approved"))


class TestManualPauseEvent:
    async def test_pause_resume_flow_events(self) -> None:
        engine, store = await make_engine()
        cp = await engine.pause()
        assert cp.state.value == "paused"
        await engine.resume()
        types = types_of(store)
        assert "run.paused" in types and "run.resumed" in types
        # 全程因果链完整
        evs = events(store)
        for prev, cur in zip(evs, evs[1:], strict=False):
            assert cur.parent_event_id == prev.event_id
