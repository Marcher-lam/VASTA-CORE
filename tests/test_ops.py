"""Story 9.12：运维基线（FR-076，G5）。

告警规则（错误率/队列深/配额触顶）；备份恢复演练（事件流完整校验）；
事故关联 Run 与复盘归档。
"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer
from vasta_storage import SqliteStorage
from vastacore.ops.ops import (
    AlertRule,
    MetricsSnapshot,
    backup_snapshot,
    declare_incident,
    default_alert_rules,
    evaluate_alerts,
    incident_archive,
    recovery_drill,
    resolve_incident,
    restore_snapshot,
    verify_stream_integrity,
)


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


async def seed_runs(store, *run_ids: str) -> None:
    for run_id in run_ids:
        seq = EventSequencer(store, run_id)
        await seq.emit("run.created", {"budget": {}})
        await seq.emit("run.started", {})


class TestAlertRules:
    def test_defaults_cover_three_key_metrics(self) -> None:
        """AC：关键指标告警规则——错误率/队列深/配额触顶三基线。"""
        rules = default_alert_rules()
        assert {r.metric for r in rules} == {
            "error_rate", "queue_depth", "quota_throttled"}

    def test_threshold_breach_fires(self) -> None:
        snapshot = MetricsSnapshot(error_rate=0.10, queue_depth=0,
                                   quota_throttled=0)
        alerts = evaluate_alerts(snapshot)
        assert [a.name for a in alerts] == ["error_rate_high"]
        assert alerts[0].severity == "sev1"
        assert alerts[0].value == 0.10

    def test_at_threshold_not_firing(self) -> None:
        """恰好达标不告警（严格大于）。"""
        snapshot = MetricsSnapshot(error_rate=0.05)
        assert evaluate_alerts(snapshot) == []

    def test_all_three_fire(self) -> None:
        snapshot = MetricsSnapshot(error_rate=0.9, queue_depth=500,
                                   quota_throttled=99)
        alerts = evaluate_alerts(snapshot)
        assert len(alerts) == 3

    def test_unknown_metric_rejected(self) -> None:
        """规则引用快照未携带的指标 → 拒（fail-closed，不静默跳过）。"""
        rule = AlertRule(name="x", metric="ghost_metric", threshold=1)
        with pytest.raises(VastaError) as excinfo:
            evaluate_alerts(MetricsSnapshot(), [rule])
        assert excinfo.value.code == "ops.unknown_metric"

    def test_bad_severity_rejected(self) -> None:
        with pytest.raises(VastaError):
            AlertRule(name="x", metric="queue_depth", threshold=1,
                      severity="urgent")

    def test_extra_metrics_supported(self) -> None:
        rule = AlertRule(name="custom", metric="p99_latency_ms",
                         threshold=500, severity="sev3")
        alerts = evaluate_alerts(
            MetricsSnapshot(extra={"p99_latency_ms": 800}), [rule])
        assert len(alerts) == 1


class TestBackupRecovery:
    async def test_drill_passes_on_healthy_store(self, store,
                                                 tmp_path) -> None:
        """AC：备份+恢复演练——恢复后事件流完整校验通过。"""
        await seed_runs(store, "run-a", "run-b")
        report = await recovery_drill(store, tmp_path / "backup.db")
        assert report["passed"] is True
        integrity = report["integrity"]
        assert integrity["runs_checked"] == 2
        assert integrity["events_checked"] == 4
        assert integrity["seq_gaps"] == []
        assert integrity["parent_breaks"] == []

    async def test_integrity_detects_injected_gap(self, store) -> None:
        await seed_runs(store, "r")  # seq 0,1
        with store._lock, store._conn:  # noqa: SLF001——人为挖洞
            store._conn.execute(  # noqa: SLF001
                "DELETE FROM events WHERE run_id='r' AND seq=0")
        report = verify_stream_integrity(store)
        assert report.ok is False
        assert "r" in report.seq_gaps

    def test_backup_idempotent_overwrite(self, store, tmp_path) -> None:
        dest = tmp_path / "b.db"
        backup_snapshot(store, dest)
        backup_snapshot(store, dest)  # 覆盖旧备份不炸
        assert dest.exists()

    def test_restore_missing_backup_rejected(self, tmp_path) -> None:
        with pytest.raises(VastaError) as excinfo:
            restore_snapshot(tmp_path / "ghost.db", tmp_path / "target")
        assert excinfo.value.code == "ops.backup_missing"

    async def test_restored_store_readable(self, store, tmp_path) -> None:
        """恢复库可正常打开并读取事件（不只是文件拷贝）。"""
        await seed_runs(store, "run-x")
        backup = backup_snapshot(store, tmp_path / "b.db")
        target = restore_snapshot(backup, tmp_path / "restored")
        restored = SqliteStorage(target)
        try:
            events = list(restored.iter_run_events("run-x"))
            assert [e.type for e in events] == ["run.created", "run.started"]
        finally:
            restored.close()


class TestIncidents:
    async def test_declare_associates_runs_and_leaves_trace(
            self, store) -> None:
        """AC：事故可关联 Run 并留痕（incident.declared）。"""
        iid = await declare_incident(
            store, "队列堆积", related_runs=["run-1", "run-2"],
            severity="sev1")
        assert iid.startswith("inc-")
        events = [e for e in store.iter_run_events("incidents")
                  if e.type == "incident.declared"]
        assert events[-1].payload["related_runs"] == ["run-1", "run-2"]
        assert events[-1].payload["severity"] == "sev1"

    async def test_resolve_and_archive(self, store) -> None:
        """结案留痕 + 复盘归档聚合（声明↔结案配对）。"""
        iid = await declare_incident(store, "限流风暴",
                                     related_runs=["r1"])
        await resolve_incident(store, iid, resolution="扩容配额")
        archive = incident_archive(store)
        assert len(archive) == 1
        rec = archive[0]
        assert rec.resolved is True
        assert rec.resolution == "扩容配额"
        assert rec.related_runs == ["r1"]

    async def test_open_incident_in_archive_unresolved(self, store) -> None:
        await declare_incident(store, "未结", related_runs=["r"])
        rec = incident_archive(store)[0]
        assert rec.resolved is False and rec.resolution is None

    async def test_declare_requires_runs(self, store) -> None:
        with pytest.raises(VastaError) as excinfo:
            await declare_incident(store, "幽灵事故", related_runs=[])
        assert excinfo.value.code == "ops.incident_needs_runs"

    async def test_declare_bad_severity(self, store) -> None:
        with pytest.raises(VastaError):
            await declare_incident(store, "x", related_runs=["r"],
                                   severity="critical")

    async def test_resolve_unknown_rejected(self, store) -> None:
        with pytest.raises(VastaError) as excinfo:
            await resolve_incident(store, "inc-ghost", resolution="x")
        assert excinfo.value.code == "ops.incident_not_found"

    async def test_double_resolve_rejected(self, store) -> None:
        """复盘归档不可改写——重复结案拒。"""
        iid = await declare_incident(store, "x", related_runs=["r"])
        await resolve_incident(store, iid, resolution="first")
        with pytest.raises(VastaError) as excinfo:
            await resolve_incident(store, iid, resolution="second")
        assert excinfo.value.code == "ops.incident_already_resolved"
        assert incident_archive(store)[0].resolution == "first"
