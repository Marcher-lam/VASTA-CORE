"""私有注册表与版本锁定（Story 12.5，FR-082，G2）。

企业内插件的唯一可信来源（事件溯源——注册表状态是 registry 系统
流事件的投影，无自建表）：

- **register_plugin**：RBAC（registry write）→ 验签 → 清单规范形
  入 CAS → ``artifact.registered`` 留痕（manifest+签名+哈希全量入
  payload——拉取侧可重建验签对象）；
- **lock_plugin_version**：版本锁定 → ``artifact.locked`` 留痕
  （锁定后装配精确解析——不可变引用，新版本注册不漂移）；
- **resolve_plugin**：投影解析（locked 版本优先；显式 version 须与
  锁一致——不可变引用语义）；
- **pull_plugin**：按解析结果取 CAS 字节 → 重建 SignedPlugin →
  **重新验签 + 哈希对拍**（注册表只是索引——真实性由密码学校验）。

状态机：active（registered）→ revoked/deprecated（12.6）——
本模块的投影已识别终态（resolve/pull 跳过非 active 条目）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

from ..governance.rbac import Principal, evaluate_access
from .manifest import (
    KeyResolver,
    SignedPlugin,
    verify_plugin,
)

_REGISTRY_RUN = "registry"


class RegistryEntry(BaseModel):
    """注册表条目（artifact.registered 事件的投影）。"""

    model_config = ConfigDict(extra="forbid")

    plugin_id: str
    version: str
    content_sha256: str
    key_id: str
    registered_by: str
    status: str = Field(default="active",
                        description="active/revoked/deprecated（12.6）")
    successor: str | None = Field(
        default=None, description="弃用时的后继版本指引（12.6）")


def _require_registry_write(principal: Principal) -> None:
    decision = evaluate_access(principal, "registry", "write",
                               tenant_id=principal.tenant_id,
                               project_id=principal.project_id)
    if not decision.allowed:
        raise VastaError(
            code="access.denied",
            message=f"注册表发布需 registry write（{decision.reason}）",
        )


def _project_registry(
    store: Any, *, tenant_id: str, project_id: str,
) -> tuple[dict[tuple[str, str], RegistryEntry], dict[str, str]]:
    """registry 流投影 → (条目表, 锁定表)。后到事件覆盖先到。"""
    entries: dict[tuple[str, str], RegistryEntry] = {}
    locks: dict[str, str] = {}
    for event in store.iter_run_events(
            _REGISTRY_RUN, tenant_id=tenant_id, project_id=project_id):
        p = event.payload
        if event.type == "artifact.registered":
            key = (p["plugin_id"], p["version"])
            entries[key] = RegistryEntry(
                plugin_id=p["plugin_id"], version=p["version"],
                content_sha256=p["content_sha256"],
                key_id=p["key_id"], registered_by=p["registered_by"])
        elif event.type == "artifact.locked":
            locks[p["plugin_id"]] = p["version"]
        elif event.type in ("artifact.revoked", "artifact.deprecated"):
            key = (p["plugin_id"], p["version"])
            if key in entries:
                updated = entries[key].model_copy(update={
                    "status": "revoked" if event.type == "artifact.revoked"
                    else "deprecated",
                    "successor": p.get("successor")})
                entries[key] = RegistryEntry.model_validate(updated)
    return entries, locks


async def register_plugin(
    store: Any, signed: SignedPlugin, *, principal: Principal,
    key_resolver: KeyResolver,
) -> RegistryEntry:
    """发布插件版本：RBAC + 验签 + CAS + 留痕。

    评审修复（REG-1，盲审 H2/边界 6-1）：**(plugin_id, version) 不可
    变**——同版本重注册即拒（否则撤销终态可被同字节重放洗白回
    active、锁定引用被同版本换内容漂移）。新内容走新版本号。"""
    _require_registry_write(principal)
    entries, _ = _project_registry(
        store, tenant_id=principal.tenant_id,
        project_id=principal.project_id)
    key = (signed.manifest.plugin_id, signed.manifest.version)
    if key in entries:
        raise VastaError(
            code="registry.version_exists",
            message=(f"插件 {key[0]!r} 版本 {key[1]!r} 已注册——注册表"
                     "条目不可变（重注册即洗白/漂移），新内容走新版本号"),
        )
    verify_plugin(signed, key_resolver=key_resolver)
    sha = await store.save_artifact(
        signed.canonical_bytes(), mime="application/json",
        source=f"plugin:{signed.manifest.plugin_id}",
        tags={"plugin_id": signed.manifest.plugin_id,
              "version": signed.manifest.version},
        tenant_id=principal.tenant_id, project_id=principal.project_id)
    sequencer = EventSequencer(
        store, _REGISTRY_RUN,
        tenant_id=principal.tenant_id, project_id=principal.project_id)
    await sequencer.emit("artifact.registered", {
        "plugin_id": signed.manifest.plugin_id,
        "version": signed.manifest.version,
        "content_sha256": sha,
        "key_id": signed.key_id,
        "registered_by": principal.user,
        "manifest": signed.manifest.model_dump(mode="json"),
        "signature": signed.signature,
    })
    return RegistryEntry(
        plugin_id=signed.manifest.plugin_id,
        version=signed.manifest.version, content_sha256=sha,
        key_id=signed.key_id, registered_by=principal.user)


async def lock_plugin_version(
    store: Any, plugin_id: str, version: str, *, principal: Principal,
) -> None:
    """版本锁定（不可变引用——锁定后解析精确到该版本）。"""
    _require_registry_write(principal)
    entries, _ = _project_registry(
        store, tenant_id=principal.tenant_id,
        project_id=principal.project_id)
    if (plugin_id, version) not in entries:
        raise VastaError(
            code="registry.version_not_registered",
            message=(f"插件 {plugin_id!r} 版本 {version!r} 未注册——"
                     "锁定以已注册版本为对象"),
        )
    sequencer = EventSequencer(
        store, _REGISTRY_RUN,
        tenant_id=principal.tenant_id, project_id=principal.project_id)
    await sequencer.emit("artifact.locked", {
        "plugin_id": plugin_id, "version": version,
        "locked_by": principal.user,
    })


def resolve_plugin(
    store: Any, plugin_id: str, *, version: str | None = None,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> RegistryEntry:
    """解析注册表条目（锁定优先——不可变引用语义）：

    - 有锁：解析到锁定版本；显式 version 与锁不符即拒；
    - 无锁：显式 version 或最新 active 版本。"""
    entries, locks = _project_registry(
        store, tenant_id=tenant_id, project_id=project_id)
    locked = locks.get(plugin_id)
    if locked is not None:
        if version is not None and version != locked:
            raise VastaError(
                code="registry.lock_mismatch",
                message=(f"插件 {plugin_id!r} 已锁定 {locked!r}——"
                         f"请求 {version!r} 与锁不符（不可变引用）"),
            )
        version = locked
    if version is not None:
        entry = entries.get((plugin_id, version))
        if entry is None:
            raise VastaError(
                code="registry.not_found",
                message=f"插件 {plugin_id!r} 版本 {version!r} 不在注册表",
            )
        return entry
    # 评审修复（VER-1，盲审 M1）：latest 用数值序（此前字典序使
    # 1.9.0 战胜 1.10.0）——点分数字解析，非法版本号即拒
    from ._versions import parse_version

    candidates = [
        v for (pid, v) in entries if pid == plugin_id
        and entries[(pid, v)].status == "active"]
    if not candidates:
        raise VastaError(
            code="registry.not_found",
            message=f"插件 {plugin_id!r} 无 active 版本",
        )
    latest = max(candidates,
                 key=lambda v: parse_version(v, field="插件版本号",
                                             code="registry.bad_version"))
    return entries[(plugin_id, latest)]


async def pull_plugin(
    store: Any, plugin_id: str, *, version: str | None = None,
    key_resolver: KeyResolver,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> SignedPlugin:
    """拉取插件：解析 → 取 CAS 字节 → 哈希对拍 → 重建验签对象。"""
    import hashlib
    import json

    entry = resolve_plugin(store, plugin_id, version=version,
                           tenant_id=tenant_id, project_id=project_id)
    if entry.status == "revoked":
        raise VastaError(
            code="registry.not_active",
            message=(f"插件 {plugin_id!r} 版本 {entry.version!r} 已撤销"
                     "——不可拉取装配（12.6 撤销语义）"),
        )
    # deprecated 宽限：显式版本仍可拉（latest 解析已跳过——12.6）
    payload = await store.get_artifact(
        entry.content_sha256, tenant_id=tenant_id, project_id=project_id)
    if hashlib.sha256(payload).hexdigest() != entry.content_sha256:
        raise VastaError(
            code="registry.hash_mismatch",
            message=(f"插件 {plugin_id!r} CAS 字节与注册哈希不符"
                     "——注册表条目不可信"),
        )
    # 规范形 = manifest JSON + 签名/密钥尾行（拉取侧重建验签对象）
    body, _, trailer = payload.partition(b"\n# signature:")
    signature, _, key_id = trailer.partition(b"\n# key-id:")
    signed = SignedPlugin.model_validate({
        "manifest": json.loads(body),
        "signature": signature.decode(),
        "key_id": key_id.decode(),
    })
    verify_plugin(signed, key_resolver=key_resolver)
    return signed


__all__ = ["RegistryEntry", "lock_plugin_version", "pull_plugin",
           "register_plugin", "resolve_plugin"]
