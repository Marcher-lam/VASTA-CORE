"""Story 1.3：五类 Observation 采集与分类保证。"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action, Observation
from vasta_runtime.budget import Budget
from vasta_runtime.observation import ObservationCollector
from vasta_runtime.runner import RunConfig, RunEngine

from .fakes import FakeStorageAdapter

_FIVE = ("decision", "transition", "terminal", "reset", "external")


class TerminalEnv:
    """决策帧 → 动画过渡帧 → 终局帧 的序列环境（AC 场景）。"""

    protocol_version = "0.1.0"

    def __init__(self) -> None:
        self.steps = 0

    async def reset(self, seed: int | None = None) -> Observation:
        return Observation(kind="decision", available_actions=["go", "stop"])

    async def observe(self) -> Observation:
        return Observation(kind="decision", available_actions=["go", "stop"])

    async def execute(self, action: Action) -> list[Observation]:
        self.steps += 1
        if action.tool == "stop":
            return [
                Observation(kind="transition"),
                Observation(kind="terminal", detail={"episode": self.steps}),
            ]
        return [
            Observation(kind="transition"),
            Observation(kind="decision", available_actions=["go", "stop"]),
        ]

    async def status(self) -> object:
        class _S:
            running = True

        return _S()


async def make_engine(env=None) -> tuple[RunEngine, FakeStorageAdapter]:
    store = FakeStorageAdapter()
    engine = await RunEngine.create(
        env=env or TerminalEnv(),
        store=store,
        budget=Budget(),
        config=RunConfig(run_id="run-obs"),
    )
    return engine, store


def types_of(store: FakeStorageAdapter) -> list[str]:
    return [e.type for e in store.iter_run_events("run-obs")]


class TestFiveKindCollection:
    async def test_decision_transition_terminal_classified(self) -> None:
        engine, store = await make_engine()
        await engine.start()
        await engine.reset(seed=1)
        await engine.step(Action(tool="stop"))

        types = types_of(store)
        assert types == [
            "run.created",
            "run.started",
            "observation.reset",
            "observation.decision",
            "observation.transition",
            "observation.terminal",
        ]
        assert engine.collector.episode_ended is True

    async def test_all_five_kinds_covered_in_one_scenario(self) -> None:
        engine, store = await make_engine()
        await engine.start()
        await engine.reset(seed=1)          # reset + decision
        await engine.ingest_external({"source": "webhook", "change": "ui_theme"})
        await engine.step(Action(tool="go"))  # transition + decision
        await engine.step(Action(tool="stop"))  # transition + terminal

        types = types_of(store)
        for kind in _FIVE:
            assert f"observation.{kind}" in types, kind
        assert engine.collector.counts.keys() == set(_FIVE)

    async def test_payload_carries_actionable_flag(self) -> None:
        engine, store = await make_engine()
        await engine.start()
        await engine.reset(seed=1)
        await engine.step(Action(tool="stop"))

        obs_events = [
            e for e in store.iter_run_events("run-obs") if e.type.startswith("observation.")
        ]
        flags = {
            e.payload["kind"]: e.payload["actionable"]
            for e in obs_events
            if "kind" in e.payload
        }
        assert flags["decision"] is True
        assert flags["transition"] is False
        assert flags["terminal"] is False
        assert flags["reset"] is False


class TestTerminalGuard:
    async def test_cannot_act_after_terminal(self) -> None:
        engine, store = await make_engine()
        await engine.start()
        await engine.reset(seed=1)
        await engine.step(Action(tool="stop"))
        with pytest.raises(VastaError) as excinfo:
            await engine.step(Action(tool="go"))
        assert excinfo.value.code == "run.terminal"
        # 拒绝不产生新事件
        assert types_of(store)[-1] == "observation.terminal"

    async def test_reset_clears_terminal_and_restores_action(self) -> None:
        engine, store = await make_engine()
        await engine.start()
        await engine.reset(seed=1)
        await engine.step(Action(tool="stop"))
        assert engine.collector.episode_ended is True

        await engine.reset(seed=2)
        assert engine.collector.episode_ended is False
        observations = await engine.step(Action(tool="go"))
        assert [o.kind for o in observations] == ["transition", "decision"]
        assert types_of(store)[-4:] == [
            "observation.reset",
            "observation.decision",
            "observation.transition",
            "observation.decision",
        ]

    async def test_external_is_not_terminal(self) -> None:
        engine, store = await make_engine()
        await engine.start()
        await engine.ingest_external({"change": "external_system_update"})
        assert engine.collector.episode_ended is False
        assert types_of(store)[-1] == "observation.external"
        # 外部事件后仍可行动
        await engine.step(Action(tool="go"))


class TestActionableInvariant:
    async def test_last_actionable_only_from_decision_frames(self) -> None:
        engine, _ = await make_engine()
        await engine.start()
        await engine.reset(seed=1)
        assert engine.collector.last_actionable is not None
        assert engine.collector.last_actionable.kind == "decision"

        await engine.step(Action(tool="stop"))  # transition + terminal
        # 终局与过渡帧不覆盖可行动状态
        assert engine.collector.last_actionable.kind == "decision"

    @given(kind=st.sampled_from(["transition", "terminal", "reset", "external"]))
    def test_non_decision_never_actionable(self, kind: str) -> None:
        collector = ObservationCollector()
        collector.record(Observation(kind="decision", available_actions=["a"]))
        payload = collector.record(Observation(kind=kind))
        assert payload["actionable"] is False
        assert collector.last_actionable is not None
        assert collector.last_actionable.kind == "decision"
        if kind == "terminal":
            assert collector.episode_ended is True
        if kind == "reset":
            assert collector.episode_ended is False

    @given(kinds=st.lists(st.sampled_from(_FIVE), min_size=0, max_size=12))
    def test_actionable_follows_last_decision(self, kinds: list[str]) -> None:
        collector = ObservationCollector()
        expected: str | None = None
        for kind in kinds:
            collector.record(Observation(kind=kind))
            if kind == "decision":
                expected = "decision"
        actual = collector.last_actionable.kind if collector.last_actionable else None
        assert actual == expected
