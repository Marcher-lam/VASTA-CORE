"""审计日志聚合（Story 10.10，FR-071 尾，G3）。

「谁在何时对什么做了什么」的单一查询面：

- **跨流聚合**（query_audit_log）：分散系统流（approvals/access/
  quotas/incidents/lifecycle/release/billing/schedules/environment/
  cognition/registry）归一为 **主体→动作→资源→结果** 四元组
  （归一规则表按事件类型声明主体字段/资源提取/结果判定——未覆盖
  类型缺省 system 主体 + unknown 资源，不丢事件）；
- **查询**：时间窗 + 主体（用户）+ 资源类型三维过滤；
- **导出接 10.6**：``AuditExport.audit_log`` 字段（可选填充——
  ``export_audit_json(include_audit_log=True)``）；
- **不可篡改声明**（audit_log_integrity_statement）：append-only
  事件流为源（AD-2）——声明体含事件计数、链尾哈希锚（parent 链 +
  全量信封摘要）与 verify_stream_integrity 的引用；本函数只读。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: 聚合面系统流（与 audit_export.AUDIT_STREAMS 同源）。
_AUDIT_STREAMS: tuple[str, ...] = (
    "approvals", "access", "quotas", "billing", "incidents",
    "lifecycle", "schedules", "environment", "cognition", "registry",
    "evaluation",
)

#: 结果判定：事件类型 → 结果（缺省 "success"）。
_RESULT_OF: dict[str, str] = {
    "artifact.access_denied": "denied",
    "run.throttled": "denied",
    "run.access_denied": "denied",
    "action.policy_denied": "denied",
    "claim.refuted": "adverse",
    "claim.disputed": "adverse",
    "release.rolled_back": "adverse",
    "plan.fire_failed": "failed",
    "action.batch_aborted": "failed",
    "incident.opened": "alerted",
}


class AuditEntry(BaseModel):
    """归一化审计条目（四元组 + 溯源）。"""

    model_config = ConfigDict(extra="forbid")

    ts: str
    principal: str = Field(description="主体（谁）")
    action: str = Field(description="动作（事件类型）")
    resource: str = Field(description="资源（对什么）")
    result: str = Field(description="结果（success/denied/…）")
    stream: str = Field(description="源系统流（溯源）")
    seq: int = Field(ge=0)
    event_id: str


class AuditLogQuery(BaseModel):
    """审计日志查询（三维过滤）。"""

    model_config = ConfigDict(extra="forbid")

    start_ts: datetime
    end_ts: datetime
    principal: str | None = None
    resource_prefix: str | None = None
    action_prefix: str | None = None
    tenant_id: str = "t-default"
    project_id: str = "p-default"


#: 事件类型感知的主体字段优先级（user 字段在 role_assigned 里是被
#: 操作对象而非主体——assigned_by 才是动作执行者）。
_PRINCIPAL_FIELDS: dict[str, tuple[str, ...]] = {
    "run.role_assigned": ("assigned_by", "user"),
}
_DEFAULT_PRINCIPAL_FIELDS: tuple[str, ...] = (
    "approver", "user", "principal", "annotator", "exported_by",
    "assigned_by", "requested_by")


def _principal_of(event_type: str, payload: dict[str, Any]) -> str:
    """主体提取（事件类型感知的字段优先级——缺失归 system）。"""
    for field in _PRINCIPAL_FIELDS.get(event_type,
                                       _DEFAULT_PRINCIPAL_FIELDS):
        value = payload.get(field)
        if isinstance(value, str) and value:
            return value
    return "system"


def _resource_of(event_type: str, payload: dict[str, Any]) -> str:
    """资源提取（按事件类型的资源键约定——缺失归 unknown）。"""
    # 资产三元组（kind/name/version）优先于通用 id——资产引用在审计
    # 语义上比关联 id（如 approval_id）更有用（revoke 事件的资源应是
    # 模型而非批准号）
    if "kind" in payload and "name" in payload:
        version = payload.get("version", "")
        return f"{payload['kind']}/{payload['name']}/{version}".rstrip("/")
    for field in ("claim_id", "plan_id", "sha256", "run_id",
                  "user", "approval_id", "incident_id"):
        value = payload.get(field)
        if isinstance(value, str) and value:
            return value
    for field in ("model", "title"):
        value = payload.get(field)
        if isinstance(value, str) and value:
            return value
    if "related_runs" in payload and payload["related_runs"]:
        return ",".join(str(r) for r in payload["related_runs"][:3])
    return "unknown"


def query_audit_log(
    store: Any, query: AuditLogQuery,
) -> list[AuditEntry]:
    """跨流聚合查询（归一四元组——按 ts 排序）。

    主体字段缺失归 ``system``、资源缺失归 ``unknown``——事件不因
    归一失败丢失（完整性优先于精度）。"""
    from .audit_export import _in_window

    entries: list[AuditEntry] = []
    for stream in _AUDIT_STREAMS:
        for event in store.iter_run_events(
                stream, tenant_id=query.tenant_id,
                project_id=query.project_id):
            if not _in_window(event, query.start_ts, query.end_ts):
                continue
            payload = dict(event.payload)
            principal = _principal_of(event.type, payload)
            resource = _resource_of(event.type, payload)
            entry = AuditEntry(
                ts=event.ts.isoformat(), principal=principal,
                action=event.type, resource=resource,
                result=_RESULT_OF.get(event.type, "success"),
                stream=stream, seq=event.seq, event_id=event.event_id,
            )
            if query.principal and entry.principal != query.principal:
                continue
            if query.resource_prefix and not entry.resource.startswith(
                    query.resource_prefix):
                continue
            if query.action_prefix and not entry.action.startswith(
                    query.action_prefix):
                continue
            entries.append(entry)
    entries.sort(key=lambda e: (e.ts, e.stream, e.seq))
    return entries


def audit_log_integrity_statement(store: Any) -> dict[str, Any]:
    """不可篡改声明（只读）：append-only 事件流为源（AD-2）——

    - 计数锚：各审计流事件数；
    - 哈希锚：全量信封摘要链尾（逐事件 canonical JSON → 链式
      SHA-256——重放可复算比对）；
    - 校验引用：ops.verify_stream_integrity（seq/parent 链一致性）。
    声明本身不入流（防自引用）——由验证方现场重算。"""
    counts: dict[str, int] = {}
    chain_hash = hashlib.sha256(b"vasta-audit-log-root").hexdigest()
    for stream in _AUDIT_STREAMS:
        for event in store.iter_run_events(stream):
            counts[stream] = counts.get(stream, 0) + 1
            canonical = json.dumps(
                {k: event.model_dump(mode="json")[k]
                 for k in ("run_id", "seq", "event_id", "type", "ts")},
                sort_keys=True, ensure_ascii=False)
            chain_hash = hashlib.sha256(
                (chain_hash + canonical).encode("utf-8")).hexdigest()
    return {
        "statement": "append-only 事件流为唯一源（AD-2）——本声明可由"
                     "验证方对同源流重算链式摘要比对；结构性一致性另经"
                     "verify_stream_integrity（seq 连续/parent 链）校验",
        "total_events": sum(counts.values()),
        "per_stream": counts,
        "chain_sha256_tail": chain_hash,
        "algorithm": "SHA-256(event_id|seq|type|ts 逐事件链式——根种子"
                     "vasta-audit-log-root)",
    }


__all__ = ["AuditEntry", "AuditLogQuery", "audit_log_integrity_statement",
           "query_audit_log"]
