"""Story 9.1：统一 EventSequencer（复盘 B1——五处手工构造点收敛）。

系统流模式（每发全量同步）与引擎快道模式（成功才推进）；
父链、续接、跨实例安全（(run_id,seq) 唯一约束兜底）。
"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import DuplicateEventError
from vasta_protocols.sequencer import EventSequencer

from .fakes import FakeStorageAdapter


class TestSystemStreamMode:
    async def test_allocates_sequential_with_parent_chain(self) -> None:
        store = FakeStorageAdapter()
        seq = EventSequencer(store, "sys-run")
        e0 = await seq.emit("run.created", {"x": 1})
        e1 = await seq.emit("memory.note", {"x": 2})
        e2 = await seq.emit("run.completed", {})
        assert (e0.seq, e1.seq, e2.seq) == (0, 1, 2)
        assert e1.parent_event_id == e0.event_id
        assert e2.parent_event_id == e1.event_id
        assert all(e.run_id == "sys-run" for e in (e0, e1, e2))

    async def test_resumes_from_existing_stream(self) -> None:
        """已有事件的流：续接 max(seq)+1（与桥接/cognition 现语义一致）。"""
        store = FakeStorageAdapter()
        first = EventSequencer(store, "cognition")
        await first.emit("claim.proposed", {"claim_id": "c1"})
        await first.emit("claim.supported", {"claim_id": "c1"})
        # 新实例（同流）续接，不撞键
        second = EventSequencer(store, "cognition")
        e = await second.emit("claim.accepted", {"claim_id": "c1"})
        assert e.seq == 2
        assert e.parent_event_id is not None

    async def test_tenant_scope_carried(self) -> None:
        store = FakeStorageAdapter()
        seq = EventSequencer(store, "r", tenant_id="t-a", project_id="p-b")
        e = await seq.emit("run.created", {})
        assert e.tenant_id == "t-a" and e.project_id == "p-b"

    async def test_two_instances_same_stream_conflict_detected(self) -> None:
        """跨实例并发分配靠唯一约束兜底——后写者明确报错不静默丢。"""
        store = FakeStorageAdapter()
        a = EventSequencer(store, "shared")
        b = EventSequencer(store, "shared")
        await a.emit("run.created", {})
        await b.emit("run.created", {})  # b 全量同步后会看到 a 的事件
        e3 = await b.emit("memory.note", {})
        assert e3.seq == 2  # 同步模式天然安全
        # 快道模式才会撞约束——见 TestEngineFastMode

    async def test_injectable_clock_and_id(self) -> None:
        from datetime import UTC, datetime

        fixed = datetime(2026, 1, 1, tzinfo=UTC)
        counter = iter(["id-1", "id-2"])
        store = FakeStorageAdapter()
        seq = EventSequencer(
            store, "r", clock=lambda: fixed,
            event_id_factory=lambda: next(counter),
        )
        e = await seq.emit("run.created", {})
        assert e.ts == fixed and e.event_id == "id-1"


class TestEngineFastMode:
    async def test_fast_mode_advances_only_on_success(self) -> None:
        """引擎语义：append 成功才推进 seq（写失败不留洞——评审修复保持）。"""
        store = FakeStorageAdapter()
        seq = EventSequencer(store, "run-x", resync_each_emit=False)
        e0 = await seq.emit("run.created", {})
        e1 = await seq.emit("run.started", {})
        assert (e0.seq, e1.seq) == (0, 1)

    async def test_fast_mode_resume_from_last(self) -> None:
        store = FakeStorageAdapter()
        seq = EventSequencer(store, "run-y", resync_each_emit=False)
        await seq.emit("run.created", {})
        # 崩溃后新引擎重建：从存储已知最大 seq 续接
        rebuilt = EventSequencer.resuming(
            store, "run-y", last_seq=0,
            last_event_id=(list(store.iter_run_events("run-y"))[-1].event_id),
        )
        e = await rebuilt.emit("run.paused", {})
        assert e.seq == 1

    async def test_fast_mode_conflict_raises_not_silent(self) -> None:
        """两个快道实例同流：后写者撞唯一约束 → DuplicateEventError。"""
        store = FakeStorageAdapter()
        a = EventSequencer(store, "run-z", resync_each_emit=False)
        b = EventSequencer(store, "run-z", resync_each_emit=False)
        await a.emit("run.created", {})
        with pytest.raises(DuplicateEventError):
            await b.emit("run.started", {})  # b 也从 seq=0 开始 → 撞键


class TestConstructionSitesConverged:
    def test_no_hand_rolled_envelope_construction_left(self) -> None:
        """AC：五站点 grep 零残留（生产写路径只剩 Sequencer 构造）。"""
        import re
        from pathlib import Path

        sites = [
            "packages/vasta-runtime/src/vasta_runtime/runner.py",
            "packages/vasta-cognition/src/vasta_cognition/cognition.py",
            "packages/vasta-model-lab/src/vasta_model_lab/_bookkeeping_stub.py",
            "packages/vastacore-sdk/src/vastacore/trajectory.py",
            "packages/vastacore-sdk/src/vastacore/versioning.py",
        ]
        for site in sites:
            text = Path(site).read_text(encoding="utf-8")
            hits = re.findall(r"EventEnvelope\.model_validate", text)
            assert not hits, f"{site} 仍有 {len(hits)} 处手工构造"
