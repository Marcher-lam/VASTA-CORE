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

    async def test_fast_mode_no_advance_on_write_failure(self) -> None:
        """评审缺口 G2 锚定：append 失败后 last_seq **不推进**——
        「成功才推进、失败不留洞、重试无洞」的完整链条
        （推进语义移回 append 前的突变体必须被本测试杀死）。"""

        class FailOnce(FakeStorageAdapter):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            async def append_event(self, envelope):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("disk full")
                return self.log.append(envelope)

        store = FailOnce()
        seq = EventSequencer(store, "run-f", resync_each_emit=False)
        with pytest.raises(RuntimeError):
            await seq.emit("run.created", {})
        assert seq.last_seq == -1  # 失败不推进（推进若在 append 前则 =0）
        e = await seq.emit("run.created", {})  # 重试用同一 seq——无洞
        assert e.seq == 0

    async def test_system_mode_uses_point_query_not_full_scan(self) -> None:
        """评审修复：系统流同步走 last_event_info 点查（O(1)——
        曾每次 emit 全量重扫 O(n²)）。"""

        class CountingStore(FakeStorageAdapter):
            def __init__(self) -> None:
                super().__init__()
                self.full_scans = 0
                self.point_queries = 0

            def last_event_info(self, run_id):
                self.point_queries += 1
                events = list(super().iter_run_events(run_id))
                if not events:
                    return None
                return (events[-1].seq, events[-1].event_id)

            def iter_run_events(self, run_id):
                self.full_scans += 1
                return super().iter_run_events(run_id)

        store = CountingStore()
        seq = EventSequencer(store, "sys")
        for _ in range(50):
            await seq.emit("memory.note", {})
        assert store.point_queries == 50  # 每次 emit 一次点查
        assert store.full_scans == 0  # 零全量重扫（曾 50 次递增扫描）

    async def test_concurrent_emit_serialized(self) -> None:
        """评审修复：同一 sequencer 并发 emit 不再必败一路
        （实例锁串行化——sync 与 append 之间的交错窗口关闭）。"""
        import asyncio

        store = FakeStorageAdapter()
        seq = EventSequencer(store, "conc")
        results = await asyncio.gather(
            seq.emit("run.created", {"n": 1}),
            seq.emit("run.created", {"n": 2}),
            seq.emit("run.created", {"n": 3}),
        )
        assert sorted(r.seq for r in results) == [0, 1, 2]  # 全部成功无撞

    async def test_fast_mode_conflict_self_heals_and_joins(self) -> None:
        """快道 resume 时点落后（他实例已推进）：撞唯一约束 → 同步尾部
        后续接重试（评审修复：不再永久卡死；事件接上存储尾部，
        无洞、父链完整——不静默丢）。"""
        store = FakeStorageAdapter()
        a = EventSequencer(store, "run-z", resync_each_emit=False)
        ea = await a.emit("run.created", {})
        # b 从 seq=0 resume（落后——a 已推进到 0）
        rebuilt_b = EventSequencer.resuming(store, "run-z", last_seq=0,
                                            last_event_id=ea.event_id)
        eb = await rebuilt_b.emit("run.started", {})  # seq=1 正常
        ea2 = await a.emit("run.paused", {})  # a 与 b 交错推进
        assert (eb.seq, ea2.seq) == (1, 2)
        # 落后撞号形态：c resume 在 seq=1，但流已被 a/b 推到 2
        c = EventSequencer.resuming(store, "run-z", last_seq=1,
                                    last_event_id=eb.event_id)
        ec = await c.emit("run.resumed", {})  # seq=2 撞 → 自愈接 seq=3
        assert ec.seq == 3
        assert len(list(store.iter_run_events("run-z"))) == 4  # 无覆盖无洞

    async def test_fast_mode_fresh_start_on_nonempty_stream_raises(
            self) -> None:
        """声称空流（last_seq=-1）对非空流从头写 = rerun 冲突——上抛
        不自愈（quickstart.rerun_conflict 检测依赖此路径）。"""
        store = FakeStorageAdapter()
        a = EventSequencer(store, "run-r", resync_each_emit=False)
        await a.emit("run.created", {})
        b = EventSequencer(store, "run-r", resync_each_emit=False)  # 从零
        with pytest.raises(DuplicateEventError):
            await b.emit("run.started", {})

    async def test_fast_mode_persistent_conflict_raises(self) -> None:
        """自愈重试一次后仍撞（存储尾部不前进的异常形态）→ 上抛。"""

        class AlwaysConflict(FakeStorageAdapter):
            def append_event(self, envelope):  # type: ignore[override]
                raise DuplicateEventError(envelope.run_id, envelope.seq)

        seq = EventSequencer(AlwaysConflict(), "run-w",
                             resync_each_emit=False)
        with pytest.raises(DuplicateEventError):
            await seq.emit("run.created", {})


class TestConstructionSitesConverged:
    def test_no_hand_rolled_envelope_construction_left(self) -> None:
        """AC：五站点 grep 零残留（生产写路径只剩 Sequencer 构造）。"""
        import re
        from pathlib import Path

        sites = [
            "packages/vasta-runtime/src/vasta_runtime/runner.py",
            "packages/vasta-cognition/src/vasta_cognition/cognition.py",
            "packages/vasta-model-lab/src/vasta_model_lab/_bookkeeping_stub.py",
            "packages/vastacore-sdk/src/vastacore/evidence/trajectory.py",
            "packages/vastacore-sdk/src/vastacore/governance/versioning.py",
        ]
        for site in sites:
            text = Path(site).read_text(encoding="utf-8")
            hits = re.findall(r"EventEnvelope\.model_validate", text)
            assert not hits, f"{site} 仍有 {len(hits)} 处手工构造"
