"""Story 3.5：偏差失效与有界恢复（FR-037，AC-04）。"""

from __future__ import annotations

import pytest

from vasta_contracts import Plan, PlanStep, make_complete_contract
from vasta_protocols.protocols import Observation
from vasta_runtime import (
    RecoveryInput,
    RecoveryLimitExceededError,
    RecoveryPolicy,
    RecoveryTracker,
    RunContext,
    RunEngine,
    Supervisor,
    SupervisorConfig,
    SupervisorEscalationError,
)
from vasta_runtime.recovery import FaultClass, classify_fault

from .fakes import FakeStorageAdapter


class Env:
    protocol_version = "0.1.0"

    def __init__(self) -> None:
        self.execute_count = 0

    async def reset(self, seed=None):
        return Observation(kind="decision", available_actions=["x"])

    async def observe(self):
        return Observation(kind="decision", available_actions=["x"])

    async def execute(self, action):
        self.execute_count += 1
        return [Observation(kind="transition"), Observation(kind="decision")]

    async def status(self):
        class S:
            running = True

        return S()


class DeviationVerifier:
    """核验恒偏差——用于偏差注入。"""

    protocol_version = "0.1.0"

    def __init__(self):
        from vasta_protocols.protocols import VerifierManifest

        self.manifest = VerifierManifest(name="read_back", version="1", kind="read_back")

    async def verify(self, contract_ref, evidence):
        from vasta_protocols.protocols import Verification

        return Verification(outcome="deviation")


async def make_engine(**kwargs):
    store = FakeStorageAdapter()
    engine = await RunEngine.create(
        env=Env(), store=store,
        run_context=RunContext.create(run_id="run-r", seed=1),
        **kwargs,
    )
    await engine.start()
    await engine.reset(seed=1)
    return engine, store


def events(store):
    return list(store.iter_run_events("run-r"))


def types_of(store):
    return [e.type for e in events(store)]


def make_plan(n_steps=3) -> Plan:
    return Plan(
        plan_id="plan-1",
        goal="批量核验订单",
        steps=[PlanStep(step_id=f"s{i}", tool="set_status") for i in range(n_steps)],
    )


class TestPlanInvalidation:
    def test_invalidate_cascades_and_is_idempotent(self) -> None:
        plan = make_plan(3)
        affected = plan.invalidate("deviation")
        assert len(affected) == 3
        assert plan.status == "invalidated"
        assert all(s.status == "invalidated" for s in plan.steps)
        assert plan.executable_steps == []  # AC-04：失效后无可执行步
        assert plan.invalidate("again") == []  # 幂等
        assert plan.invalidated_reason == "deviation"

    async def test_deviation_invalidates_plan_completely(self) -> None:
        """AC-04 核心：偏差注入 → 旧计划 100% 失效、不继续批量执行。"""
        engine, store = await make_engine()
        plan = make_plan(3)
        await engine.execute_contracted(
            make_complete_contract(),
            verifiers={"read_back": DeviationVerifier()},
            plan=plan,
        )
        assert plan.status == "invalidated"
        assert plan.executable_steps == []  # 100% 失效
        types = types_of(store)
        assert "plan.invalidated" in types
        assert "action.recovered" in types  # 恢复分派已落事件
        env: Env = engine.env  # type: ignore[assignment]
        # 后续步不再执行（计划失效后 executable_steps 为空——引擎侧通过
        # 调用方检查；此处断言环境只被执行了一次即首个偏差动作）
        assert env.execute_count == 1

    async def test_no_plan_deviation_still_recovers(self) -> None:
        engine, store = await make_engine()
        await engine.execute_contracted(
            make_complete_contract(),
            verifiers={"read_back": DeviationVerifier()},
        )
        assert "action.recovered" in types_of(store)


class TestFaultClassification:
    def test_classification_rules(self) -> None:
        assert classify_fault(
            RecoveryInput(permission_denied=True)
        ) == FaultClass.PERMISSION_DENIED
        assert classify_fault(
            RecoveryInput(external_change_in_window=True)
        ) == FaultClass.EXTERNAL_CHANGE
        assert classify_fault(
            RecoveryInput(tool_ok=False)
        ) == FaultClass.TOOL_ERROR
        assert classify_fault(
            RecoveryInput(read_back_ok=False, verification_deviated=True)
        ) == FaultClass.ENVIRONMENT_DELAY
        assert classify_fault(
            RecoveryInput()
        ) == FaultClass.MODEL_MISCONCEPTION


