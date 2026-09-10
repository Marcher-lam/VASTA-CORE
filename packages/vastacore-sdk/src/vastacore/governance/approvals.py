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
    """批准是否有效：未撤销且未超时。

    naive ``now``（无时区）按**本地时区**解释（评审修复——公共 API
    对 datetime.now() 这类自然调用不再 TypeError，且墙钟语义正确：
    naive 本地时间锚定本地时区后比较）；
    到期瞬间（== expires_at）仍有效（含端点——设计选择）。"""
    from datetime import UTC

    from vasta_protocols.ids import now_utc

    if record.revoked:
        return False
    current = now or now_utc()
    if current.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo or UTC
        current = current.replace(tzinfo=local_tz)
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
    from uuid import uuid4

    from vasta_protocols.ids import now_utc

    if ttl_s <= 0:
        raise VastaError(
            code="approval.bad_ttl",
            message=f"ttl_s 须为正数（得到 {ttl_s}——零/负 TTL 的批准"
                    "签发即过期，无审计意义）",
        )
    approved_at = now_utc()
    expires_at = approved_at.fromtimestamp(
        approved_at.timestamp() + ttl_s,
        tz=approved_at.tzinfo,
    )
    # 随机尾段防同秒碰撞（评审修复——同 tool 同秒多批不再撞 id）
    approval_id = f"apr-{tool}-{int(approved_at.timestamp())}-{uuid4().hex[:8]}"
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
    """撤销批准（落撤销事件；按作用域过滤——跨租户同 id 不可误撤）。"""
    # 验证存在性（本作用域——评审修复：iter 全流匹配不带租户过滤）
    records = [
        e for e in store.iter_run_events(
            _APPROVALS_RUN, tenant_id=tenant_id, project_id=project_id)
        if e.type == "action.approval_record"
        and e.payload.get("approval_id") == approval_id
    ]
    if not records:
        raise VastaError(
            code="approval.not_found",
            message=f"批准记录 {approval_id!r} 在 {tenant_id}:{project_id}"
                    " 不存在",
        )
    sequencer = EventSequencer(
        store, _APPROVALS_RUN,
        tenant_id=tenant_id, project_id=project_id,
    )
    await sequencer.emit("action.approval_revoked", {
        "approval_id": approval_id,
        "reason": reason,
    })


async def get_approval(
    store: Any, approval_id: str, *,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> ApprovalRecord:
    """从事件流重建批准记录（含 revoked 状态——评审修复闭环：
    revoke 落事件后，经本函数重建的 record 在 is_approval_valid
    下立即失效；找不到报 approval.not_found）。"""
    from datetime import datetime

    record: dict[str, Any] | None = None
    revoked = False
    for event in store.iter_run_events(
            _APPROVALS_RUN, tenant_id=tenant_id, project_id=project_id):
        p = event.payload
        if event.type == "action.approval_record" \
                and p.get("approval_id") == approval_id:
            record = p
            revoked = False  # 同 id 重批后撤销位复位（以最后一条为准）
        elif event.type == "action.approval_revoked" \
                and p.get("approval_id") == approval_id and record:
            revoked = True
    if record is None:
        raise VastaError(
            code="approval.not_found",
            message=f"批准记录 {approval_id!r} 在 {tenant_id}:{project_id}"
                    " 不存在",
        )
    return ApprovalRecord(
        approval_id=approval_id,
        tool=record["tool"], args=dict(record.get("args", {})),
        scope=record["scope"],
        expires_at=datetime.fromisoformat(record["expires_at"]),
        approver=record["approver"],
        approved_at=datetime.fromisoformat(record["approved_at"]),
        revoked=revoked,
    )


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


__all__ = ["ApprovalRecord", "get_approval", "is_approval_valid",
           "record_approval", "revoke_approval", "search_approvals"]
