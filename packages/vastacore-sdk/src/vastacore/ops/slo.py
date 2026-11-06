"""运营达标工程面（Story 9.15，NFR-004/006/014 收口）。

终检三处「属地运营」缺口的**工程可验部分**：

- **NFR-004 SLO 达成度测量**：``slo_report`` 从事件流按窗口统计
  run 完成/失败 → 可用率、错误预算（允许额度/剩余/超耗）、达标判定；
  ``record_slo_report`` 留痕（evaluation.slo_reported）——「达成度
  测量」从纸面 SLO 表变为数据驱动的周期报告；
- **NFR-014 RPO/RTO 达标测量与定期编排**：``timed_recovery_drill``
  在既有恢复演练（9.12）外套实测——RTO=演练墙钟（备份+恢复+校验），
  RPO=备份内最新事件距演练开始的滞后期（灾难在演练开始瞬间命中时的
  数据损失上界）；``drill_due``/``drill_executor`` 与 9.9 Scheduler
  组合实现 cron 定期演练；
- **NFR-006 分布式形态（工程面）**：多进程共享单库的部署形态由
  ``tests/test_multiprocess_store.py`` 锚定（每流单写者的分区契约）。

诚实边界：生产多区域演练、月度可用性统计的**运营执行**仍属地化——
本模块交付的是可复跑的测量与编排机制（数字由真实运营数据产生）。
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.sequencer import EventSequencer

from .ops import _distinct_runs
from .scheduling import CronSpec

#: 运营测量系统流（SLO 报告与演练留痕）。
_OPS_RUN = "ops"


class SloSpec(BaseModel):
    """SLO 定义（月可用性口径——PRD §11）。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    target_pct: float = Field(gt=0, le=100)
    window_days: int = Field(ge=1)


class SloReport(BaseModel):
    """SLO 达成度报告（数据驱动——由事件流统计产生）。"""

    model_config = ConfigDict(extra="forbid")

    spec: SloSpec
    window_from: str
    total_runs: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    availability_pct: float | None = None  # 无数据=不可判（不伪造 100%）
    error_budget_allowed: float = Field(ge=0)
    error_budget_remaining: float = 0.0
    attained: bool | None = None

    @property
    def sufficient_data(self) -> bool:
        return self.total_runs > 0


def _run_outcomes(
    store: Any, *, window_from: datetime,
    tenant_id: str, project_id: str,
) -> dict[str, str]:
    """窗口内各 run 的终局（completed/failed；失败优先——保守口径）。"""
    outcomes: dict[str, str] = {}
    for run_id in _distinct_runs(store):
        for event in store.iter_run_events(
                run_id, tenant_id=tenant_id, project_id=project_id):
            try:
                ts = datetime.fromisoformat(str(event.ts))
            except ValueError:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts < window_from:  # 双方均 aware UTC
                continue
            if event.type == "run.completed":
                outcomes[run_id] = "completed"
            elif event.type == "run.failed":
                outcomes[run_id] = "failed"  # 失败优先（保守）
    return outcomes


