"""Story 4.1/4.2：时间线投影与首偏差定位。"""

from __future__ import annotations

import pytest

from vasta_protocols.protocols import Action, Observation

from .fakes import FakeStorageAdapter

from vasta_storage import SqliteStorage
from vasta_storage.replay import render_text, timeline

from vasta_runtime import RunEngine, RunContext
from tests.test_deviation_recovery import DeviationVerifier
from vasta_contracts import make_complete_contract


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


async def seeded_run(store, *, with_deviation=False):
    engine = await RunEngine.create(
        env=Env(), store=store,
        run_context=RunContext.create(run_id="run-tl", seed=1),
    )
    await engine.start()
    await engine.reset(seed=1)
    await engine.step(Action(tool="go"))
    verifiers = {"read_back": DeviationVerifier()} if with_deviation else None
    await engine.execute_contracted(
        make_complete_contract(), verifiers=verifiers
    )
    await engine.ingest_external({"source": "webhook", "change": "ui"})
    await engine.complete()
    return engine


class TestTimelineProjection:
    async def test_full_coverage_and_causal_trace(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        await seeded_run(store)
        events = list(store.iter_run_events("run-tl"))

        tl = timeline(events)
        assert tl.total_events == len(events)
        assert tl.covers_all_events  # AC-01：全覆盖
        assert "action" in tl.families_present
        assert "verification" in tl.families_present
        # 因果父链逐条可溯
        id_to_seq = {e.event_id: e.seq for e in events}
        for entry in tl.entries:
            if entry.parent_seq is not None:
                assert entry.depth >= 1
                # 父项存在且深度恰为 depth-1
                parent = next(e for e in tl.entries if e.seq == entry.parent_seq)
                assert parent.depth == entry.depth - 1
        # 根事件 depth=0 存在
        assert any(e.depth == 0 for e in tl.entries)

    async def test_projection_pure_and_rebuildable(self, tmp_path) -> None:
        """AD-11：纯函数，同输入同输出，可删除重建。"""
        store = SqliteStorage(tmp_path / "s")
        await seeded_run(store)
        events = list(store.iter_run_events("run-tl"))
        tl1 = timeline(events)
        tl2 = timeline(list(store.iter_run_events("run-tl")))  # 重建
        assert tl1.model_dump() == tl2.model_dump()

    async def test_external_change_flag(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        await seeded_run(store)
        events = list(store.iter_run_events("run-tl"))
        tl = timeline(events)
        flagged = [e for e in tl.entries if e.external_change]
        assert len(flagged) == 1  # webhook 注入的外部变化
        assert flagged[0].type == "observation.external"

    async def test_render_text(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        await seeded_run(store)
        events = list(store.iter_run_events("run-tl"))
        text = render_text(timeline(events))
        assert "timeline run=run-tl" in text
        assert "run.created" in text
        assert "[外部变化]" in text
