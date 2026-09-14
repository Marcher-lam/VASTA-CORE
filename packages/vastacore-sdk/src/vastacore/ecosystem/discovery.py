"""公开发现与评分（Story 12.8，FR-084，G3）。

好插件可被找到、质量信号可比较：

- **discover_plugins**：公开发现面——registry 投影过滤（active、
  扫描门通过——12.7 ``scan_passed`` fail-closed、兼容性可选）；
  弃用版本带标记列示（预告迁移）；
- **rate_plugin**：评分**引用评测事件而非复制数值**（11.12 证据
  引用语义——评分 payload 只携带 (evidence_run, evidence_event_seq)
  与指标名，分值由读者从被引事件解析，条目不可篡改）；
  ``artifact.rated`` 留痕；
- **plugin_rating**：聚合解析——逐条评分回读被引事件取分值求均
  （引用失效即拒——fail-closed）。

可见性：评分事件落 registry 系统流（租户作用域——private 缺省）；
公开发现面是只读聚合（public 语义——复用 11.6/11.12 的双面模式）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

from ..governance.rbac import Principal
from .registry import _REGISTRY_RUN, _project_registry, _require_registry_write
from .trust import registered_manifests, satisfies, scan_passed


class DiscoveredPlugin(BaseModel):
    """发现面条目（公开面）。"""

    model_config = ConfigDict(extra="forbid")

    plugin_id: str
    version: str
    status: str
    permissions: list[str] = Field(default_factory=list)
    platform: str = ""
    deprecated_successor: str | None = None


def discover_plugins(
    store: Any, *, platform_version: str | None = None,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> list[DiscoveredPlugin]:
    """公开发现面：active + 扫描门通过（未扫描即不公开——fail-closed）
    + 可选平台兼容过滤；弃用版本带后继标记列示。

    评审修复（VER-1 联动）：platform_version 非法形态入口即拒
    （VastaError——此前裸 ValueError 逃逸）。"""
    if platform_version is not None:
        from ._versions import parse_version

        parse_version(platform_version, field="platform_version")
    entries, _ = _project_registry(
        store, tenant_id=tenant_id, project_id=project_id)
    manifests = registered_manifests(
        store, tenant_id=tenant_id, project_id=project_id)
    discovered: list[DiscoveredPlugin] = []
    for (pid, version), entry in sorted(entries.items()):
        if entry.status == "revoked":
            continue  # 撤销即下架
        if not scan_passed(store, pid, version,
                           tenant_id=tenant_id, project_id=project_id):
            continue  # 扫描门不通过即拒公开（12.7 接线）
        manifest = manifests.get((pid, version)) or {}
        platform = (manifest.get("compatibility") or {}).get(
            "platform", "")
        if platform_version is not None and platform:
            try:
                if not satisfies(platform_version, platform):
                    continue
            except VastaError:
                continue  # 约束不可解析——公开面静默跳过（fail-safe）
        discovered.append(DiscoveredPlugin(
            plugin_id=pid, version=version, status=entry.status,
            permissions=list(manifest.get("permissions", [])),
            platform=platform,
            deprecated_successor=(entry.successor
                                  if entry.status == "deprecated"
                                  else None)))
    return discovered


class PluginRating(BaseModel):
    """评分引用（不复制数值——分值从被引事件解析）。"""

    model_config = ConfigDict(extra="forbid")

    plugin_id: str
    version: str
    metric: str
    evidence_run: str
    evidence_event_seq: int = Field(ge=0)
    rated_by: str


async def rate_plugin(
    store: Any, plugin_id: str, version: str, *, metric: str,
    evidence_run: str, evidence_event_seq: int,
    principal: Principal,
) -> PluginRating:
    """评分留痕：引用 (run, seq) 处的评测事件。

    评审修复（RATE-1，盲审 M3/边界 9-1/9-5/9-6）四道绑定：

    - 被评插件版本必须在册且 active（不可给幽灵插件刷分）；
    - 被引事件必须真实存在且属 evaluation 族（引用失效即拒）；
    - 被引事件**写时预验分值可解析**（毒评分不再瘫痪聚合读取）；
    - 被引事件的 ranking/entries 候选须含该 plugin_id（评测与被评
      对象绑定——任何无关评测事件不可刷分）；
    - 同 (plugin, version, run, seq, metric) 重放即拒（幂等）。"""
    _require_registry_write(principal)
    entries, _ = _project_registry(
        store, tenant_id=principal.tenant_id,
        project_id=principal.project_id)
    entry = entries.get((plugin_id, version))
    if entry is None or entry.status != "active":
        raise VastaError(
            code="discovery.plugin_not_active",
            message=(f"被评插件 {plugin_id!r}@{version} 不在注册表或"
                     "非 active——评分对象以注册表为准"),
        )
    referenced = None
    for event in store.iter_run_events(
            evidence_run, tenant_id=principal.tenant_id,
            project_id=principal.project_id):
        if event.seq == evidence_event_seq:
            referenced = event
            break
    if referenced is None or \
            not referenced.type.startswith("evaluation."):
        raise VastaError(
            code="discovery.bad_evidence_ref",
            message=(f"评分引用 ({evidence_run!r}, seq="
                     f"{evidence_event_seq}) 不存在或非 evaluation 族"
                     "事件——评分必须锚定真实评测证据"),
        )
    _score_of(referenced.payload)  # 写时预验（毒评分拒于门外）
    if not _event_mentions_plugin(referenced.payload, plugin_id):
        raise VastaError(
            code="discovery.evidence_not_about_plugin",
            message=(f"被引评测事件不含候选 {plugin_id!r}——评分证据"
                     "与被评对象必须绑定（不可借他者评测刷分）"),
        )
    for prior in store.iter_run_events(
            _REGISTRY_RUN, tenant_id=principal.tenant_id,
            project_id=principal.project_id):
        if event_is_same_rating(prior, plugin_id, version, metric,
                                evidence_run, evidence_event_seq):
            raise VastaError(
                code="discovery.duplicate_rating",
                message=(f"评分 (plugin={plugin_id!r}, run={evidence_run!r}"
                         f", seq={evidence_event_seq}, metric={metric!r})"
                         "已存在——评分不可重放"),
            )
    rating = PluginRating(
        plugin_id=plugin_id, version=version, metric=metric,
        evidence_run=evidence_run, evidence_event_seq=evidence_event_seq,
        rated_by=principal.user)
    sequencer = EventSequencer(
        store, _REGISTRY_RUN,
        tenant_id=principal.tenant_id, project_id=principal.project_id)
    await sequencer.emit("artifact.rated", {
        "plugin_id": plugin_id, "version": version, "metric": metric,
        "evidence_run": evidence_run,
        "evidence_event_seq": evidence_event_seq,
        "rated_by": principal.user,
    })
    return rating


def event_is_same_rating(event: Any, plugin_id: str, version: str,
                         metric: str, evidence_run: str,
                         evidence_event_seq: int) -> bool:
    """重放判定：已存在的同引用评分事件。"""
    return event.type == "artifact.rated" \
        and event.payload.get("plugin_id") == plugin_id \
        and event.payload.get("version") == version \
        and event.payload.get("metric") == metric \
        and event.payload.get("evidence_run") == evidence_run \
        and event.payload.get("evidence_event_seq") == evidence_event_seq


def _event_mentions_plugin(payload: dict[str, Any],
                           plugin_id: str) -> bool:
    """被引评测事件与被评插件的绑定：ranking/entries 候选名（生态
    评测约定候选名 = plugin_id）或 adapter 名含该插件。"""
    for key in ("ranking", "entries"):
        items = payload.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and \
                        item.get("candidate") == plugin_id:
                    return True
    return payload.get("adapter") == plugin_id


def plugin_rating(
    store: Any, plugin_id: str, *,
    version: str | None = None,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> float | None:
    """聚合评分：逐条回读被引事件解析分值求均（引用失效即拒）。

    ``version=None`` 为插件级均值（跨版本——口径在 docstring 明示；
    版本级聚合传显式 version）。"""
    scores: list[float] = []
    for event in store.iter_run_events(
            _REGISTRY_RUN, tenant_id=tenant_id, project_id=project_id):
        if event.type != "artifact.rated" \
                or event.payload["plugin_id"] != plugin_id:
            continue
        if version is not None \
                and event.payload.get("version") != version:
            continue
        referenced = None
        for ev in store.iter_run_events(
                event.payload["evidence_run"],
                tenant_id=tenant_id, project_id=project_id):
            if ev.seq == event.payload["evidence_event_seq"]:
                referenced = ev
                break
        if referenced is None:
            raise VastaError(
                code="discovery.dangling_evidence_ref",
                message=(f"评分引用 ({event.payload['evidence_run']!r},"
                         f" seq={event.payload['evidence_event_seq']})"
                         "已失效——证据链断裂（fail-closed）"),
            )
        scores.append(_score_of(referenced.payload))
    if not scores:
        return None
    return sum(scores) / len(scores)


def _score_of(payload: dict[str, Any]) -> float:
    """从被引评测事件 payload 解析分值（ranking 首位 score /
    leaderboard 首条 / 显式 score 字段——评测面约定；非 dict 条目
    跳过而非裸 AttributeError）。"""
    for key in ("ranking", "entries"):
        items = payload.get(key)
        if isinstance(items, list) and items:
            top = items[0]
            if isinstance(top, dict) and \
                    isinstance(top.get("score"), (int, float)) \
                    and not isinstance(top["score"], bool):
                return float(top["score"])
            continue
    if isinstance(payload.get("score"), (int, float)) \
            and not isinstance(payload["score"], bool):
        return float(payload["score"])
    if isinstance(payload.get("ci"), dict) and \
            isinstance(payload["ci"].get("mean"), (int, float)):
        return float(payload["ci"]["mean"])
    raise VastaError(
        code="discovery.unresolvable_score",
        message="被引评测事件无可解析分值（ranking/entries/score/ci 均无）",
    )


__all__ = ["DiscoveredPlugin", "PluginRating", "discover_plugins",
           "plugin_rating", "rate_plugin"]
