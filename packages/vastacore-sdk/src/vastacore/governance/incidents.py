"""事故管理（Story 9.12 起，Story 10.4 评审修复 F3
自 ops 下沉至 governance——incident 是治理语义，与 approvals/release
同域；ops 层经 re-export 后向兼容）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

_INCIDENTS_RUN = "incidents"
_SEVERITIES = ("sev1", "sev2", "sev3")



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
    subject: str | None = None,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> str:
    """事故登记（incident.declared——关联 Run + severity 留痕）。

    related_runs 与 subject 至少其一（评审修复 F10：非 Run 治理对象
    （如模型漂移）不再伪装 run id——subject 承载其引用）。"""
    if severity not in _SEVERITIES:
        raise VastaError(
            code="ops.bad_severity",
            message=f"severity 须为 {_SEVERITIES}（得到 {severity!r}）",
        )
    if not related_runs and not subject:
        raise VastaError(
            code="ops.incident_needs_runs",
            message="事故须关联至少一个 Run 或治理对象（subject）",
        )
    from vasta_protocols.ids import new_event_id

    incident_id = f"inc-{new_event_id()[:12]}"
    sequencer = EventSequencer(
        store, _INCIDENTS_RUN,
        tenant_id=tenant_id, project_id=project_id)
    await sequencer.emit("incident.declared", {
        "incident_id": incident_id, "title": title,
        "severity": severity, "related_runs": list(related_runs),
        **({"subject": subject} if subject else {}),
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




__all__ = ["IncidentRecord", "declare_incident",
           "incident_archive", "resolve_incident"]
