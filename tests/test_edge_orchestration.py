"""Story 12.11：跨区域数据面与边缘编排（FR-079，G5）。"""

from __future__ import annotations

import hashlib

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.agents.streaming_edge import StreamFrame
from vastacore.ecosystem.edge_orchestration import (
    EdgeDeployment,
    RegionSpec,
    deploy_edge_group,
    register_region,
    return_frames_cross_region,
)
from vastacore.ecosystem.manifest import PluginManifest, sign_manifest
from vastacore.ecosystem.registry import register_plugin
from vastacore.governance.rbac import Principal, Role


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


KEY = b"k"


def key_resolver(key_id: str) -> bytes:
    return KEY


def operator() -> Principal:
    return Principal(user="op", role=Role.OPERATOR,
                     tenant_id="t", project_id="p")


async def cas_commit(body: bytes, frame_id: str) -> str:
    return hashlib.sha256(body).hexdigest()


def frame(seq: int) -> StreamFrame:
    return StreamFrame(
        frame_id=f"edge:f{seq}", seq=seq, event_count=3,
        payload_digest=hashlib.sha256(f"frame-{seq}".encode()).hexdigest())


async def publish_plugin(store) -> None:
    await register_plugin(
        store,
        sign_manifest(
            PluginManifest(plugin_id="collector", version="1.0.0",
                           name="collector", permissions=["query"],
                           data={}, network={"egress": []},
                           resources={"max_actions": 1},
                           compatibility={"platform": ">=0.1.0"}),
            key_id="k", key=KEY),
        principal=operator(), key_resolver=key_resolver)


class TestRegionRegistration:
    async def test_register_region_traced(self, store) -> None:
        """AC：区域数据面声明留痕。"""
        await register_region(
            store, RegionSpec(region_id="eu-1", data_residency="in-region"),
            principal=operator())
        events = [e for e in store.iter_run_events("edge-orchestration")
                  if e.type == "run.region_registered"]
        assert events[-1].payload["data_residency"] == "in-region"

    async def test_invalid_residency_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RegionSpec(region_id="x", data_residency="anywhere")


class TestEdgeDeployment:
    async def test_deploy_validates_plugin_and_regions(
            self, store) -> None:
        """AC：编组下发清单化——插件注册表 active + 区域 active。"""
        await publish_plugin(store)
        await register_region(
            store, RegionSpec(region_id="eu-1", data_residency="open"),
            principal=operator())
        await deploy_edge_group(
            store,
            EdgeDeployment(group="collectors", plugin_id="collector",
                           version="1.0.0", regions=["eu-1"]),
            principal=operator())
        events = [e for e in store.iter_run_events("edge-orchestration")
                  if e.type == "run.edge_group_deployed"]
        assert events[-1].payload["regions"] == ["eu-1"]

    async def test_deploy_unknown_region_fail_closed(self, store) -> None:
        """AC：区域不可达 fail-closed + run.region_unreachable 留痕。"""
        await publish_plugin(store)
        with pytest.raises(VastaError) as e:
            await deploy_edge_group(
                store,
                EdgeDeployment(group="g", plugin_id="collector",
                               version="1.0.0", regions=["mars-1"]),
                principal=operator())
        assert e.value.code == "edge.region_unreachable"
        events = [ev for ev in store.iter_run_events("edge-orchestration")
                  if ev.type == "run.region_unreachable"]
        assert events[-1].payload["region"] == "mars-1"

    async def test_deploy_unregistered_plugin_rejected(
            self, store) -> None:
        await register_region(
            store, RegionSpec(region_id="eu-1", data_residency="open"),
            principal=operator())
        with pytest.raises(VastaError) as e:
            await deploy_edge_group(
                store,
                EdgeDeployment(group="g", plugin_id="ghost",
                               version="1.0.0", regions=["eu-1"]),
                principal=operator())
        assert e.value.code == "edge.plugin_not_deployable"


class TestCrossRegionReturn:
    async def test_open_region_full_frames_returned(self, store) -> None:
        """AC：open 源区整帧回传——复用帧 CAS + stream_frame 留痕。"""
        for rid, residency in (("edge-1", "open"), ("hub", "open")):
            await register_region(
                store, RegionSpec(region_id=rid, data_residency=residency),
                principal=operator())
        committed = await return_frames_cross_region(
            store, [frame(0), frame(1)], source_region="edge-1",
            target_region="hub", frame_commit=cas_commit,
            tenant_id="t", project_id="p")
        assert [f.seq for f in committed] == [0, 1]
        assert all(f.cas_sha256 for f in committed)
        events = [e for e in store.iter_run_events("edge-stream")
                  if e.type == "observation.stream_frame"]
        assert len(events) == 2

    async def test_in_region_source_returns_digest_manifest_only(
            self, store) -> None:
        """AC：in-region 驻留——原始帧体不出域，仅 digest 清单帧。"""
        for rid, residency in (("eu-1", "in-region"), ("hub", "open")):
            await register_region(
                store, RegionSpec(region_id=rid, data_residency=residency),
                principal=operator())
        frames = [frame(0), frame(1)]
        committed = await return_frames_cross_region(
            store, frames, source_region="eu-1", target_region="hub",
            frame_commit=cas_commit, tenant_id="t", project_id="p")
        assert len(committed) == 1  # 单清单帧
        events = [e for e in store.iter_run_events("edge-stream")
                  if e.type == "observation.stream_frame"]
        # 目标区只见清单帧（event_count=帧数），原始帧摘要入清单
        assert events[-1].payload["frame_id"] == "eu-1:manifest"
        assert events[-1].payload["event_count"] == 2
        assert len(events) == 1  # 无原始帧体回传

    async def test_unreachable_target_rejected_with_trace(
            self, store) -> None:
        """AC：目标不可达——留痕并拒（不静默降级）。"""
        await register_region(
            store, RegionSpec(region_id="edge-1", data_residency="open"),
            principal=operator())
        await register_region(
            store, RegionSpec(region_id="hub", data_residency="open",
                              status="unreachable"),
            principal=operator())
        with pytest.raises(VastaError) as e:
            await return_frames_cross_region(
                store, [frame(0)], source_region="edge-1",
                target_region="hub", frame_commit=cas_commit,
                tenant_id="t", project_id="p")
        assert e.value.code == "edge.region_unreachable"
        events = [ev for ev in store.iter_run_events("edge-orchestration")
                  if ev.type == "run.region_unreachable"]
        assert events[-1].payload["region"] == "hub"

    async def test_unknown_source_rejected(self, store) -> None:
        await register_region(
            store, RegionSpec(region_id="hub", data_residency="open"),
            principal=operator())
        with pytest.raises(VastaError) as e:
            await return_frames_cross_region(
                store, [frame(0)], source_region="ghost-region",
                target_region="hub", frame_commit=cas_commit,
                tenant_id="t", project_id="p")
        assert e.value.code == "edge.source_region_unknown"
