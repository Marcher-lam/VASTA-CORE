"""Story 12.8：公开发现与评分（FR-084，G3）。"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer
from vasta_storage import SqliteStorage
from vastacore.ecosystem.discovery import (
    discover_plugins,
    plugin_rating,
    rate_plugin,
)
from vastacore.ecosystem.manifest import PluginManifest, sign_manifest
from vastacore.ecosystem.registry import register_plugin
from vastacore.ecosystem.revocation import deprecate_plugin, revoke_plugin
from vastacore.ecosystem.trust import security_scan
from vastacore.governance.rbac import Principal, Role


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


KEY = b"k"


def key_resolver(key_id: str) -> bytes:
    return KEY


def publisher() -> Principal:
    return Principal(user="op-1", role=Role.OPERATOR,
                     tenant_id="t", project_id="p")


def manifest(plugin_id="csv", version="1.0.0", **kw) -> PluginManifest:
    base = dict(plugin_id=plugin_id, version=version, name=plugin_id,
                permissions=["query"], data={}, network={"egress": []},
                resources={"max_actions": 1},
                compatibility={"platform": ">=0.1.0"})
    base.update(kw)
    return PluginManifest(**base)


async def publish_scanned(store, m: PluginManifest | None = None) -> None:
    """发布 + 扫描通过（公开面前置）。"""
    m = m or manifest()
    signed = sign_manifest(m, key_id="k", key=KEY)
    await register_plugin(store, signed, principal=publisher(),
                          key_resolver=key_resolver)
    await security_scan(store, signed, principal=publisher())


async def seed_eval_event(store, score: float) -> tuple[str, int]:
    """落一条可被评分引用的评测事件（tournament_settled）。"""
    seq = EventSequencer(store, "evaluation", tenant_id="t", project_id="p")
    envelope = await seq.emit("evaluation.tournament_settled", {
        "tournament_id": "t-1", "winner": "alpha",
        "ranking": [{"candidate": "alpha", "failed": False,
                     "score": score}]})
    return "evaluation", envelope.seq


class TestDiscovery:
    async def test_unscanned_not_listed(self, store) -> None:
        """AC：扫描门不通过即拒公开——未扫描不列（fail-closed）。"""
        signed = sign_manifest(manifest(), key_id="k", key=KEY)
        await register_plugin(store, signed, principal=publisher(),
                              key_resolver=key_resolver)
        assert discover_plugins(store, tenant_id="t",
                                project_id="p") == []

    async def test_scanned_listed_with_faces(self, store) -> None:
        """AC：发现面带清单六面信息（权限/兼容）。"""
        await publish_scanned(store)
        listed = discover_plugins(store, tenant_id="t", project_id="p")
        assert [(p.plugin_id, p.version, p.status) for p in listed] == \
            [("csv", "1.0.0", "active")]
        assert listed[0].permissions == ["query"]
        assert listed[0].platform == ">=0.1.0"

    async def test_platform_filter(self, store) -> None:
        await publish_scanned(store, manifest(version="1.0.0"))
        await publish_scanned(store, manifest(
            version="2.0.0", compatibility={"platform": ">=1.0.0"}))
        listed = discover_plugins(store, platform_version="0.5.0",
                                  tenant_id="t", project_id="p")
        assert [p.version for p in listed] == ["1.0.0"]

    async def test_revoked_not_listed_deprecated_flagged(
            self, store) -> None:
        """撤销下架；弃用带后继标记列示（预告迁移）。"""
        await publish_scanned(store, manifest(version="1.0.0"))
        await publish_scanned(store, manifest(version="2.0.0"))
        await revoke_plugin(store, "csv", "1.0.0",
                            principal=publisher(), reason="security")
        await deprecate_plugin(store, "csv", "2.0.0",
                               principal=publisher(), successor="1.0.0")
        listed = discover_plugins(store, tenant_id="t", project_id="p")
        assert [p.version for p in listed] == ["2.0.0"]
        assert listed[0].status == "deprecated"
        assert listed[0].deprecated_successor == "1.0.0"


class TestRatingEvidenceRef:
    async def test_rating_references_eval_event(self, store) -> None:
        """AC：评分引用评测事件而非复制数值——payload 只携带引用。"""
        await publish_scanned(store)
        run, seq = await seed_eval_event(store, 0.85)
        rating = await rate_plugin(
            store, "csv", "1.0.0", metric="success_rate",
            evidence_run=run, evidence_event_seq=seq,
            principal=publisher())
        assert rating.evidence_run == "evaluation"
        events = [e for e in store.iter_run_events("registry")
                  if e.type == "artifact.rated"]
        assert "score" not in events[-1].payload  # 不复制数值
        assert events[-1].payload["evidence_event_seq"] == seq

    async def test_aggregate_resolves_from_events(self, store) -> None:
        """聚合分值从被引事件解析（两条引用求均）。"""
        await publish_scanned(store)
        _, seq1 = await seed_eval_event(store, 0.8)
        _, seq2 = await seed_eval_event(store, 0.6)
        await rate_plugin(store, "csv", "1.0.0", metric="m",
                          evidence_run="evaluation", evidence_event_seq=seq1,
                          principal=publisher())
        await rate_plugin(store, "csv", "1.0.0", metric="m",
                          evidence_run="evaluation", evidence_event_seq=seq2,
                          principal=publisher())
        assert plugin_rating(store, "csv", tenant_id="t",
                             project_id="p") == pytest.approx(0.7)

    async def test_dangling_reference_rejected(self, store) -> None:
        """评分引用不存在的事件即拒（不可凭空捏造）。"""
        await publish_scanned(store)
        with pytest.raises(VastaError) as e:
            await rate_plugin(store, "csv", "1.0.0", metric="m",
                              evidence_run="evaluation",
                              evidence_event_seq=99,
                              principal=publisher())
        assert e.value.code == "discovery.bad_evidence_ref"

    async def test_rating_requires_registry_write(self, store) -> None:
        _, seq = await seed_eval_event(store, 0.9)
        rando = Principal(user="x", role=Role.VIEWER,
                          tenant_id="t", project_id="p")
        with pytest.raises(VastaError):
            await rate_plugin(store, "csv", "1.0.0", metric="m",
                              evidence_run="evaluation",
                              evidence_event_seq=seq, principal=rando)

    async def test_unrated_plugin_no_aggregate(self, store) -> None:
        assert plugin_rating(store, "csv", tenant_id="t",
                             project_id="p") is None
