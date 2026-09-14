"""撤销与弃用生命周期（Story 12.6，FR-082，G2）。

问题插件可下架且下游不静默破坏：

- **revoke_plugin**（撤销——安全原因，立即生效）：撤销前计算
  **依赖闭包**（registry 投影 BFS——depends_on 传递闭包）并入事件
  payload（下游不可静默破坏）；已运行实例留处置决策记录
  （``running_instances_disposition_required``——FR-017 删除证明
  的依赖检查同型）；撤销后 ``pull_plugin`` 拒（12.5 已接线
  ``registry.not_active``）；
- **deprecate_plugin**（弃用——预告迁移，宽限生效）：带后继版本
  指引；弃用版本在宽限期内仍可显式拉取（``pull_plugin`` 放行
  deprecated），但 latest 解析跳过（新装配自然迁移）。

状态机（registry 投影内）：active → revoked（终态）/ deprecated
（宽限）。
"""

from __future__ import annotations

from typing import Any

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

from ..governance.rbac import Principal
from .registry import (
    _REGISTRY_RUN,
    _project_registry,
    _require_registry_write,
)


def dependent_closure(
    store: Any, plugin_id: str, *,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> list[str]:
    """依赖闭包：传递依赖 plugin_id 的注册插件清单（BFS）。

    依赖边来自各插件清单的 depends_on（注册事件 payload 中的
    manifest）——投影内即可读，不回读 CAS。"""
    entries, _ = _project_registry(
        store, tenant_id=tenant_id, project_id=project_id)
    # 依赖边：插件（任意版本注册）→ 其 depends_on 目标
    dependents: dict[str, set[str]] = {}
    registered_manifests: dict[str, dict[str, Any]] = {}
    for event in store.iter_run_events(
            _REGISTRY_RUN, tenant_id=tenant_id, project_id=project_id):
        if event.type == "artifact.registered":
            manifest = event.payload.get("manifest") or {}
            registered_manifests[event.payload["plugin_id"]] = manifest
            for dep in manifest.get("depends_on", []):
                dependents.setdefault(dep, set()).add(
                    event.payload["plugin_id"])
    closure: set[str] = set()
    frontier = {plugin_id}
    while frontier:
        direct = set()
        for target in frontier:
            direct |= dependents.get(target, set())
        frontier = direct - closure
        closure |= frontier
    return sorted(closure)


async def revoke_plugin(
    store: Any, plugin_id: str, version: str, *, principal: Principal,
    reason: str,
) -> list[str]:
    """撤销插件版本（立即生效）——返回依赖闭包（撤销前列出下游）。"""
    _require_registry_write(principal)
    if not reason:
        raise VastaError(
            code="registry.revocation_reason_required",
            message="撤销必须携带原因（安全审计面——不可静默下架）",
        )
    entries, _ = _project_registry(
        store, tenant_id=principal.tenant_id,
        project_id=principal.project_id)
    entry = entries.get((plugin_id, version))
    if entry is None:
        raise VastaError(
            code="registry.not_found",
            message=f"插件 {plugin_id!r} 版本 {version!r} 不在注册表",
        )
    if entry.status == "revoked":
        raise VastaError(
            code="registry.already_revoked",
            message=f"插件 {plugin_id!r} 版本 {version!r} 已撤销（终态）",
        )
    closure = dependent_closure(
        store, plugin_id,
        tenant_id=principal.tenant_id, project_id=principal.project_id)
    sequencer = EventSequencer(
        store, _REGISTRY_RUN,
        tenant_id=principal.tenant_id, project_id=principal.project_id)
    await sequencer.emit("artifact.revoked", {
        "plugin_id": plugin_id, "version": version,
        "revoked_by": principal.user, "reason": reason,
        "dependent_plugins": closure,
        # 已运行实例处置决策记录（FR-017 依赖检查同型——不静默破坏）
        "running_instances_disposition_required": True,
    })
    return closure


async def deprecate_plugin(
    store: Any, plugin_id: str, version: str, *, principal: Principal,
    successor: str,
) -> None:
    """弃用插件版本（宽限生效）——后继版本指引必填。"""
    _require_registry_write(principal)
    entries, _ = _project_registry(
        store, tenant_id=principal.tenant_id,
        project_id=principal.project_id)
    if (plugin_id, version) not in entries:
        raise VastaError(
            code="registry.not_found",
            message=f"插件 {plugin_id!r} 版本 {version!r} 不在注册表",
        )
    if (plugin_id, successor) not in entries:
        raise VastaError(
            code="registry.successor_not_registered",
            message=(f"后继版本 {successor!r} 未注册——弃用指引必须"
                     "指向可迁移的已注册版本"),
        )
    sequencer = EventSequencer(
        store, _REGISTRY_RUN,
        tenant_id=principal.tenant_id, project_id=principal.project_id)
    await sequencer.emit("artifact.deprecated", {
        "plugin_id": plugin_id, "version": version,
        "deprecated_by": principal.user, "successor": successor,
    })


__all__ = ["dependent_closure", "deprecate_plugin", "revoke_plugin"]
