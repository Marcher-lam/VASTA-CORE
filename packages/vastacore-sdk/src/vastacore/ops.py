"""运维基线（Story 9.12，FR-076，G5）。

出事知道、坏了能修：

- 告警规则（AlertRule/evaluate_alerts）：错误率 / 队列深 / 配额触顶
  三类关键指标阈值规则——对指标快照评估，触发即 Alert（severity 分级）；
- 备份恢复（backup_snapshot/restore_snapshot/recovery_drill）：
  SQLite 在线备份（backup API——WAL 安全，锁内一致性快照）→ 恢复到
  目标路径 → **事件流完整性校验**（每 run seq 连续无洞 + parent 链
  一致 + 信封可重建）→ 演练报告（一键 backup→restore→verify）；
- 事故管理（declare_incident/resolve_incident/incident_archive）：
  ``incident.declared``（关联 Run 清单 + severity）/ ``incident.resolved``
  （处置结论）事件留痕（incident 族）；复盘归档从事件流重放聚合
  （declarations ↔ resolutions 配对 + 关联 Run 终态）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

_INCIDENTS_RUN = "incidents"

#: 备份一致性锁提示（SqliteStorage._conn.backup 在锁内执行）
_SEVERITIES = ("sev1", "sev2", "sev3")


# ---- 指标与告警 ----

class MetricsSnapshot(BaseModel):
    """服务指标快照（MVP 形态——JSON /metrics 的数据面）。"""

    model_config = ConfigDict(extra="forbid")

    error_rate: float = Field(default=0.0, ge=0.0)
    queue_depth: int = Field(default=0, ge=0)
    quota_throttled: int = Field(default=0, ge=0)
    sessions_active: int = Field(default=0, ge=0)
    extra: dict[str, float] = Field(default_factory=dict)


class AlertRule(BaseModel):
    """阈值规则：metric > threshold 即触发。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    metric: str  # error_rate | queue_depth | quota_throttled | extra 键
    threshold: float
    severity: str = "sev3"  # _SEVERITIES

    def model_post_init(self, __context: Any) -> None:
        if self.severity not in _SEVERITIES:
            raise VastaError(
                code="ops.bad_severity",
                message=f"severity 须为 {_SEVERITIES}（得到 {self.severity!r}）",
            )


class Alert(BaseModel):
    """触发中的告警。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    metric: str
    value: float
    threshold: float
    severity: str


def default_alert_rules() -> list[AlertRule]:
    """关键指标基线规则（错误率 / 队列深 / 配额触顶——AC 字面）。"""
    return [
        AlertRule(name="error_rate_high", metric="error_rate",
                  threshold=0.05, severity="sev1"),
        AlertRule(name="queue_depth_high", metric="queue_depth",
                  threshold=100, severity="sev2"),
        AlertRule(name="quota_throttling", metric="quota_throttled",
                  threshold=10, severity="sev2"),
    ]


def evaluate_alerts(
    snapshot: MetricsSnapshot,
    rules: list[AlertRule] | None = None,
) -> list[Alert]:
    """规则评估：metric > threshold 触发（严格大于——恰好达标不告警）。"""
    rules = rules if rules is not None else default_alert_rules()
    values: dict[str, float] = {
        "error_rate": snapshot.error_rate,
        "queue_depth": float(snapshot.queue_depth),
        "quota_throttled": float(snapshot.quota_throttled),
        "sessions_active": float(snapshot.sessions_active),
        **snapshot.extra,
    }
    alerts: list[Alert] = []
    for rule in rules:
        value = values.get(rule.metric)
        if value is None:
            raise VastaError(
                code="ops.unknown_metric",
                message=(f"规则 {rule.name!r} 引用未知指标 {rule.metric!r}"
                         "（快照未携带）"),
            )
        if value > rule.threshold:
            alerts.append(Alert(name=rule.name, metric=rule.metric,
                                value=value, threshold=rule.threshold,
                                severity=rule.severity))
    return alerts


# ---- 备份 / 恢复 / 演练 ----

class IntegrityReport(BaseModel):
    """事件流完整性校验报告（恢复后必过）。"""

    model_config = ConfigDict(extra="forbid")

    runs_checked: int = Field(ge=0)
    events_checked: int = Field(ge=0)
    seq_gaps: list[str] = Field(default_factory=list,
                                description="seq 断裂的 run 清单")
    parent_breaks: list[str] = Field(default_factory=list,
                                     description="父链断裂的 run 清单")

    @computed_field
    @property
    def ok(self) -> bool:
        """派生：无断裂即通过（随清单填充实时反映；序列化包含）。"""
        return not self.seq_gaps and not self.parent_breaks


def verify_stream_integrity(store: Any) -> IntegrityReport:
    """事件流完整性校验：每 run seq 从 0 连续无洞；parent_event_id 链
    与前一事件 event_id 一致（首事件 None）。信封可重建（model_validate
    已由迭代器保证——损坏行在读取面暴露）。"""
    runs = _distinct_runs(store)
    report = IntegrityReport(runs_checked=len(runs), events_checked=0)
    for run_id in runs:
        events = list(store.iter_run_events(run_id))
        report.events_checked += len(events)
        prev_id: str | None = None
        for i, event in enumerate(events):
            if event.seq != i:
                report.seq_gaps.append(run_id)
                break
            if event.parent_event_id != prev_id:
                report.parent_breaks.append(run_id)
                break
            prev_id = event.event_id
    return report


def _distinct_runs(store: Any) -> list[str]:
    """全库 run 清单（元数据面直查——不重放全事件）。"""
    with store._lock:  # noqa: SLF001——同 SDK 域运维直查
        rows = store._conn.execute(  # noqa: SLF001
            "SELECT DISTINCT run_id FROM events ORDER BY run_id"
        ).fetchall()
    return [r[0] for r in rows]


def backup_snapshot(store: Any, dest: str | Path) -> Path:
    """SQLite 在线备份（backup API——WAL 模式一致性快照，锁内执行）。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()  # 幂等：覆盖旧备份
    dest_conn = sqlite3.connect(dest)
    try:
        with store._lock:  # noqa: SLF001——快照一致性
            store._conn.backup(dest_conn)  # noqa: SLF001
    finally:
        dest_conn.close()
    return dest


