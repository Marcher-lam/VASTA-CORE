"""Story 4.1/4.2：时间线投影与首偏差定位。"""

from __future__ import annotations

import pytest

from tests.test_deviation_recovery import DeviationVerifier
from vasta_contracts import make_complete_contract
from vasta_protocols.envelope import EventEnvelope
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


class TestReviewGuards:
    """Epic 4-7 code-review 修复的守卫（转义/环护/过滤/信号覆盖/快照）。"""

    async def test_html_escapes_hostile_payload(self, tmp_path) -> None:
        """评审实锤：payload 摘要原样注入 HTML 可执行脚本。"""
        from vasta_storage import first_deviation, render_html, timeline

        store = SqliteStorage(tmp_path / "s")
        engine = await RunEngine.create(
            env=Env(), store=store,
            run_context=RunContext.create(run_id="run-xss", seed=1),
        )
        await engine.start()
        await engine.ingest_external(
            {"source": "<script>alert(1)</script>", "change": "ui"}
        )
        events = list(store.iter_run_events("run-xss"))
        html_text = render_html(timeline(events), first_deviation(events)).decode("utf-8")
        assert "<script>alert(1)</script>" not in html_text
        assert "&lt;script&gt;" in html_text  # 已转义仍可读
        await engine.complete()
        store.close()

    async def test_depth_computation_survives_parent_cycle(self) -> None:
        """评审实锤：parent 环导致原递归死循环；迭代版须终止且深度有限。"""
        from vasta_protocols.ids import new_event_id, now_utc
        from vasta_storage import timeline
        from vasta_storage.replay import _compute_depths

        def env(seq: int, parent: str | None) -> EventEnvelope:
            return EventEnvelope.model_validate({
                "run_id": "run-cyc", "seq": seq, "type": "observation.decision",
                "parent_event_id": parent, "ts": now_utc(),
                "tenant_id": "t", "project_id": "p", "event_id": new_event_id(),
                "payload": {},
            })

        a = env(0, None)
        b = env(1, a.event_id)
        # 构造环：a 的 parent 指向 b（信封不可变 → 用同 id 重建）
        a_cyclic = EventEnvelope.model_validate({
            **a.model_dump(), "parent_event_id": b.event_id,
        })
        c = env(4, b.event_id)
        depths = _compute_depths([a_cyclic, b, c])
        assert all(d >= 0 for d in depths)  # 有界
        tl = timeline([a_cyclic, b, c])
        assert tl.total_events == 3

    async def test_replay_skips_model_exchange_refs(self, tmp_path) -> None:
        """评审实锤：docstring 承诺跳过模型交换事件，原实现全量重放。"""
        from vasta_storage import export_repro_bundle, replay_non_model_events

        store = SqliteStorage(tmp_path / "s")
        await seeded_run(store)
        engine_events = list(store.iter_run_events("run-tl"))
        # 人为追加一条引用 model.exchange 的事件
        from vasta_protocols.ids import new_event_id, now_utc

        model_event = EventEnvelope.model_validate({
            "run_id": "run-tl",
            "seq": engine_events[-1].seq + 1,
            "type": "observation.external",
            "parent_event_id": engine_events[-1].event_id,
            "ts": now_utc(), "tenant_id": "t-default", "project_id": "p-default",
            "event_id": new_event_id(),
            "payload": {"kind": "model.exchange", "result_ref": "sha256:model.exchange@1"},
        })
        await store.append_event(model_event)
        bundle, event_bytes = await export_repro_bundle(store, "run-tl")
        replayed = replay_non_model_events(event_bytes)
        assert len(replayed) == bundle.event_count - 1  # 模型事件被跳过
        assert not any("model" in r for r in replayed)
        store.close()

    async def test_first_deviation_covers_all_signals(self, tmp_path) -> None:
        """评审修复：8 类偏差信号逐一验证可定位（原只测 2 类）。"""
        from vasta_protocols.ids import new_event_id, now_utc
        from vasta_storage import first_deviation

        def make(seq: int, type_: str, payload: dict | None = None) -> EventEnvelope:
            return EventEnvelope.model_validate({
                "run_id": "run-sig", "seq": seq, "type": type_,
                "parent_event_id": None, "ts": now_utc(),
                "tenant_id": "t", "project_id": "p", "event_id": new_event_id(),
                "payload": payload or {},
            })

        signals = [
            ("verification.deviated", {}),
            ("verification.errored", {}),
            ("action.policy_denied", {}),
            ("action.failed", {}),
            ("action.approval_requested", {}),
            ("incident.opened", {}),
            ("run.failed", {}),
            ("observation.external", {"external_source": "cron"}),
        ]
        for type_, payload in signals:
            hit = first_deviation([make(0, type_, payload)])
            assert hit is not None and hit.type == type_, type_
            expected_cat = (
                "external_change" if type_ == "observation.external"
                else "verification" if type_.startswith("verification.")
                else "policy" if type_ == "action.policy_denied"
                else "execution" if type_ in ("action.failed", "run.failed")
                else "supervisor"
            )
            assert hit.category == expected_cat, (type_, hit.category)

    async def test_tool_sourced_external_not_flagged(self, tmp_path) -> None:
        """发射侧语义守卫：source=tool 的 external 观察不算外部变化。"""
        store = SqliteStorage(tmp_path / "s")
        engine = await RunEngine.create(
            env=Env(), store=store,
            run_context=RunContext.create(run_id="run-tool", seed=1),
        )
        await engine.start()
        await engine.ingest_external({"source": "tool", "detail": "self-echo"})
        events = list(store.iter_run_events("run-tool"))
        # 发射侧只在 source≠tool 时打 external_source 键（runner._record_observation）
        ext_events = [
            e for e in events
            if e.type == "observation.external" and "external_source" in e.payload
        ]
        assert ext_events == []
        tl = timeline(events)
        assert not any(e.external_change for e in tl.entries)
        from vasta_storage import first_deviation

        assert first_deviation(events) is None
        await engine.complete()
        store.close()

    async def test_deviation_hit_carries_plan_ref(self, tmp_path) -> None:
        """评审修复：DeviationHit 补 plan_ref 维度。"""
        from vasta_protocols.ids import new_event_id, now_utc
        from vasta_storage import first_deviation

        def make(seq: int, type_: str, payload: dict | None = None) -> EventEnvelope:
            return EventEnvelope.model_validate({
                "run_id": "run-plan", "seq": seq, "type": type_,
                "parent_event_id": None, "ts": now_utc(),
                "tenant_id": "t", "project_id": "p", "event_id": new_event_id(),
                "payload": payload or {},
            })

        events = [
            make(0, "plan.created", {"plan_id": "p-9", "step_id": "s-1"}),
            make(1, "plan.invalidated", {"plan_id": "p-9", "step_id": "s-2"}),
            make(2, "action.failed", {"tool": "click"}),
        ]
        hit = first_deviation(events)
        assert hit is not None
        assert hit.plan_ref is not None and "p-9" in hit.plan_ref

    async def test_regression_task_contract_in_protocols(self) -> None:
        """评审修复：回归任务契约上移 vasta-protocols（AD-1）。"""
        import vasta_protocols
        from vasta_protocols.regression import REGRESSION_FORMAT_VERSION, RegressionTask
        from vasta_storage.replay import RegressionTask as Reexported

        assert Reexported is RegressionTask  # storage 侧为兼容再导出
        task = RegressionTask(task_id="r", source_run_id="run-1")
        assert task.format_version == REGRESSION_FORMAT_VERSION
        assert vasta_protocols.RegressionTask is RegressionTask