class TestBoundedRecovery:
    def test_retry_budget_then_escalate(self) -> None:
        tracker = RecoveryTracker(RecoveryPolicy(max_retries=2))
        d1 = tracker.decide(RecoveryInput(read_back_ok=False, verification_deviated=True))
        assert d1.action == "retry"  # 环境延迟 → 重试
        d2 = tracker.decide(RecoveryInput(read_back_ok=False, verification_deviated=True))
        assert d2.action == "retry"
        d3 = tracker.decide(RecoveryInput(read_back_ok=False, verification_deviated=True))
        assert d3.action == "human_takeover"  # 重试额度耗尽 → 接管

    def test_side_effect_limit_safe_stop(self) -> None:
        tracker = RecoveryTracker(RecoveryPolicy(max_retries=0, max_side_effects=2))
        tracker.decide(RecoveryInput(tool_ok=False))  # tool_error → compensate
        tracker.decide(RecoveryInput(tool_ok=False))
        with pytest.raises(RecoveryLimitExceededError):
            tracker.decide(RecoveryInput(tool_ok=False))  # 达上限

    async def test_engine_recovery_limit_safe_stops(self) -> None:
        engine, store = await make_engine(
            recovery_policy=RecoveryPolicy(max_retries=0, max_side_effects=1)
        )
        contract = make_complete_contract()
        verifier = {"read_back": DeviationVerifier()}
        # 第一次偏差：恢复（model_misconception → replan，1 次副作用）
        await engine.execute_contracted(contract, verifiers=verifier)
        assert "action.recovered" in types_of(store)
        assert engine.state.value == "started"
        # 第二次偏差：恢复预算耗尽 → 安全停止
        with pytest.raises(Exception):  # noqa: B017（RecoveryLimitExceeded）
            await engine.execute_contracted(contract, verifiers=verifier)
        assert engine.state.value == "failed"
        failed = [e for e in events(store) if e.type == "run.failed"][-1]
        assert failed.payload["safe_stop"] is True
        assert failed.payload["reason"] == "recovery_limit"

    async def test_recovery_count_persists_across_deviations(self) -> None:
        engine, _ = await make_engine(
            recovery_policy=RecoveryPolicy(max_retries=0, max_side_effects=3),
            supervisor=Supervisor(SupervisorConfig(deviation_threshold=99)),
        )
        verifier = {"read_back": DeviationVerifier()}
        for _ in range(3):
            await engine.execute_contracted(make_complete_contract(), verifiers=verifier)
        assert engine.recovery.side_effects_used == 3


class TestSupervisorLinkage:
    async def test_deviation_feeds_supervisor_escalation(self) -> None:
        """FR-053 联动：连续偏差（M 次）→ Supervisor 升级暂停。"""
        engine, store = await make_engine(
            supervisor=Supervisor(SupervisorConfig(deviation_threshold=3)),
            recovery_policy=RecoveryPolicy(max_retries=0, max_side_effects=10),
        )
        verifier = {"read_back": DeviationVerifier()}
        await engine.execute_contracted(make_complete_contract(), verifiers=verifier)
        await engine.execute_contracted(make_complete_contract(), verifiers=verifier)
        with pytest.raises(SupervisorEscalationError):
            await engine.execute_contracted(make_complete_contract(), verifiers=verifier)
        assert engine.state.value == "paused"
        types = types_of(store)
        assert "incident.opened" in types
        assert types[-1] == "run.paused"


class TestRecoveryEventPayload:
    async def test_recovered_event_carries_context(self) -> None:
        engine, store = await make_engine()
        await engine.execute_contracted(
            make_complete_contract(),
            verifiers={"read_back": DeviationVerifier()},
        )
        recovered = [e for e in events(store) if e.type == "action.recovered"][-1]
        payload = recovered.payload
        assert payload["fault_class"] == "environment_delay"
        assert payload["action"] == "retry"
        assert payload["attempt"] == 1
        assert "verification_seq" in payload  # 偏差定位引用
        assert "recovery" in payload  # 恢复预算快照
