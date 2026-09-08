"""Story 4.1/4.2：时间线投影与首偏差定位。"""

from __future__ import annotations

import pytest

from tests.test_deviation_recovery import DeviationVerifier
from vasta_contracts import make_complete_contract
from vasta_protocols.protocols import Action, Observation
from vasta_runtime import RunContext, RunEngine
from vasta_storage import SqliteStorage
from vasta_storage.replay import render_text, timeline


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
    from vasta_protocols.protocols import Verification, VerifierManifest

    class AlwaysPass:
        protocol_version = "0.1.0"
        manifest = VerifierManifest(name="read_back", version="1", kind="read_back")

        async def verify(self, ref, ev):
            return Verification(outcome="pass")

    engine = await RunEngine.create(
        env=Env(), store=store,
        run_context=RunContext.create(run_id="run-tl", seed=1),
    )
    await engine.start()
    await engine.reset(seed=1)
    await engine.step(Action(tool="go"))
    verifiers = (
        {"read_back": DeviationVerifier()} if with_deviation
        else {"read_back": AlwaysPass()}
    )
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


class TestFirstDeviation:
    async def test_deviation_run_locates_first(self, tmp_path) -> None:
        from vasta_storage import first_deviation

        store = SqliteStorage(tmp_path / "s")
        await seeded_run(store, with_deviation=True)
        events = list(store.iter_run_events("run-tl"))
        hit = first_deviation(events)
        assert hit is not None
        assert hit.type == "verification.deviated"
        assert hit.category == "verification"
        assert hit.contract_ref is not None  # 契约可跳转
        assert hit.before_seq is not None  # 前置观察
        assert hit.context_seqs  # 上下文窗口

    async def test_clean_run_no_deviation(self, tmp_path) -> None:
        from vasta_storage import first_deviation

        store = SqliteStorage(tmp_path / "s")
        await seeded_run(store)
        events = list(store.iter_run_events("run-tl"))
        # 无偏差注入但 ingest_external 是外部变化——也算首偏差信号（环境变了）
        hit = first_deviation(events)
        assert hit is not None
        assert hit.category == "external_change"
        assert hit.type == "observation.external"

    async def test_external_change_distinguished(self, tmp_path) -> None:
        """外部变化 vs 核验偏差——分类不同（排障路径分叉）。"""
        from vasta_storage import first_deviation

        store = SqliteStorage(tmp_path / "s")
        await seeded_run(store, with_deviation=True)
        # 注入顺序：contract(deviation) 在 ingest_external 之前 → 首个是核验
        events = list(store.iter_run_events("run-tl"))
        hit = first_deviation(events)
        assert hit.category == "verification"
        # 反转：无 deviation → external
        store2 = SqliteStorage(tmp_path / "s2")
        await seeded_run(store2)
        hit2 = first_deviation(list(store2.iter_run_events("run-tl")))
        assert hit2.category == "external_change"
        store2.close()


class TestHtmlReplay:
    async def test_self_contained_html(self, tmp_path) -> None:
        from vasta_storage import first_deviation, render_html, timeline

        store = SqliteStorage(tmp_path / "s")
        await seeded_run(store, with_deviation=True)
        events = list(store.iter_run_events("run-tl"))
        html = render_html(timeline(events), first_deviation(events))
        text = html.decode("utf-8")
        assert text.startswith("<!DOCTYPE html>")
        assert "run-tl" in text
        assert "verification.deviated" in text  # 偏差行在表内
        assert "首个偏差" in text  # 高亮块
        # 自包含：无外部资源引用（无 http:// 无 <script src）
        assert "<script src" not in text
        assert "http://" not in text and "https://" not in text
        assert "外部变化" in text  # webhook 注入提示
        store.close()

    async def test_clean_run_html_no_deviation_block(self, tmp_path) -> None:
        from vasta_storage import first_deviation, render_html, timeline

        store = SqliteStorage(tmp_path / "s")
        await seeded_run(store)
        events = list(store.iter_run_events("run-tl"))
        html = render_html(timeline(events), first_deviation(events))
        text = html.decode("utf-8")
        assert "外部变化" in text  # external 块仍在（即使无核验偏差）
        store.close()


class TestReproBundle:
    async def test_export_and_offline_replay(self, tmp_path) -> None:
        from vasta_storage import (
            build_regression_task,
            export_repro_bundle,
            replay_non_model_events,
        )

        store = SqliteStorage(tmp_path / "s")
        await seeded_run(store, with_deviation=True)
        bundle, event_bytes = await export_repro_bundle(
            store, "run-tl", tenant_id="t-default", project_id="p-default"
        )
        assert bundle.event_count >= 15
        assert bundle.artifact_refs  # 契约与观察证据引用在清单
        assert "budget" in bundle.config_snapshot  # 配置快照可还原
        # 干净环境离线重放（AC-08）：逐条 schema 校验通过
        replayed = replay_non_model_events(event_bytes)
        assert len(replayed) == bundle.event_count
        # 回归任务契约格式
        task = build_regression_task(bundle, event_bytes)
        assert task.source_run_id == "run-tl"
        assert len(task.event_data) == bundle.event_count
        store.close()

    async def test_unknown_run_rejected(self, tmp_path) -> None:
        from vasta_protocols.errors import VastaError
        from vasta_storage import export_repro_bundle

        store = SqliteStorage(tmp_path / "s")
        with pytest.raises(VastaError):
            await export_repro_bundle(store, "run-none")
        store.close()
