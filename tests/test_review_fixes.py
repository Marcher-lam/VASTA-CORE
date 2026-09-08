"""Epic 1 代码评审修复的回归测试（四层评审 patch 项的钉子）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action, Observation
from vasta_runtime.budget import Budget, BudgetExceededError
from vasta_runtime.runcontext import RunContext
from vasta_runtime.runner import RunConfig, RunEngine
from vasta_runtime.state import RunState
from vasta_runtime.supervisor import (
    Supervisor,
    SupervisorConfig,
    SupervisorEscalationError,
)

from .fakes import FakeStorageAdapter


class SimpleEnv:
    protocol_version = "0.1.0"

    async def reset(self, seed: int | None = None) -> Observation:
        return Observation(kind="decision", available_actions=["go"])

    async def observe(self) -> Observation:
        return Observation(kind="decision", available_actions=["go"])

    async def execute(self, action: Action) -> list[Observation]:
        return [
            Observation(kind="transition"),
            Observation(kind="decision", available_actions=["go"]),
        ]

    async def status(self) -> object:
        class _S:
            running = True

        return _S()


class ExplodingEnv(SimpleEnv):
    async def execute(self, action: Action) -> list[Observation]:
        raise RuntimeError("boom")


async def make_engine(**kwargs) -> tuple[RunEngine, FakeStorageAdapter]:
    store = FakeStorageAdapter()
    engine = await RunEngine.create(
        env=kwargs.pop("env", SimpleEnv()),
        store=store,
        config=RunConfig(run_id="run-cr"),
        **kwargs,
    )
    return engine, store


def types_of(store: FakeStorageAdapter) -> list[str]:
    return [e.type for e in store.iter_run_events("run-cr")]


class TestFailLifecycle:
    async def test_fail_from_started(self) -> None:
        engine, store = await make_engine()
        await engine.start()
        await engine.fail("operator_abort")
        assert engine.state is RunState.FAILED
        failed = [e for e in store.iter_run_events("run-cr") if e.type == "run.failed"]
        assert failed[-1].payload["safe_stop"] is False
        assert failed[-1].payload["reason"] == "operator_abort"

    async def test_fail_from_paused(self) -> None:
        engine, store = await make_engine()
        await engine.start()
        await engine.pause()
        await engine.fail("human_decision")
        assert engine.state is RunState.FAILED
        assert types_of(store)[-1] == "run.failed"


class TestEscalationCheckpoint:
    async def test_escalation_builds_checkpoint_and_resume_detects_change(self) -> None:
        env = SimpleEnv()
        engine, store = await make_engine(
            env=env, supervisor=Supervisor(SupervisorConfig(loop_threshold=2))
        )
        await engine.start()
        await engine.reset(seed=1)
        await engine.step(Action(tool="go"))
        with pytest.raises(SupervisorEscalationError):
            await engine.step(Action(tool="go"))
        assert engine.state is RunState.PAUSED
        assert engine.checkpoint is not None  # 评审修复：升级也建 checkpoint
        paused = [e for e in store.iter_run_events("run-cr") if e.type == "run.paused"]
        assert "checkpoint" in paused[-1].payload  # payload 双键统一
        assert "escalation" in paused[-1].payload

        # 暂停期间环境变化 → resume 检出（依赖 checkpoint，此前静默丢失）
        env.__dict__["_actions_override"] = ["other"]
        orig = env.observe

        async def observe_changed() -> Observation:
            return Observation(kind="decision", available_actions=["other"])

        env.observe = observe_changed  # type: ignore[method-assign]
        report = await engine.resume()
        assert report.env_changed is True
        env.observe = orig  # type: ignore[method-assign]

    async def test_deviation_streak_resets_on_resume(self) -> None:
        engine, _ = await make_engine(
            supervisor=Supervisor(SupervisorConfig(deviation_threshold=2))
        )
        await engine.start()
        await engine.note_deviation(True)
        with pytest.raises(SupervisorEscalationError):
            await engine.note_deviation(True)
        assert engine.state is RunState.PAUSED
        await engine.resume()
        await engine.note_deviation(True)  # 连续性已清零：单次不立即再升级
        assert engine.state is RunState.STARTED


class TestEnvErrorTerminal:
    async def test_execute_exception_fails_run_with_event(self) -> None:
        engine, store = await make_engine(env=ExplodingEnv())
        await engine.start()
        with pytest.raises(RuntimeError):
            await engine.step(Action(tool="go"))
        assert engine.state is RunState.FAILED  # 不卡 STARTED
        failed = types_of(store)[-1]
        assert failed == "run.failed"
        failed_payload = [
            e.payload for e in store.iter_run_events("run-cr") if e.type == "run.failed"
        ][0]
        assert failed_payload["reason"] == "env_error:RuntimeError"


class TestGuards:
    async def test_resume_requires_paused(self) -> None:
        engine, _ = await make_engine()
        with pytest.raises(VastaError) as excinfo:
            await engine.resume()
        assert excinfo.value.code == "run.not_paused"

    async def test_observe_requires_started(self) -> None:
        engine, _ = await make_engine()
        with pytest.raises(VastaError):
            await engine.observe()

    async def test_replay_mode_requires_seed(self) -> None:
        with pytest.raises(ValueError, match="seed"):
            RunContext.create(run_id="r", replay_mode=True)

    async def test_run_context_and_config_ambiguous(self) -> None:
        with pytest.raises(ValueError, match="ambiguous"):
            await RunEngine.create(
                env=SimpleEnv(),
                store=FakeStorageAdapter(),
                config=RunConfig(run_id="x"),
                run_context=RunContext.create(run_id="y"),
            )


class TestWallClockPauseAccounting:
    async def test_paused_time_not_billed(self) -> None:
        class FakeClock:
            def __init__(self) -> None:
                self.now = datetime(2026, 9, 8, tzinfo=UTC)

            def __call__(self) -> datetime:
                return self.now

            def advance(self, s: float) -> None:
                self.now += timedelta(seconds=s)

        clock = FakeClock()
        engine, _ = await make_engine(
            budget=Budget(max_wall_seconds=5.0), safety_clock=clock
        )
        await engine.start()
        await engine.step(Action(tool="go"))
        await engine.pause()
        clock.advance(600.0)  # 人工审阅 10 分钟
        await engine.resume()
        clock.advance(1.0)
        await engine.step(Action(tool="go"))  # 暂停时长不计费：不触发墙钟预算
        assert engine.state is RunState.STARTED


class TestOverBudgetExchangeEvidence:
    async def test_over_budget_exchange_still_persists_artifact(self) -> None:
        from vasta_protocols.protocols import ModelRequest, ModelResponse

        store = FakeStorageAdapter()
        engine = await RunEngine.create(
            env=SimpleEnv(),
            store=store,
            budget=Budget(max_model_calls=1),
            config=RunConfig(run_id="run-cr"),
        )
        await engine.start()
        await engine.record_model_exchange(
            ModelRequest(prompt="a"), ModelResponse(content="b")
        )
        with pytest.raises(BudgetExceededError):
            await engine.record_model_exchange(
                ModelRequest(prompt="c"), ModelResponse(content="d")
            )
        # 证据先于预算：超限这一次的交换载荷也已落盘
        payloads = [json_loads(bytes_) for bytes_ in store._blobs.values()]  # noqa: SLF001
        prompts = {p["request"]["prompt"] for p in payloads}
        assert prompts == {"a", "c"}


def json_loads(b: bytes) -> dict:
    import json

    return json.loads(b)
