"""Story 1.6：Supervisor 循环检测与持续偏差监控。"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action, Observation
from vasta_runtime.budget import Budget, BudgetExceededError
from vasta_runtime.runner import RunEngine
from vasta_runtime.supervisor import (
    EscalationReason,
    Supervisor,
    SupervisorConfig,
    SupervisorEscalationError,
)

from .fakes import FakeStorageAdapter


class LoopEnv:
    """循环环境：任何动作都回到同一决策签名（状态永不变化）。"""

    protocol_version = "0.1.0"

    def __init__(self) -> None:
        self.execute_count = 0

    async def reset(self, seed: int | None = None) -> Observation:
        return Observation(kind="decision", available_actions=["go"])

    async def observe(self) -> Observation:
        return Observation(kind="decision", available_actions=["go"])

    async def execute(self, action: Action) -> list[Observation]:
        self.execute_count += 1
        return [
            Observation(kind="transition"),
            Observation(kind="decision", available_actions=["go"]),
        ]

    async def status(self) -> object:
        class _S:
            running = True

        return _S()


async def make_engine(
    *, supervisor: Supervisor | None = None, budget: Budget | None = None, env=None
) -> tuple[RunEngine, FakeStorageAdapter, LoopEnv]:
    store = FakeStorageAdapter()
    env = env or LoopEnv()
    engine = await RunEngine.create(
        env=env,
        store=store,
        budget=budget,
        supervisor=supervisor,
    )
    return engine, store, env


def types_of(store: FakeStorageAdapter) -> list[str]:
    run_ids = {e.run_id for e in store.log._by_key.values()}  # noqa: SLF001
    rid = next(iter(run_ids))
    return [e.type for e in store.iter_run_events(rid)]


class TestLoopDetection:
    async def test_loop_escalates_pauses_without_spending_budget(self) -> None:
        sup = Supervisor(SupervisorConfig(loop_threshold=3))
        engine, store, env = await make_engine(supervisor=sup, budget=Budget(max_actions=100))
        await engine.start()
        await engine.reset(seed=1)
        await engine.step(Action(tool="go"))  # count=1 执行
        await engine.step(Action(tool="go"))  # count=2 执行
        with pytest.raises(SupervisorEscalationError) as excinfo:
            await engine.step(Action(tool="go"))  # count=3 → 升级，不执行

        assert excinfo.value.reason is EscalationReason.LOOP
        assert engine.state.value == "paused"
        # 不执行、不耗预算
        assert env.execute_count == 2
        assert engine.tracker.snapshot().actions_used == 2
        # 事件：升级 incident.opened 在前，run.paused 在后
        types = types_of(store)
        assert types[-2:] == ["incident.opened", "run.paused"]
        paused = [e for e in store.log._by_key.values() if e.type == "run.paused"]  # noqa: SLF001
        assert paused[-1].payload["escalation"]["reason"] == "supervisor_loop"

    async def test_threshold_configurable(self) -> None:
        sup = Supervisor(SupervisorConfig(loop_threshold=5))
        engine, store, env = await make_engine(supervisor=sup)
        await engine.start()
        await engine.reset(seed=1)
        for _ in range(4):
            await engine.step(Action(tool="go"))
        with pytest.raises(SupervisorEscalationError):
            await engine.step(Action(tool="go"))
        assert env.execute_count == 4

    async def test_alternating_actions_break_pattern(self) -> None:
        sup = Supervisor(SupervisorConfig(loop_threshold=3))
        engine, _, env = await make_engine(supervisor=sup)
        await engine.start()
        await engine.reset(seed=1)
        for i in range(10):  # go/alt 交替：连续同模式计数最多 1
            await engine.step(Action(tool="go" if i % 2 == 0 else "alt"))
        assert engine.state.value == "started"
        assert env.execute_count == 10

    async def test_resume_resets_loop_counter(self) -> None:
        sup = Supervisor(SupervisorConfig(loop_threshold=2))
        engine, _, env = await make_engine(supervisor=sup)
        await engine.start()
        await engine.reset(seed=1)
        await engine.step(Action(tool="go"))
        with pytest.raises(SupervisorEscalationError):
            await engine.step(Action(tool="go"))
        assert engine.state.value == "paused"

        await engine.resume()  # 人工审阅恢复 → 计数清零
        await engine.step(Action(tool="go"))  # 重新计数，不立即升级
        assert engine.state.value == "started"

    async def test_env_reset_clears_counters(self) -> None:
        sup = Supervisor(SupervisorConfig(loop_threshold=3))
        engine, _, _ = await make_engine(supervisor=sup)
        await engine.start()
        await engine.reset(seed=1)
        await engine.step(Action(tool="go"))
        await engine.step(Action(tool="go"))
        await engine.reset(seed=2)  # 新 episode 清零
        await engine.step(Action(tool="go"))
        await engine.step(Action(tool="go"))
        assert engine.state.value == "started"  # 未达阈值


class TestConsecutiveDeviations:
    async def test_consecutive_deviations_escalate(self) -> None:
        sup = Supervisor(SupervisorConfig(deviation_threshold=3))
        engine, store, _ = await make_engine(supervisor=sup)
        await engine.start()
        await engine.note_deviation(True)
        await engine.note_deviation(True)
        with pytest.raises(SupervisorEscalationError) as excinfo:
            await engine.note_deviation(True)
        assert excinfo.value.reason is EscalationReason.DEVIATIONS
        assert engine.state.value == "paused"
        types = types_of(store)
        assert types[-2:] == ["incident.opened", "run.paused"]

    async def test_non_deviation_resets_streak(self) -> None:
        sup = Supervisor(SupervisorConfig(deviation_threshold=3))
        engine, _, _ = await make_engine(supervisor=sup)
        await engine.start()
        await engine.note_deviation(True)
        await engine.note_deviation(True)
        await engine.note_deviation(False)  # 打断连续性
        await engine.note_deviation(True)
        await engine.note_deviation(True)
        assert engine.state.value == "started"  # 连续仅 2，未达 3

    async def test_note_deviation_requires_started(self) -> None:
        engine, _, _ = await make_engine()
        with pytest.raises(VastaError):
            await engine.note_deviation(True)


class TestBudgetCoordination:
    async def test_budget_first_safe_stops(self) -> None:
        """预算先到 → 安全停止（FAILED），非暂停。"""
        sup = Supervisor(SupervisorConfig(loop_threshold=8))
        engine, store, env = await make_engine(
            supervisor=sup, budget=Budget(max_actions=2)
        )
        await engine.start()
        await engine.reset(seed=1)
        await engine.step(Action(tool="go"))
        await engine.step(Action(tool="go"))
        with pytest.raises(BudgetExceededError):
            await engine.step(Action(tool="go"))
        assert engine.state.value == "failed"  # 安全停止而非暂停
        types = types_of(store)
        assert types[-1] == "run.failed"
        assert env.execute_count == 2


class TestSupervisorUnit:
    def test_check_loop_without_signature_noop(self) -> None:
        from vasta_runtime.checkpoint import ObservationSignature

        sup = Supervisor()
        assert sup.check_loop(None, Action(tool="x")) is None
        sig = ObservationSignature(kind="decision", available_actions=("a",))
        assert sup.check_loop(sig, Action(tool="x")) is None  # 计数 1 < 8

    def test_different_args_are_different_patterns(self) -> None:
        from vasta_runtime.checkpoint import ObservationSignature

        sup = Supervisor(SupervisorConfig(loop_threshold=2))
        sig = ObservationSignature(kind="decision", available_actions=("a",))
        assert sup.check_loop(sig, Action(tool="go", args={"i": 1})) is None
        # 参数不同 → 模式不同 → 计数重置
        assert sup.check_loop(sig, Action(tool="go", args={"i": 2})) is None