def slo_report(
    store: Any, spec: SloSpec, *,
    now: datetime | None = None,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> SloReport:
    """窗口内 SLO 达成度（无数据 → availability/attained 均为 None）。"""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    window_from = now - timedelta(days=spec.window_days)
    outcomes = _run_outcomes(
        store, window_from=window_from,
        tenant_id=tenant_id, project_id=project_id)
    completed = sum(1 for v in outcomes.values() if v == "completed")
    failed = sum(1 for v in outcomes.values() if v == "failed")
    total = completed + failed
    availability = (completed / total * 100.0) if total else None
    allowed = total * (1 - spec.target_pct / 100.0)
    remaining = allowed - failed
    attained = (availability >= spec.target_pct) if total else None
    return SloReport(
        spec=spec, window_from=window_from.isoformat(),
        total_runs=total, completed=completed, failed=failed,
        availability_pct=None if availability is None
        else round(availability, 4),
        error_budget_allowed=round(allowed, 4),
        error_budget_remaining=round(remaining, 4),
        attained=attained,
    )


async def record_slo_report(
    store: Any, report: SloReport, *,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> None:
    """SLO 报告留痕（evaluation.slo_reported——运营测量入事件流）。"""
    sequencer = EventSequencer(
        store, _OPS_RUN, tenant_id=tenant_id, project_id=project_id)
    await sequencer.emit("evaluation.slo_reported", report.model_dump())


async def timed_recovery_drill(
    store: Any, dest: str | Path, *,
    rto_slo_s: float | None = None,
    rpo_slo_s: float | None = None,
    tenant_id: str = "t-default", project_id: str = "p-default",
    record: bool = True,
) -> dict[str, Any]:
    """计时恢复演练：RTO（墙钟）+ RPO（备份滞后期）实测 + 达标判定。

    RPO 口径：备份内最新事件时间距演练开始——灾难瞬间命中的数据
    损失上界（新鲜库即时备份 → RPO≈0；陈旧备份 → RPO 大）。"""
    from .ops import recovery_drill

    drill_start = datetime.now(UTC)
    t0 = time.perf_counter()
    base = await recovery_drill(store, dest)
    rto_s = time.perf_counter() - t0

    # RPO：恢复库中最新事件距演练开始（双方 aware UTC）
    from vasta_storage import SqliteStorage

    restored_root = Path(base["restored_root"])
    restored = SqliteStorage(restored_root)
    newest: datetime | None = None
    try:
        for run_id in _distinct_runs(restored):
            for event in restored.iter_run_events(
                    run_id, tenant_id=tenant_id, project_id=project_id):
                try:
                    ts = datetime.fromisoformat(str(event.ts))
                except ValueError:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if newest is None or ts > newest:
                    newest = ts
    finally:
        restored.close()
    rpo_s = (drill_start - newest).total_seconds() \
        if newest is not None else 0.0

    report = {
        **base,
        "rto_s": round(rto_s, 4),
        "rpo_s": round(rpo_s, 4),
        "rto_ok": (rto_s <= rto_slo_s) if rto_slo_s is not None else None,
        "rpo_ok": (rpo_s <= rpo_slo_s) if rpo_slo_s is not None else None,
        "passed": base["passed"]
        and (rto_slo_s is None or rto_s <= rto_slo_s)
        and (rpo_slo_s is None or rpo_s <= rpo_slo_s),
    }
    if record:
        sequencer = EventSequencer(
            store, _OPS_RUN, tenant_id=tenant_id, project_id=project_id)
        await sequencer.emit(
            "evaluation.drill_completed",
            {"rto_s": report["rto_s"], "rpo_s": report["rpo_s"],
             "rto_ok": report["rto_ok"], "rpo_ok": report["rpo_ok"],
             "passed": report["passed"], "integrity": base["integrity"]})
    return report


def drill_due(cron_expr: str, *, last_drill: datetime,
              now: datetime | None = None) -> bool:
    """定期编排判定：上次演练后已有到期触发点（CronSpec.next_after）。"""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)  # next_after 恒返 aware UTC
    return CronSpec(cron_expr).next_after(last_drill) <= now


def drill_executor(
    store_factory: Callable[[], Any],
    dest_root: str | Path,
) -> Callable[[list[Any], str], Awaitable[Any]]:
    """把计时演练包成 9.9 Scheduler 的执行器形态（cron 定期演练接线）。

    Scheduler 的执行面是 ``async (tasks, root) -> 摘要对象``（读取
    .runs/.success_rate——batch 摘要同契约）；本执行器忽略 tasks
    （演练不是任务批），每次触发跑一次计时演练。"""

    class _DrillSummary:
        def __init__(self, report: dict[str, Any]) -> None:
            self.runs = 1
            self.success_rate = 1.0 if report["passed"] else 0.0
            self.report = report

    async def _execute(_tasks: list[Any], _root: str) -> _DrillSummary:
        store = store_factory()
        try:
            return _DrillSummary(
                await timed_recovery_drill(store, Path(dest_root)))
        finally:
            store.close()

    return _execute


__all__ = [
    "SloReport",
    "SloSpec",
    "drill_due",
    "drill_executor",
    "record_slo_report",
    "slo_report",
    "timed_recovery_drill",
]
