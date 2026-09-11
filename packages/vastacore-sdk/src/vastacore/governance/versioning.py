"""模型与策略版本化（Story 8.8，FR-061，G4）——「回到当时」补齐后两类对象。

- 模型资产（DSL ruleset / 受限 Python code + manifest）打包 JSON 入 CAS，
  发布事件 `world_model.published` 落 registry 系统流——事件流即版本链
  （AD-2：投影可重建）；
- 策略配置快照 JSON 入 CAS，发布事件 `artifact.published`
  （kind=policy_config）；
- `version_as_of` 重放 registry 事件至指定点取当时版本 + CAS 取回完整
  bundle（模型可重建、策略 dict 原样往返）——CAS 内容寻址保证旧版本
  不可变，回放不串版；
- 同版本同内容幂等（CAS 同址）；同版本异内容拒绝（registry.conflict）。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from vasta_protocols.envelope import EventEnvelope
from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

_REGISTRY_RUN = "registry"


class PublishedRef(BaseModel):
    """发布结果引用。"""

    model_config = ConfigDict(extra="forbid")

    kind: str  # model | policy
    name: str
    version: str
    sha256: str


class VersionRecord(BaseModel):
    """as-of 取回的完整版本记录（bundle 元数据；payload 经属性懒取）。"""

    model_config = ConfigDict(extra="forbid")

    kind: str
    name: str
    version: str
    sha256: str
    bundle: dict[str, Any]

    @property
    def config(self) -> dict[str, Any]:
        """策略配置原样往返（kind=policy）。"""
        if self.kind != "policy":
            raise VastaError(
                code="versioning.not_policy",
                message=f"{self.name!r} 是 {self.kind}，无 config 字段",
            )
        return dict(self.bundle["config"])

    def rebuild_dsl(self) -> Any:
        """重建 DSLWorldModel（kind=model 且 bundle 形态为 ruleset）。"""
        from vasta_model_lab import DSLWorldModel, RuleSet, WorldModelManifest

        if self.kind != "model" or "ruleset" not in self.bundle:
            raise VastaError(
                code="versioning.not_dsl_model",
                message=f"{self.name!r} 的 bundle 不是 DSL ruleset 形态",
            )
        manifest = WorldModelManifest.model_validate(self.bundle["manifest"])
        ruleset = RuleSet.model_validate(self.bundle["ruleset"])
        return DSLWorldModel(manifest, ruleset)

    def rebuild_python(self) -> Any:
        """重建受限 Python 模型（kind=model 且 bundle 形态为 code）。"""
        from vasta_model_lab import PythonWorldModel, WorldModelManifest

        if self.kind != "model" or "code" not in self.bundle:
            raise VastaError(
                code="versioning.not_python_model",
                message=f"{self.name!r} 的 bundle 不是 Python code 形态",
            )
        manifest = WorldModelManifest.model_validate(self.bundle["manifest"])
        return PythonWorldModel(manifest, self.bundle["code"])


# ---- registry 事件发射（seq 每次全量同步——与 cognition/桥接同策略）----

async def _emit_registry(
    store: Any, type_: str, payload: dict[str, Any],
    *, tenant_id: str = "t-default", project_id: str = "p-default",
) -> EventEnvelope:
    # 统一序列器（Story 9.1）：系统流模式（registry 并发发布安全）
    sequencer = EventSequencer(
        store, _REGISTRY_RUN, tenant_id=tenant_id, project_id=project_id,
    )
    return await sequencer.emit(type_, payload)


def _existing_version(
    store: Any, kind: str, name: str, version: str, *,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> dict[str, Any] | None:
    """registry 流中该 (kind, name, version) 的既有发布（None=未发布过；
    F8：按作用域过滤——跨租户同键互为幻影）。"""
    for event in store.iter_run_events(
            _REGISTRY_RUN, tenant_id=tenant_id, project_id=project_id):
        if event.type != _event_type_of(kind):
            continue
        p = event.payload
        if p.get("name") == name and p.get("version") == version:
            return dict(p)
    return None


def _event_type_of(kind: str) -> str:
    if kind == "model":
        return "world_model.published"
    if kind == "policy":
        return "artifact.published"
    raise VastaError(
        code="versioning.unknown_kind",
        message=f"未知版本化对象类型 {kind!r}（支持: model/policy）",
    )


async def _publish(
    store: Any, kind: str, name: str, version: str,
    bundle: dict[str, Any],
    *, tenant_id: str = "t-default", project_id: str = "p-default",
) -> PublishedRef:
    try:
        canonical = json.dumps(
            {"kind": kind, "name": name, "version": version, "bundle": bundle},
            ensure_ascii=False, sort_keys=True,
        ).encode("utf-8")
    except TypeError as exc:
        # 评审修复：与策略路径对称——不可序列化内容在构造期拒绝
        raise VastaError(
            code="versioning.bad_bundle",
            message=f"bundle 含不可 JSON 序列化的值: {exc}",
        ) from exc
    import hashlib

    sha = hashlib.sha256(canonical).hexdigest()
    existing = _existing_version(store, kind, name, version,
                                 tenant_id=tenant_id,
                                 project_id=project_id)
    if existing is not None:
        if existing.get("sha256") == sha:
            return PublishedRef(kind=kind, name=name, version=version, sha256=sha)
        raise VastaError(
            code="registry.conflict",
            message=(
                f"{kind} {name!r} v{version} 已发布为不同内容"
                f"（{existing.get('sha256', '')[:12]}… ≠ {sha[:12]}…）——"
                "版本号不可复用（事件溯源不覆盖）"
            ),
        )
    await store.save_artifact(
        canonical, mime="application/json",
        source="registry", classification=f"{kind}-version",
        tenant_id=tenant_id, project_id=project_id,
    )
    await _emit_registry(
        store, _event_type_of(kind),
        {"kind": kind, "name": name, "version": version, "sha256": sha},
        tenant_id=tenant_id, project_id=project_id,
    )
    return PublishedRef(kind=kind, name=name, version=version, sha256=sha)


async def publish_model_version(
    store: Any, name: str, version: str, *,
    ruleset: dict[str, Any] | None = None,
    code: str | None = None,
    manifest: dict[str, Any],
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> PublishedRef:
    """发布模型版本（ruleset 与 code 二选一；manifest 必备）。"""
    if (ruleset is None) == (code is None):
        raise VastaError(
            code="versioning.bad_model_form",
            message="ruleset 与 code 必须二选一",
        )
    bundle: dict[str, Any] = {"manifest": dict(manifest)}
    if ruleset is not None:
        bundle["ruleset"] = dict(ruleset)
    else:
        bundle["code"] = code
    return await _publish(
        store, "model", name, version, bundle,
        tenant_id=tenant_id, project_id=project_id,
    )


async def publish_policy_snapshot(
    store: Any, name: str, version: str, config: dict[str, Any],
    *, tenant_id: str = "t-default", project_id: str = "p-default",
) -> PublishedRef:
    """发布策略配置快照。"""
    try:
        json.dumps(config, sort_keys=True, ensure_ascii=False)
    except TypeError as exc:
        raise VastaError(
            code="versioning.bad_config",
            message=f"策略配置含不可 JSON 序列化的值: {exc}",
        ) from exc
    return await _publish(
        store, "policy", name, version, {"config": dict(config)},
        tenant_id=tenant_id, project_id=project_id,
    )


async def version_as_of(
    store: Any, kind: str, name: str, *,
    version: str | None = None,
    as_of_seq: int | None = None,
    as_of_ts: datetime | None = None,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> VersionRecord:
    """取该名称当时（默认最新）的版本记录 + 完整 bundle（只读零副作用）。

    ``version`` 指定时取该版本（未发布过该版本则 not_found）——
    影子对比（compare_shadow）与发布存在性校验（promote）用。"""
    type_ = _event_type_of(kind)
    latest: dict[str, Any] | None = None
    found = False
    for event in store.iter_run_events(
            _REGISTRY_RUN, tenant_id=tenant_id, project_id=project_id):
        if as_of_seq is not None and event.seq > as_of_seq:
            continue
        if as_of_ts is not None and event.ts > as_of_ts:
            continue
        if event.type != type_:
            continue
        p = event.payload
        if p.get("name") != name:
            continue
        if version is not None and p.get("version") != version:
            continue
        latest = dict(p)
        found = True
    if not found or latest is None:
        point = "latest" if (as_of_seq is None and as_of_ts is None) else (
            f"seq={as_of_seq}" if as_of_seq is not None else f"ts={as_of_ts}"
        )
        target = f" v{version}" if version is not None else ""
        raise VastaError(
            code="versioning.not_found",
            message=f"{kind} {name!r}{target} 在 {point} 无发布记录",
        )
    canonical = await store.get_artifact(
        latest["sha256"], tenant_id=tenant_id, project_id=project_id,
    )
    bundle = json.loads(canonical.decode("utf-8"))["bundle"]
    return VersionRecord(
        kind=kind, name=name, version=latest["version"],
        sha256=latest["sha256"], bundle=bundle,
    )


__all__ = ["PublishedRef", "VersionRecord", "publish_model_version",
           "publish_policy_snapshot", "version_as_of"]
