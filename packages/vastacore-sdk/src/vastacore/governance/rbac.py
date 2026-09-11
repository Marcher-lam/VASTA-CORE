"""RBAC/ABAC 角色模型（Story 10.8，FR-071 前半，G3）。

共享 token 升级为**每操作鉴权**：

- 角色（Role）：viewer / operator / auditor / admin 四档——能力矩阵
  （资源类 × 动作）声明式定义；admin 全通过、越权 fail-closed（403
  ``access.denied`` 留痕 access 流）；
- 主体（Principal）：身份（user id）+ 角色 + 作用域（tenant/project）
  ——Bearer token 到主体的解析由装配面注入（静态映射开发档；10.9
  OIDC 接真实 IdP）；
- ABAC 属性规则：作用域匹配（跨租户拒）+ 资源类动作匹配——
  ``evaluate_access`` 纯函数（可单测）+ ``require_role`` FastAPI
  依赖工厂（service/studio 端点接入，403 留痕）；
- 角色分配留痕：``assign_role`` → ``evaluation.role_assigned``？——
  否：访问控制事件归 incident 族语义不贴；用**专门的 access 流**
  ``access.role_assigned``（事件族 access 是新族？不行——13 族封闭
  集！归 ``run.role_assigned``（run 族，治理运行时动作）；
  拒绝留痕 ``access.denied`` 同理改 ``run.access_denied``？
  ——已存在 ``artifact.access_denied``（9.4，artifact 族）。
  HTTP 面的拒绝是**服务访问**不是工件内容——用 run 族
  ``run.access_denied``（与 run.throttled 同族形态）。

- F8 顺带（G0-G2 评审 defer 挂本 Story）：release 全链线程化
  tenant_id/project_id——promote/suspend/resume/retire/revoke/rollback
  加作用域参数，复核/重放/级联全链透传。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.sequencer import EventSequencer

_ACCESS_RUN = "access"

#: 资源类（ABAC 维度之一——端点族）。
RESOURCES = ("runs", "evidence", "cognition", "governance", "ops")

#: 动作。
ACTIONS = ("read", "write", "approve", "admin")


class Role(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    AUDITOR = "auditor"
    ADMIN = "admin"


#: 能力矩阵：角色 → {(资源类, 动作)} 允许集（admin = 全通过特判）。
_CAPABILITIES: dict[Role, frozenset[tuple[str, str]]] = {
    Role.VIEWER: frozenset({
        ("runs", "read"), ("evidence", "read"), ("cognition", "read"),
        ("ops", "read"),
    }),
    Role.OPERATOR: frozenset({
        ("runs", "read"), ("runs", "write"),
        ("evidence", "read"), ("evidence", "write"),
        ("cognition", "read"), ("cognition", "write"),
        ("ops", "read"),
    }),
    Role.AUDITOR: frozenset({
        ("runs", "read"), ("evidence", "read"), ("cognition", "read"),
        ("governance", "read"), ("ops", "read"),
    }),
    Role.ADMIN: frozenset(),  # 全通过（特判——含 governance write/approve）
}


class Principal(BaseModel):
    """访问主体（token 解析产物）。"""

    model_config = ConfigDict(extra="forbid")

    user: str = Field(min_length=1)
    role: Role
    tenant_id: str
    project_id: str


class AccessDecision(BaseModel):
    """策略评估结果。"""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason: str = ""
    principal: str
    resource: str
    action: str


def evaluate_access(
    principal: Principal, resource: str, action: str, *,
    tenant_id: str, project_id: str,
) -> AccessDecision:
    """ABAC 策略评估（纯函数）：

    1. 作用域匹配——主体作用域必须覆盖请求作用域（跨租户/项目拒）；
    2. 能力匹配——(resource, action) 在角色允许集（admin 全通过）。
    """
    if tenant_id != principal.tenant_id or project_id != principal.project_id:
        return AccessDecision(
            allowed=False,
            reason=(f"作用域不匹配：主体 {principal.tenant_id}:"
                    f"{principal.project_id} vs 请求 {tenant_id}:{project_id}"),
            principal=principal.user, resource=resource, action=action)
    if principal.role is Role.ADMIN or \
            (resource, action) in _CAPABILITIES[principal.role]:
        return AccessDecision(
            allowed=True, principal=principal.user,
            resource=resource, action=action)
    return AccessDecision(
        allowed=False,
        reason=(f"角色 {principal.role.value} 无 {resource}:{action}"
                " 能力（fail-closed）"),
        principal=principal.user, resource=resource, action=action)


async def assign_role(
    store: Any, user: str, role: Role, *,
    assigned_by: str,
    tenant_id: str, project_id: str,
) -> None:
    """角色分配留痕（run.role_assigned——run 族，治理运行时动作）。"""
    sequencer = EventSequencer(
        store, _ACCESS_RUN, tenant_id=tenant_id, project_id=project_id)
    await sequencer.emit("run.role_assigned", {
        "user": user, "role": role.value, "assigned_by": assigned_by,
    })


async def deny_trace(
    store: Any, decision: AccessDecision, *,
    tenant_id: str, project_id: str,
    path: str = "",
) -> None:
    """拒绝留痕（run.access_denied——与 run.throttled 同族形态）。

    留痕失败不掩盖拒绝本体（服务面依赖工厂同步抛 403）。"""
    import contextlib

    with contextlib.suppress(Exception):
        sequencer = EventSequencer(
            store, _ACCESS_RUN, tenant_id=tenant_id, project_id=project_id)
        await sequencer.emit("run.access_denied", {
            "user": decision.principal, "resource": decision.resource,
            "action": decision.action, "reason": decision.reason,
            "path": path,
        })


#: 静态主体映射（开发档——token → Principal；10.9 由 OIDC claims 替代）。
def make_principal_resolver(
    mappings: dict[str, Principal],
) -> Any:
    """构造 token→主体 解析器（开发档静态映射）。

    返回 callable(token: str) -> Principal | None——装配面注入服务；
    None = 未知 token（fail-closed 由调用方拒）。"""
    def resolve(token: str) -> Principal | None:
        return mappings.get(token)

    return resolve


def require_role(
    resource: str, action: str, *,
    resolver: Any,
    store: Any = None,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> Any:
    """FastAPI 依赖工厂：token 解析 → 策略评估 → 拒绝 403 留痕。

    用法：``dependencies=[Depends(require_role("runs", "write",
    resolver=..., store=...))]``——替代裸 require_token（认证+鉴权
    一体：401 未知 token / 403 越权）。"""

    async def dependency(request: Request) -> Principal:
        import inspect

        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip()
        principal = None
        if token:
            result = resolver(token)
            # 评审修复 H-1/F1：OIDC as_resolver 是 async——同步 resolver
            # （静态映射）与异步（IdP）统一兼容
            principal = await result if inspect.isawaitable(result)                 else result
        if principal is None:
            raise HTTPException(status_code=401, detail="invalid token")
        decision = evaluate_access(
            principal, resource, action,
            tenant_id=tenant_id, project_id=project_id)
        if not decision.allowed:
            if store is not None:
                # async 依赖内直接 await——确定性留痕（拒绝抛出前完成）
                await deny_trace(
                    store, decision, tenant_id=tenant_id,
                    project_id=project_id,
                    path=str(getattr(request, "url", "")))
            raise HTTPException(
                status_code=403, detail=decision.reason)
        request.state.principal = principal  # 端点取真实身份
        return principal

    return dependency


__all__ = ["ACTIONS", "AccessDecision", "Principal", "RESOURCES",
           "Role", "assign_role", "deny_trace", "evaluate_access",
           "make_principal_resolver", "require_role"]