def restore_snapshot(backup: str | Path, target: str | Path) -> Path:
    """备份恢复到目标目录（target/ 目录下重建 store.db + objects/）。

    恢复语义：备份文件即恢复库（不回写原库——演练/回滚以新根落地，
    原库不受影响）。"""
    backup, target = Path(backup), Path(target)
    if not backup.exists():
        raise VastaError(
            code="ops.backup_missing",
            message=f"备份文件 {backup} 不存在",
        )
    target.mkdir(parents=True, exist_ok=True)
    (target / "store.db").write_bytes(backup.read_bytes())
    return target


async def recovery_drill(store: Any, dest: str | Path) -> dict[str, Any]:
    """恢复演练：备份 → 恢复到演练根 → 打开恢复库校验事件流完整性
    → 报告（AC：恢复后事件流完整校验）。原库只读不写。"""
    from vasta_storage import SqliteStorage

    backup = backup_snapshot(store, dest)
    drill_root = backup.with_name(f"{backup.stem}-restored")
    restore_snapshot(backup, drill_root)
    restored = SqliteStorage(drill_root)
    try:
        integrity = verify_stream_integrity(restored)
    finally:
        restored.close()
    return {
        "backup": str(backup),
        "restored_root": str(drill_root),
        "integrity": integrity.model_dump(),
        "passed": integrity.ok,
    }


# ---- 事故管理 ----

class IncidentRecord(BaseModel):
    """复盘归档中的单事故视图（重放聚合）。"""

    model_config = ConfigDict(extra="forbid")

    incident_id: str
    title: str
    severity: str
    related_runs: list[str] = Field(default_factory=list)
    resolved: bool = False
    resolution: str | None = None


async def declare_incident(
    store: Any, title: str, *,
    related_runs: list[str], severity: str = "sev2",
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> str:
    """事故登记（incident.declared——关联 Run + severity 留痕）。"""
    if severity not in _SEVERITIES:
        raise VastaError(
            code="ops.bad_severity",
            message=f"severity 须为 {_SEVERITIES}（得到 {severity!r}）",
        )
    if not related_runs:
        raise VastaError(
            code="ops.incident_needs_runs",
            message="事故须关联至少一个 Run（无 Run 的异常走日志面）",
        )
    from vasta_protocols.ids import new_event_id

    incident_id = f"inc-{new_event_id()[:12]}"
    sequencer = EventSequencer(
        store, _INCIDENTS_RUN,
        tenant_id=tenant_id, project_id=project_id)
    await sequencer.emit("incident.declared", {
        "incident_id": incident_id, "title": title,
        "severity": severity, "related_runs": list(related_runs),
    })
    return incident_id


async def resolve_incident(
    store: Any, incident_id: str, *, resolution: str,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> None:
    """事故结案（incident.resolved——处置结论留痕；未登记/重复结案拒）。"""
    records = incident_archive(store)
    if incident_id not in {r.incident_id for r in records}:
        raise VastaError(
            code="ops.incident_not_found",
            message=f"事故 {incident_id!r} 未登记",
        )
    if any(r.resolved for r in records if r.incident_id == incident_id):
        raise VastaError(
            code="ops.incident_already_resolved",
            message=f"事故 {incident_id!r} 已结案（复盘归档不可改写）",
        )
    sequencer = EventSequencer(
        store, _INCIDENTS_RUN,
        tenant_id=tenant_id, project_id=project_id)
    await sequencer.emit("incident.resolved", {
        "incident_id": incident_id, "resolution": resolution,
    })


def incident_archive(store: Any) -> list[IncidentRecord]:
    """复盘归档：incident.* 事件流重放聚合（声明↔结案配对 + 关联 Run
    + 处置结论）。"""
    records: dict[str, IncidentRecord] = {}
    for event in store.iter_run_events(_INCIDENTS_RUN):
        p = event.payload
        if event.type == "incident.declared":
            iid = p["incident_id"]
            records[iid] = IncidentRecord(
                incident_id=iid, title=p.get("title", ""),
                severity=p.get("severity", "sev3"),
                related_runs=list(p.get("related_runs", [])),
            )
        elif event.type == "incident.resolved" \
                and p.get("incident_id") in records:
            rec = records[p["incident_id"]]
            rec.resolved = True
            rec.resolution = str(p.get("resolution", ""))
    return list(records.values())


__all__ = ["Alert", "AlertRule", "IncidentRecord", "IntegrityReport",
           "MetricsSnapshot", "backup_snapshot", "declare_incident",
           "default_alert_rules", "evaluate_alerts", "incident_archive",
           "recovery_drill", "resolve_incident", "restore_snapshot",
           "verify_stream_integrity"]
