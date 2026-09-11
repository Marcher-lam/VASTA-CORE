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

from ..governance.alerting import (  # noqa: F401
    Alert,
    AlertRule,
    MetricsSnapshot,
    default_alert_rules,
    evaluate_alerts,
)
from ..governance.incidents import (  # noqa: F401
    IncidentRecord,
    declare_incident,
    incident_archive,
    resolve_incident,
)

_INCIDENTS_RUN = "incidents"

#: 备份一致性锁提示（SqliteStorage._conn.backup 在锁内执行）


# ---- 指标与告警 ----

# 评审修复 F3：告警与事故原语下沉 governance（drift 反向依赖打破
# layers 契约）——此处 re-export 后向兼容（ops 域消费者零改动）。

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
    missing_artifacts: list[str] = Field(
        default_factory=list,
        description="引用悬空/损坏的工件清单（评审修复 H3：恢复库"
                    "须证据可达，不只是事件可读）")

    @computed_field
    @property
    def ok(self) -> bool:
        """派生：无断裂且无悬空工件即通过（随清单填充实时反映）。"""
        return not self.seq_gaps and not self.parent_breaks \
            and not self.missing_artifacts


def verify_stream_integrity(store: Any) -> IntegrityReport:
    """事件流完整性校验：每 run seq 从 0 连续无洞；parent_event_id 链
    与前一事件 event_id 一致（首事件 None）；事件引用的工件全部可达
    且哈希可校验（get_artifact 内含校验——H3：证据面一并核）。"""
    runs = _distinct_runs(store)
    report = IntegrityReport(runs_checked=len(runs), events_checked=0)
    refs: set[str] = set()
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
        for event in events:
            payload_refs = event.payload.get("artifact_refs")
            if isinstance(payload_refs, list):
                refs.update(str(r) for r in payload_refs)
            for key in ("contract_ref", "result_ref"):
                ref = event.payload.get(key)
                if ref:
                    refs.add(str(ref))
    for sha in sorted(refs):
        try:
            store.get_artifact(sha)
        except Exception:  # noqa: BLE001——悬空/损坏统一记 missing
            report.missing_artifacts.append(sha)
    return report


def _distinct_runs(store: Any) -> list[str]:
    """全库 run 清单（元数据面直查——不重放全事件）。"""
    with store._lock:  # noqa: SLF001——同 SDK 域运维直查
        rows = store._conn.execute(  # noqa: SLF001
            "SELECT DISTINCT run_id FROM events ORDER BY run_id"
        ).fetchall()
    return [r[0] for r in rows]


_SQLITE_MAGIC = b"SQLite format 3\x00"


def backup_snapshot(store: Any, dest: str | Path) -> Path:
    """一致性备份（评审修复 H3/F6：库 + **objects/ 证据 CAS**——原仅拷
    store.db，恢复后全部工件悬空而校验仍绿）。

    dest 为备份**目录**（store.db + objects/）；SQLite 经 backup API
    （WAL 一致性，锁内），objects/ 文件拷贝（内容寻址不可变——拷贝
    即一致）。幂等：清空旧目录重建。"""
    dest = Path(dest)
    if dest.exists():
        import shutil

        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    dest_conn = sqlite3.connect(dest / "store.db")
    try:
        with store._lock:  # noqa: SLF001——快照一致性
            store._conn.backup(dest_conn)  # noqa: SLF001
    finally:
        dest_conn.close()
    objects = Path(store.objects_dir)
    if objects.exists():
        import shutil

        shutil.copytree(objects, dest / "objects",
                        dirs_exist_ok=True)
    return dest


def restore_snapshot(backup: str | Path, target: str | Path) -> Path:
    """备份恢复到目标目录（store.db + objects/）。

    恢复语义：备份目录即恢复源（不回写原库——演练/回滚以新根落地，
    原库不受影响）。备份完整性先验（评审修复 F5：0 字节/torn 备份
    曾静默恢复成空库且演练「通过」）。"""
    backup, target = Path(backup), Path(target)
    db = backup / "store.db" if (backup / "store.db").exists() \
        else backup  # 兼容裸 db 文件形态
    if not db.exists():
        raise VastaError(
            code="ops.backup_missing",
            message=f"备份 {backup} 不存在",
        )
    head = db.read_bytes()[:16] if db.stat().st_size >= 16 else b""
    if head != _SQLITE_MAGIC:
        raise VastaError(
            code="ops.corrupt_backup",
            message=(f"备份 {db} 非 SQLite 库（截断/损坏——头校验"
                     "失败，拒绝静默恢复成空库）"),
        )
    target.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copyfile(db, target / "store.db")
    if (backup / "objects").exists():
        shutil.copytree(backup / "objects", target / "objects",
                        dirs_exist_ok=True)
    return target


async def recovery_drill(store: Any, dest: str | Path) -> dict[str, Any]:
    """恢复演练：备份 → 恢复到演练根 → 打开恢复库校验事件流完整性
    → 报告（AC：恢复后事件流完整校验）。原库只读不写。"""
    from vasta_storage import SqliteStorage

    backup = backup_snapshot(store, dest)
    drill_root = backup.parent / f"{backup.name}-restored"
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


__all__ = ["Alert", "AlertRule", "IncidentRecord", "IntegrityReport",
           "MetricsSnapshot", "backup_snapshot", "declare_incident",
           "default_alert_rules", "evaluate_alerts", "incident_archive",
           "recovery_drill", "resolve_incident", "restore_snapshot",
           "verify_stream_integrity"]
