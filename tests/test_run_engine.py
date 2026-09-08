"""Story 1.2：Run 生命周期、预算与检查点测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action, Observation
from vasta_runtime.budget import Budget, BudgetExceededError, BudgetKind
from vasta_runtime.checkpoint import Checkpoint
from vasta_runtime.runner import RunConfig, RunEngine
from vasta_runtime.state import InvalidTransitionError, RunState

from .fakes import FakeStorageAdapter


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


class MutableEnv:
    """动作集可变的假环境（用于环境变化检测）。"""

    protocol_version = "0.1.0"
    execute_count = 0

    def __init__(self, actions: list[str]) -> None:
        self.actions = actions

    async def reset(self, seed: int | None = None) -> Observation:
        return Observation(kind="decision", available_actions=list(self.actions))

    async def observe(self) -> Observation:
        return Observation(kind="decision", available_actions=list(self.actions))

    async def execute(self, action: Action) -> list[Observation]:
        self.execute_count += 1
        return [
            Observation(kind="transition"),
            Observation(kind="decision", available_actions=list(self.actions)),
        ]

    async def status(self) -> object:
        class _S:
            running = True

        return _S()


async def make_engine(
    *, budget: Budget | None = None, env: MutableEnv | None = None, clock: FakeClock | None = None
) -> tuple[RunEngine, FakeStorageAdapter, MutableEnv, FakeClock]:
    store = FakeStorageAdapter()
    env = env or MutableEnv(["noop", "finish"])
    clock = clock or FakeClock()
    engine = await RunEngine.create(
        env=env,
        store=store,
        budget=budget,
        config=RunConfig(run_id="run-test"),
        clock=clock,
        safety_clock=clock,  # AD-15：测试注入安全时钟驱动墙钟预算
    )
    return engine, store, env, clock


def events_of(store: FakeStorageAdapter, run_id: str = "run-test"):
    return list(store.iter_run_events(run_id))


class TestStateMachine:
    async def test_full_lifecycle_transitions_emit_events(self) -> None:
        engine, store, *_ = await make_engine()
        types = [e.type for e in events_of(store)]
        assert types == ["run.created"]

        await engine.start()
        await engine.pause()
        await engine.resume()
        await engine.complete()
        types = [e.type for e in events_of(store)]
        assert types == [
            "run.created",
            "run.started",
            "run.paused",
            "observation.decision",  # resume 先重观察并记录（评审修复）
            "run.resumed",
            "run.completed",
        ]
        assert engine.state is RunState.COMPLETED

    async def test_invalid_transitions_rejected(self) -> None:
        engine, store, *_ = await make_engine()
        with pytest.raises(InvalidTransitionError):
            await engine.pause()  # created → paused 非法
        await engine.start()
        with pytest.raises(InvalidTransitionError):
            await engine.start()  # started → started 非法
        await engine.complete()
        with pytest.raises(InvalidTransitionError):
            await engine.pause()  # 终态不可再转移
        assert [e.type for e in events_of(store)] == ["run.created", "run.started", "run.completed"]

    async def test_cancel_from_created(self) -> None:
        engine, store, *_ = await make_engine()
        await engine.cancel()
        assert engine.state is RunState.CANCELLED
        assert events_of(store)[-1].type == "run.cancelled"


class TestCausalChain:
    async def test_every_event_has_parent_chain(self) -> None:
        engine, store, *_ = await make_engine()
        await engine.start()
        await engine.step(Action(tool="noop"))
        await engine.pause()
        await engine.resume()
        await engine.complete()

        events = events_of(store)
        assert events[0].type == "run.created" and events[0].parent_event_id is None
        for prev, cur in zip(events, events[1:], strict=False):
            assert cur.parent_event_id == prev.event_id
        seqs = [e.seq for e in events]
        assert seqs == list(range(len(events)))


class TestBudgetSafeStop:
    async def test_actions_budget_safe_stop(self) -> None:
        engine, store, env, _ = await make_engine(budget=Budget(max_actions=2))
        await engine.start()
        await engine.step(Action(tool="noop"))
        await engine.step(Action(tool="noop"))
        with pytest.raises(BudgetExceededError) as excinfo:
            await engine.step(Action(tool="noop"))
        assert excinfo.value.kind is BudgetKind.ACTIONS

        assert engine.state is RunState.FAILED
        failed = events_of(store)[-1]
        assert failed.type == "run.failed"
        assert failed.payload["safe_stop"] is True
        assert failed.payload["reason"] == "actions"
        assert env.execute_count == 2  # 超限动作未执行（预算先检）

    async def test_wall_seconds_budget_safe_stop(self) -> None:
        clock = FakeClock()
        engine, store, _, _ = await make_engine(
            budget=Budget(max_wall_seconds=10.0), clock=clock
        )
        await engine.start()
        clock.advance(11.0)
        with pytest.raises(BudgetExceededError) as excinfo:
            await engine.step(Action(tool="noop"))
        assert excinfo.value.kind is BudgetKind.WALL_SECONDS
        assert engine.state is RunState.FAILED
        assert events_of(store)[-1].payload["reason"] == "wall_seconds"

    async def test_model_calls_budget_safe_stop(self) -> None:
        engine, store, _, _ = await make_engine(budget=Budget(max_model_calls=1))
        await engine.start()
        await engine.record_model_call()
        with pytest.raises(BudgetExceededError):
            await engine.record_model_call()
        assert engine.state is RunState.FAILED
        assert events_of(store)[-1].type == "run.failed"

    async def test_step_requires_started(self) -> None:
        engine, *_ = await make_engine()
        with pytest.raises(VastaError):
            await engine.step(Action(tool="noop"))


class TestPauseResume:
    async def test_checkpoint_contains_required_fields(self) -> None:
        engine, store, *_ = await make_engine(budget=Budget(max_actions=10))
        await engine.start()
        await engine.step(Action(tool="noop", args={"x": 1}))
        cp = await engine.pause()

        assert isinstance(cp, Checkpoint)
        assert cp.state is RunState.PAUSED
        assert cp.last_action is not None and cp.last_action.tool == "noop"
        assert cp.last_action.args == {"x": 1}
        assert cp.active_plans == []
        assert cp.budget.actions_used == 1
        assert cp.budget.max_actions == 10
        assert cp.last_observation is not None
        assert cp.last_observation.kind == "decision"
        assert engine.checkpoint == cp

    async def test_resume_reobserves_and_detects_env_change(self) -> None:
        env = MutableEnv(["noop", "finish"])
        engine, store, *_ = await make_engine(env=env)
        await engine.start()
        await engine.step(Action(tool="noop"))
        await engine.pause()

        env.actions = ["noop"]  # 暂停期间环境变化：finish 动作消失
        report = await engine.resume()
        assert report.env_changed is True
        resumed = events_of(store)[-1]
        assert resumed.type == "run.resumed"
        assert resumed.payload["env_changed"] is True
        assert resumed.payload["observed_actions"] == ["noop"]
        assert engine.state is RunState.STARTED

    async def test_resume_without_env_change(self) -> None:
        engine, store, *_ = await make_engine()
        await engine.start()
        await engine.pause()
        report = await engine.resume()
        assert report.env_changed is False
        assert events_of(store)[-1].payload["env_changed"] is False

    async def test_step_emits_observation_events(self) -> None:
        engine, store, *_ = await make_engine()
        await engine.start()
        observations = await engine.step(Action(tool="noop"))
        kinds = [o.kind for o in observations]
        types = [e.type for e in events_of(store)]
        assert kinds == ["transition", "decision"]
        assert types == [
            "run.created",
            "run.started",
            "observation.transition",
            "observation.decision",
        ]
