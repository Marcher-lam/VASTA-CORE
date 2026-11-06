"""Story 9.15：运营达标工程面（NFR-004/006/014 收口——工程可验部分）。

SLO 达成度测量（错误预算）+ 计时恢复演练（RTO/RPO 实测与达标判定）
+ cron 定期演练接线（drill_executor × 9.9 Scheduler）。
多进程共享单库形态见 tests/test_multiprocess_store.py。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from vasta_eval import VastaLabTask
from vasta_protocols.sequencer import EventSequencer
from vasta_storage import SqliteStorage
from vastacore.ops.slo import (
    SloSpec,
    drill_due,
    drill_executor,
    record_slo_report,
    slo_report,
    timed_recovery_drill,
)


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


async def _seed_run(store, run_id: str, *, fail: bool = False,
                    ts_offset_s: float = 0.0) -> None:
    seq = EventSequencer(
        store, run_id, tenant_id="t-default", project_id="p-default",
        clock=lambda: datetime.now(UTC) - timedelta(seconds=ts_offset_s))
    await seq.emit("run.started", {"goal": "demo"})
    await seq.emit("run.failed" if fail else "run.completed", {})


class TestSloReport:
    async def test_attainment_and_error_budget(self, store) -> None:
        """数据驱动：可用率、错误预算、达标判定。"""
        await _seed_run(store, "r1")                    # 完成
        await _seed_run(store, "r2")                    # 完成
        await _seed_run(store, "r3", fail=True)         # 失败
        spec = SloSpec(name="monthly", target_pct=99.0, window_days=30)
        report = slo_report(store, spec)
        assert report.total_runs == 3
        assert report.completed == 2 and report.failed == 1
        assert report.availability_pct == pytest.approx(66.6667, abs=1e-3)
        assert report.attained is False  # 66.67% < 99%
        # 错误预算：3 × 1% = 0.03 允许，实际失败 1 → 超耗
        assert report.error_budget_allowed == pytest.approx(0.03)
        assert report.error_budget_remaining == pytest.approx(0.03 - 1)

    async def test_no_data_is_not_fake_100(self, store) -> None:
        """无数据 ≠ 100% 可用（availability/attained 均为 None）。"""
        spec = SloSpec(name="monthly", target_pct=99.5, window_days=30)
        report = slo_report(store, spec)
        assert report.total_runs == 0
        assert report.availability_pct is None
        assert report.attained is None
        assert not report.sufficient_data

    async def test_window_filters_old_events(self, store) -> None:
        """窗口外事件不计（30 天窗 vs 40 天前的旧 run）。"""
        await _seed_run(store, "old", ts_offset_s=40 * 86400)
        await _seed_run(store, "new")
        spec = SloSpec(name="monthly", target_pct=50.0, window_days=30)
        report = slo_report(store, spec)
        assert report.total_runs == 1
        assert report.availability_pct == 100.0
        assert report.attained is True

    async def test_report_recorded_to_ops_stream(self, store) -> None:
        await _seed_run(store, "r1")
        report = slo_report(store, SloSpec(name="m", target_pct=99,
                                           window_days=30))
        await record_slo_report(store, report)
        events = [e for e in store.iter_run_events("ops")
                  if e.type == "evaluation.slo_reported"]
        assert len(events) == 1
        assert events[0].payload["spec"]["name"] == "m"
        assert events[0].payload["availability_pct"] == 100.0


class TestTimedDrill:
    async def test_rto_rpo_measured_and_gated(self, store, tmp_path) -> None:
        """RTO（墙钟）与 RPO（备份滞后期）实测 + SLO 门判定。"""
        await _seed_run(store, "r1", ts_offset_s=120)  # 备份内最新事件 2 分钟前
        report = await timed_recovery_drill(
            store, tmp_path / "backup",
            rto_slo_s=30.0, rpo_slo_s=3600.0)
        assert report["passed"] is True
        assert 0 < report["rto_s"] < 30.0
        assert 100 <= report["rpo_s"] < 3600  # ≈120s 滞后（含容差）
        assert report["rto_ok"] is True and report["rpo_ok"] is True
        # 留痕：ops 流
        events = [e for e in store.iter_run_events("ops")
                  if e.type == "evaluation.drill_completed"]
        assert len(events) == 1 and events[0].payload["passed"] is True

    async def test_slo_violation_fails_drill(self, store, tmp_path) -> None:
        """RPO 超 SLO → passed=False（达标测量有牙齿）。"""
        await _seed_run(store, "r1", ts_offset_s=7200)  # 2 小时前
        report = await timed_recovery_drill(
            store, tmp_path / "backup", rpo_slo_s=3600.0, record=False)
        assert report["rpo_ok"] is False
        assert report["passed"] is False

    async def test_empty_store_drill(self, store, tmp_path) -> None:
        """空库演练：RPO=0（无数据无损失）、完整性绿。"""
        report = await timed_recovery_drill(store, tmp_path / "b", record=False)
        assert report["rpo_s"] == 0.0
        assert report["integrity"]["ok"] is True


class TestDrillOrchestration:
    def test_drill_due_cron(self) -> None:
        last = datetime(2026, 11, 6, 10, 0)
        assert drill_due("0 3 * * *", last_drill=last,
                         now=datetime(2026, 11, 7, 4, 0))  # 次日 03:00 已过
        assert not drill_due("0 3 * * *", last_drill=last,
                             now=datetime(2026, 11, 6, 12, 0))  # 未到点

    async def test_scheduler_drives_drills_via_executor(
            self, store, tmp_path) -> None:
        """cron 定期演练接线：Scheduler 触发 → drill_executor 执行。"""
        from vastacore.ops.scheduling import Scheduler, ScheduleSpec

        await _seed_run(store, "r1")

        class FakeClock:
            def __init__(self) -> None:
                self.now = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)

            def __call__(self) -> datetime:
                return self.now

            def advance_to_next_day(self) -> None:
                self.now += timedelta(days=1)

        clock = FakeClock()
        store_path = tmp_path / "s"  # 演练自开自关句柄（生产语义）
        scheduler = Scheduler(
            store, executor=drill_executor(
                lambda: SqliteStorage(store_path), tmp_path / "drills"),
            clock=clock)
        await scheduler.add(ScheduleSpec(
            schedule_id="daily-drill", cron="0 3 * * *",
            tasks=[VastaLabTask(task_id="drill-anchor")]))
        assert await scheduler.tick() == []  # 未到点不触发
        clock.advance_to_next_day()
        fired = await scheduler.tick()
        assert len(fired) == 1 and fired[0].success
        # 演练真实跑过：ops 流有 drill_completed
        assert any(e.type == "evaluation.drill_completed"
                   for e in store.iter_run_events("ops"))
