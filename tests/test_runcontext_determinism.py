"""Story 1.5：RunContext 确定性注入与重放守卫。"""

from __future__ import annotations

import json

import pytest

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action, Observation
from vasta_runtime.budget import Budget
from vasta_runtime.runcontext import RunContext
from vasta_runtime.runner import RunEngine

from .fakes import FakeStorageAdapter


class ScriptedEnv:
    """确定性脚本环境（重放替身）：deterministic = True（AD-5 标记）。"""

    protocol_version = "0.1.0"
    deterministic = True

    async def reset(self, seed: int | None = None) -> Observation:
        return Observation(kind="decision", available_actions=["go", "stop"])

    async def observe(self) -> Observation:
        return Observation(kind="decision", available_actions=["go", "stop"])

    async def execute(self, action: Action) -> list[Observation]:
        if action.tool == "stop":
            return [Observation(kind="transition"), Observation(kind="terminal")]
        return [Observation(kind="transition"), Observation(kind="decision")]

    async def status(self) -> object:
        class _S:
            running = True

        return _S()


class RealishEnv(ScriptedEnv):
    """未标记确定性的"真实"环境。"""

    deterministic = False


async def run_scenario(store, *, seed: int, env=None) -> list[str]:
    """同一段脚本两次执行，返回事件 JSON 列表（逐字节比对用）。"""
    ctx = RunContext.create(run_id="run-replay", seed=seed, replay_mode=True)
    engine = await RunEngine.create(
        env=env or ScriptedEnv(), store=store, budget=Budget(), run_context=ctx
    )
    await engine.start()
    await engine.reset(seed=seed)
    await engine.step(Action(tool="go"))
    await engine.step(Action(tool="stop"))
    return [e.model_dump_json() for e in store.iter_run_events("run-replay")]


class TestDeterministicReplay:
    async def test_same_seed_byte_identical_event_stream(self) -> None:
        """NFR-002 核心：同种子两次完整 Run，事件流逐字节一致。"""
        first = await run_scenario(FakeStorageAdapter(), seed=42)
        second = await run_scenario(FakeStorageAdapter(), seed=42)
        assert first == second
        assert len(first) >= 6

    async def test_different_seed_different_ids(self) -> None:
        first = await run_scenario(FakeStorageAdapter(), seed=1)
        second = await run_scenario(FakeStorageAdapter(), seed=2)
        ids_a = [json.loads(e)["event_id"] for e in first]
        ids_b = [json.loads(e)["event_id"] for e in second]
        assert ids_a != ids_b

    async def test_seeded_clock_is_deterministic_and_monotonic(self) -> None:
        ctx_a = RunContext.create(run_id="r", seed=7)
        ctx_b = RunContext.create(run_id="r", seed=7)
        stamps_a = [ctx_a.clock() for _ in range(5)]
        stamps_b = [ctx_b.clock() for _ in range(5)]
        assert stamps_a == stamps_b
        assert stamps_a == sorted(stamps_a)

    async def test_seeded_rng_reproducible(self) -> None:
        a = RunContext.create(run_id="r", seed=9).rng
        b = RunContext.create(run_id="r", seed=9).rng
        assert [a.random() for _ in range(8)] == [b.random() for _ in range(8)]


class TestReplayGuard:
    async def test_replay_mode_rejects_real_env(self) -> None:
        ctx = RunContext.create(run_id="r", seed=1, replay_mode=True)
        engine = await RunEngine.create(
            env=RealishEnv(), store=FakeStorageAdapter(), run_context=ctx
        )
        await engine.start()
        with pytest.raises(VastaError) as excinfo:
            await engine.step(Action(tool="go"))
        assert excinfo.value.code == "replay.real_env_unauthorized"

    async def test_replay_mode_allows_deterministic_stand_in(self) -> None:
        ctx = RunContext.create(run_id="r", seed=1, replay_mode=True)
        engine = await RunEngine.create(
            env=ScriptedEnv(), store=FakeStorageAdapter(), run_context=ctx
        )
        await engine.start()
        observations = await engine.step(Action(tool="go"))
        assert len(observations) == 2

    async def test_authorized_real_env_in_replay(self) -> None:
        ctx = RunContext.create(
            run_id="r", seed=1, replay_mode=True, real_tools_authorized=True
        )
        engine = await RunEngine.create(
            env=RealishEnv(), store=FakeStorageAdapter(), run_context=ctx
        )
        await engine.start()
        assert len(await engine.step(Action(tool="go"))) == 2

    async def test_record_mode_no_guard(self) -> None:
        ctx = RunContext.create(run_id="r")  # 非 replay
        engine = await RunEngine.create(
            env=RealishEnv(), store=FakeStorageAdapter(), run_context=ctx
        )
        await engine.start()
        assert len(await engine.step(Action(tool="go"))) == 2


class TestModelExchangeArtifact:
    async def test_exchange_saved_as_artifact_and_budgeted(self) -> None:
        from vasta_protocols.protocols import ModelRequest, ModelResponse

        store = FakeStorageAdapter()
        ctx = RunContext.create(run_id="r", seed=3)
        engine = await RunEngine.create(
            env=ScriptedEnv(), store=store, budget=Budget(max_model_calls=2),
            run_context=ctx,
        )
        await engine.start()
        sha = await engine.record_model_exchange(
            ModelRequest(prompt="ping"), ModelResponse(content="pong")
        )
        assert sha in store._blobs  # noqa: SLF001（测试直接检视假存储）
        payload = json.loads(await store.get_artifact(sha))
        assert payload["request"]["prompt"] == "ping"
        assert payload["response"]["content"] == "pong"
        assert engine.tracker.snapshot().model_calls_used == 1

    async def test_exchange_over_budget_safe_stops(self) -> None:
        from vasta_protocols.protocols import ModelRequest, ModelResponse

        ctx = RunContext.create(run_id="r", seed=3)
        engine = await RunEngine.create(
            env=ScriptedEnv(), store=FakeStorageAdapter(),
            budget=Budget(max_model_calls=1), run_context=ctx,
        )
        await engine.start()
        await engine.record_model_exchange(
            ModelRequest(prompt="a"), ModelResponse(content="b")
        )
        from vasta_runtime.budget import BudgetExceededError

        with pytest.raises(BudgetExceededError):
            await engine.record_model_exchange(
                ModelRequest(prompt="c"), ModelResponse(content="d")
            )
