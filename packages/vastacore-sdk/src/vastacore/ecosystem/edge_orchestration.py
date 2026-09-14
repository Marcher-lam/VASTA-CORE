"""跨区域数据面与边缘编排（Story 12.11，FR-079，G5）。

数据驻留边界内就近执行、证据跨区域回传：

- **RegionSpec / register_region**：区域数据面声明——``in-region``
  驻留（区域原始数据不出域）/ ``open``（可整帧回传）；区域状态
  ``active/unreachable``（``run.region_registered`` 留痕）；
- **deploy_edge_group**：边缘编组下发（清单化编排——编组 × 插件
  版本 × 区域清单；插件须在注册表 active、区域须 active——
  ``run.edge_group_deployed`` 留痕）；
- **return_frames_cross_region**：跨区证据回传——复用 11.13 帧级
  CAS + 完整性校验（``StreamingEnvironment.commit_frame``）；源区
  ``in-region`` 时只回传 **digest 清单帧**（原始帧体留源域 CAS）；
- **fail-closed 路由**：目标区域未注册/不可达即 ``run.region_unreachable``
  留痕并拒（不静默降级）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

from ..agents.streaming_edge import StreamFrame, StreamingEnvironment
from ..governance.rbac import Principal
from .registry import _project_registry, _require_registry_write

_EDGE_RUN = "edge-orchestration"


class RegionSpec(BaseModel):
    """区域数据面声明。"""

    model_config = ConfigDict(extra="forbid")

    region_id: str = Field(min_length=1)
    data_residency: str = Field(pattern="^(in-region|open)$",
                                description="in-region=原始数据不出域"
                                            "（回传仅 digest 清单）")
    status: str = Field(pattern="^(active|unreachable)$", default="active")
    tenant_id: str = "t-default"
    project_id: str = "p-default"


def _region_projection(
    store: Any, *, tenant_id: str, project_id: str,
) -> dict[str, RegionSpec]:
    regions: dict[str, RegionSpec] = {}
    for event in store.iter_run_events(
            _EDGE_RUN, tenant_id=tenant_id, project_id=project_id):
        if event.type == "run.region_registered":
            p = event.payload
            regions[p["region_id"]] = RegionSpec(
                region_id=p["region_id"],
                data_residency=p["data_residency"],
                status=p.get("status", "active"),
                tenant_id=tenant_id, project_id=project_id)
    return regions


async def register_region(
    store: Any, spec: RegionSpec, *, principal: Principal,
) -> None:
    """区域注册/状态更新留痕（治理动作——registry write）。"""
    _require_registry_write(principal)
    sequencer = EventSequencer(
        store, _EDGE_RUN,
        tenant_id=principal.tenant_id, project_id=principal.project_id)
    await sequencer.emit("run.region_registered", {
        "region_id": spec.region_id,
        "data_residency": spec.data_residency,
        "status": spec.status,
        "registered_by": principal.user,
    })


class EdgeDeployment(BaseModel):
    """边缘编组下发清单（清单化编排）。"""

    model_config = ConfigDict(extra="forbid")

    group: str = Field(min_length=1)
    plugin_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    regions: list[str] = Field(min_length=1)


async def deploy_edge_group(
    store: Any, deployment: EdgeDeployment, *, principal: Principal,
) -> None:
    """编组下发：插件在注册表 active + 区域全部 active → 留痕。"""
    _require_registry_write(principal)
    entries, _ = _project_registry(
        store, tenant_id=principal.tenant_id,
        project_id=principal.project_id)
    entry = entries.get((deployment.plugin_id, deployment.version))
    if entry is None or entry.status != "active":
        raise VastaError(
            code="edge.plugin_not_deployable",
            message=(f"插件 {deployment.plugin_id!r}"
                     f"@{deployment.version} 不在注册表或非 active"
                     "——编组下发以注册表为准"),
        )
    regions = _region_projection(
        store, tenant_id=principal.tenant_id,
        project_id=principal.project_id)
    for region_id in deployment.regions:
        spec = regions.get(region_id)
        if spec is None or spec.status != "active":
            await _trace_unreachable(store, region_id,
                                     tenant_id=principal.tenant_id,
                                     project_id=principal.project_id)
            raise VastaError(
                code="edge.region_unreachable",
                message=(f"编组 {deployment.group!r} 目标区域 "
                         f"{region_id!r} 未注册或不可达——fail-closed"
                         "（不静默降级到其余区域）"),
            )
    sequencer = EventSequencer(
        store, _EDGE_RUN,
        tenant_id=principal.tenant_id, project_id=principal.project_id)
    await sequencer.emit("run.edge_group_deployed", {
        "group": deployment.group,
        "plugin_id": deployment.plugin_id,
        "version": deployment.version,
        "regions": list(deployment.regions),
        "deployed_by": principal.user,
    })


async def _trace_unreachable(store: Any, region_id: str, *,
                             tenant_id: str, project_id: str) -> None:
    sequencer = EventSequencer(
        store, _EDGE_RUN, tenant_id=tenant_id, project_id=project_id)
    await sequencer.emit("run.region_unreachable", {"region": region_id})


async def return_frames_cross_region(
    store: Any, frames: list[StreamFrame], *, source_region: str,
    target_region: str, frame_commit: Any,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> list[StreamFrame]:
    """跨区证据回传（复用 11.13 帧级 CAS + 完整性校验）。

    - 源区 ``open``：整帧逐帧 CAS 提交至目标区
      （``observation.stream_frame`` 留痕）；
    - 源区 ``in-region``：**仅回传 digest 清单帧**（原始帧体留源域
      CAS——数据不出域），清单帧同样走帧级 CAS；
    - 目标区域不可达：``run.region_unreachable`` 留痕并拒。"""
    regions = _region_projection(store, tenant_id=tenant_id,
                                 project_id=project_id)
    source = regions.get(source_region)
    target = regions.get(target_region)
    if target is None or target.status != "active":
        await _trace_unreachable(store, target_region,
                                 tenant_id=tenant_id,
                                 project_id=project_id)
        raise VastaError(
            code="edge.region_unreachable",
            message=(f"回传目标区域 {target_region!r} 未注册或不可达"
                     "——fail-closed（不静默丢弃回传）"),
        )
    if source is None:
        raise VastaError(
            code="edge.source_region_unknown",
            message=f"源区域 {source_region!r} 未注册——回传无从路由",
        )
    env = StreamingEnvironment(count_window=1,
                               stream_id=f"{source_region}-return")
    import hashlib
    import json

    if source.data_residency == "in-region":
        # 数据不出域：清单帧 = 帧摘要集（无原始帧体）
        manifest = {
            "source_region": source_region,
            "frame_ids": [f.frame_id for f in frames],
            "digests": [f.payload_digest for f in frames],
            "seqs": [f.seq for f in frames],
        }
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True,
                       ensure_ascii=False).encode()).hexdigest()
        manifest_frame = StreamFrame(
            frame_id=f"{source_region}:manifest", seq=0,
            event_count=len(frames), payload_digest=digest)
        committed = [await env.commit_frame(
            store, manifest_frame, frame_commit=frame_commit,
            tenant_id=tenant_id, project_id=project_id)]
        return committed
    committed = []
    for frame in sorted(frames, key=lambda f: f.seq):
        committed.append(await env.commit_frame(
            store, frame, frame_commit=frame_commit,
            tenant_id=tenant_id, project_id=project_id))
    return committed


__all__ = ["EdgeDeployment", "RegionSpec", "deploy_edge_group",
           "register_region", "return_frames_cross_region"]
