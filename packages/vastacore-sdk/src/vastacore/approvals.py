"""批准记录五要素绑定（Story 9.5，FR-034，G3）。

每次批准绑定动作/参数/范围/时限/批准者——「谁在何时批了什么」不可抵赖：
- `record_approval` 落 "approvals" 系统流（action.approval_record 事件，
  五要素全量 payload）；
- `is_approval_valid` 超时自动失效（供给点时钟，AD-5）；
- `revoke_approval` 落撤销事件（action.approval_revoked）；
- `search_approvals` 按批准者审计检索；
- 与 Epic 3 approve_pending **并行不替代**——参数级审计层（FR-034
  明文 Stage 3），引擎级批准语义不变。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

_APPROVALS_RUN = "approvals"


class ApprovalRecord(BaseModel):
    """批准记录（五要素——FR-034 字面）。"""

    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=1)
    tool: str = Field(min_length=1, description="被批准的动作")
    args: dict[str, Any] = Field(default_factory=dict, description="被批准的参数")
    scope: str = Field(min_length=1, description="作用域 tenant:project")
    expires_at: datetime = Field(description="时限（超时自动失效）")
    approver: str = Field(min_length=1, description="批准者")
    approved_at: datetime = Field(description="批准时刻")
    revoked: bool = Field(default=False)


def is_approval_valid(
    record: ApprovalRecord, *, now: datetime | None = None,
) -> bool:
    """批准是否有效：未撤销且未超时。"""
    from vasta_protocols.ids import now_utc

    if record.revoked:
        return False
    current = now or now_utc()
    return current <= record.expires_at


async def record_approval(
    store: Any,
    *,
    tool: str,
    args: dict[str, Any],
    approver: str,
    scope: str,
    ttl_s: int,
    tenant_id: str = "t-default",
    project_id: str = "p-default",
) -> ApprovalRecord:
    """记录批准（五要素 → approvals 系统流）。"""
    from vasta_protocols.ids import now_utc

    approved_at = now_utc()
    expires_at = approved_at.fromtimestamp(
        approved_at.timestamp() + ttl_s,
        tz=approved_at.tzinfo,
    )
    approval_id = f"apr-{tool}-{int(approved_at.timestamp())}"
    record = ApprovalRecord(
        approval_id=approval_id, tool=tool, args=dict(args),
        scope=scope, expires_at=expires_at, approver=approver,
        approved_at=approved_at,
    )
    sequencer = EventSequencer(
        store, _APPROVALS_RUN,
        tenant_id=tenant_id, project_id=project_id,
    )
    await sequencer.emit("action.approval_record", {
        "approval_id": approval_id,
        "tool": tool, "args": dict(args),
        "scope": scope,
        "expires_at": expires_at.isoformat(),
        "approver": approver,
        "approved_at": approved_at.isoformat(),
    })
    return record


async def revoke_approval(
    store: Any, approval_id: str, *, reason: str,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> None:
    """撤销批准（落撤销事件）。"""
    # 验证存在性
    records = [e for e in store.iter_run_events(_APPROVALS_RUN)
               if e.type == "action.approval_record"
               and e.payload.get("approval_id") == approval_id]
    if not records:
        raise VastaError(
            code="approval.not_found",
            message=f"批准记录 {approval_id!r} 不存在",
        )
    sequencer = EventSequencer(
        store, _APPROVALS_RUN,
        tenant_id=tenant_id, project_id=project_id,
    )
    await sequencer.emit("action.approval_revoked", {
        "approval_id": approval_id,
        "reason": reason,
    })


async def search_approvals(
    store: Any, *, approver: str | None = None,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> list[Any]:
    """按批准者审计检索（返回 action.approval_record 事件列表）。"""
    kwargs: dict[str, Any] = {}
    if approver:
        kwargs["payload_equals"] = {"approver": approver}
    return await store.search_events(
        tenant_id, project_id,
        run_id=_APPROVALS_RUN,
        event_type="action.approval_record",
        **kwargs,
    )


__all__ = ["ApprovalRecord", "is_approval_valid", "record_approval",
           "revoke_approval", "search_approvals"]
