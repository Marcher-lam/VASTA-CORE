"""Story 12.8：公开发现与评分（FR-084，G3）。"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer
from vasta_storage import SqliteStorage
from vastacore.ecosystem.discovery import (
    PluginRating,
    discover_plugins,
    plugin_rating,
    rate_plugin,
)
from vastacore.ecosystem.manifest import PluginManifest, sign_manifest
from vastacore.ecosystem.registry import register_plugin
from vastacore.ecosystem.revocation import deprecate_plugin, revoke_plugin
from vastacore.ecosystem.trust import satisfies, security_scan
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
        "tournament_id": "t-1", "winner": "csv",
        "ranking": [{"candidate": "csv", "failed": False,
                     "score": score}]})  # 候选名=plugin_id（生态约定）
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
        await publish_scanned(store, manifest(version="3.0.0"))
        await revoke_plugin(store, "csv", "1.0.0",
                            principal=publisher(), reason="security")
        await deprecate_plugin(store, "csv", "2.0.0",
                               principal=publisher(), successor="3.0.0")
        listed = discover_plugins(store, tenant_id="t", project_id="p")
        assert [p.version for p in listed] == ["2.0.0", "3.0.0"]
        deprecated = [p for p in listed if p.version == "2.0.0"][0]
        assert deprecated.status == "deprecated"
        assert deprecated.deprecated_successor == "3.0.0"


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


# ==================== Epic 12 评审修复回归 ====================

class TestVersionSemantics:
    """VER-1（盲审 M1/L5、边界 8-1/8-2）。"""

    def test_cross_precision_equality(self) -> None:
        """1.0.0 ≡ 1.0（右补零对齐——裸元组比较三问三错）。"""
        assert satisfies("1.0.0", "==1.0")
        assert satisfies("1.0", ">=1.0.0")
        assert satisfies("1.0.0", ">=1.0")

    def test_platform_version_prerelease_rejected(self) -> None:
        """非数字平台版本 → VastaError（此前裸 ValueError 逃逸）。"""
        with pytest.raises(VastaError) as e:
            satisfies("1.0.0-rc1", ">=1.0")
        assert e.value.code == "trust.bad_version"

    def test_boundary_equality_inclusive(self) -> None:
        """缺口 M26：恰界相等侧（>=/<= 含等）。"""
        assert satisfies("1.0.0", ">=1.0.0")
        assert satisfies("1.0.0", "<=1.0.0")
        assert satisfies("1.0.0", "==1.0.0")
        assert not satisfies("0.9.9", ">=1.0.0")

    async def test_discover_rejects_bad_platform_version(
            self, store) -> None:
        await publish_scanned(store)
        with pytest.raises(VastaError) as e:
            discover_plugins(store, platform_version="0.2.0-rc1",
                             tenant_id="t", project_id="p")
        assert e.value.code == "trust.bad_version"

    async def test_empty_platform_constraint_consistent(
            self, store) -> None:
        """L4：空/不可解析 platform 约束构造期拒——discover 与
        compatible_with 两面口径自然一致。"""
        with pytest.raises(VastaError) as e:
            manifest(compatibility={"platform": ""})
        assert e.value.code == "plugin.bad_platform_constraint"
        with pytest.raises(VastaError):
            manifest(compatibility={"platform": "任意文字"})


class TestRatingBinding:
    """RATE-1（盲审 M3、边界 9-1/9-3/9-5/9-6）。"""

    async def test_cannot_rate_with_foreign_evaluation(self, store) -> None:
        """M3：他者评测事件（候选 competitor-x）给本插件刷分 → 拒。"""
        await publish_scanned(store)
        seq = EventSequencer(store, "evaluation", tenant_id="t",
                             project_id="p")
        await seq.emit("evaluation.tournament_settled", {
            "tournament_id": "t-x", "winner": "competitor-x",
            "ranking": [{"candidate": "competitor-x", "failed": False,
                         "score": 0.99}]})
        settled = [e for e in store.iter_run_events("evaluation")
                   if e.type == "evaluation.tournament_settled"][-1]
        with pytest.raises(VastaError) as e:
            await rate_plugin(store, "csv", "1.0.0", metric="m",
                              evidence_run="evaluation",
                              evidence_event_seq=settled.seq,
                              principal=publisher())
        assert e.value.code == "discovery.evidence_not_about_plugin"

    async def test_poison_rating_rejected_at_write(self, store) -> None:
        """9-1：无可解析分值的 evaluation 事件 → 写入即拒（此前毒
        评分瘫痪聚合读取）。"""
        await publish_scanned(store)
        seq = EventSequencer(store, "evaluation", tenant_id="t",
                             project_id="p")
        await seq.emit("evaluation.tournament_started", {})
        started = [e for e in store.iter_run_events("evaluation")
                   if e.type == "evaluation.tournament_started"][-1]
        with pytest.raises(VastaError) as e:
            await rate_plugin(store, "csv", "1.0.0", metric="m",
                              evidence_run="evaluation",
                              evidence_event_seq=started.seq,
                              principal=publisher())
        assert e.value.code == "discovery.unresolvable_score"

    async def test_rating_replay_rejected(self, store) -> None:
        """9-5：同引用重放评分即拒（此前重复计数）。"""
        await publish_scanned(store)
        _, seq1 = await seed_eval_event(store, 0.8)
        await rate_plugin(store, "csv", "1.0.0", metric="m",
                          evidence_run="evaluation", evidence_event_seq=seq1,
                          principal=publisher())
        with pytest.raises(VastaError) as e:
            await rate_plugin(store, "csv", "1.0.0", metric="m",
                              evidence_run="evaluation",
                              evidence_event_seq=seq1,
                              principal=publisher())
        assert e.value.code == "discovery.duplicate_rating"

    async def test_unregistered_plugin_cannot_be_rated(
            self, store) -> None:
        """9-6：幽灵插件评分拒。"""
        _, seq = await seed_eval_event(store, 0.8)
        with pytest.raises(VastaError) as e:
            await rate_plugin(store, "ghost", "1.0.0", metric="m",
                              evidence_run="evaluation",
                              evidence_event_seq=seq,
                              principal=publisher())
        assert e.value.code == "discovery.plugin_not_active"

    async def test_multi_element_ranking_takes_first(self, store) -> None:
        """缺口 M29：多元素 ranking 取首位（末位是最差候选）。"""
        await publish_scanned(store)
        seq = EventSequencer(store, "evaluation", tenant_id="t",
                             project_id="p")
        await seq.emit("evaluation.tournament_settled", {
            "tournament_id": "t-multi", "winner": "csv",
            "ranking": [{"candidate": "csv", "failed": False,
                         "score": 0.9},
                        {"candidate": "other", "failed": False,
                         "score": 0.4}]})
        settled = [e for e in store.iter_run_events("evaluation")
                   if e.type == "evaluation.tournament_settled"][-1]
        await rate_plugin(store, "csv", "1.0.0", metric="m",
                          evidence_run="evaluation",
                          evidence_event_seq=settled.seq,
                          principal=publisher())
        assert plugin_rating(store, "csv", tenant_id="t",
                             project_id="p") == pytest.approx(0.9)

    async def test_version_scoped_rating(self, store) -> None:
        """9-4：版本级聚合（plugin 级均值口径明示）。"""
        await publish_scanned(store, manifest(version="1.0.0"))
        await publish_scanned(store, manifest(version="2.0.0"))
        _, seq1 = await seed_eval_event(store, 1.0)
        _, seq2 = await seed_eval_event(store, 0.0)
        await rate_plugin(store, "csv", "1.0.0", metric="m",
                          evidence_run="evaluation", evidence_event_seq=seq1,
                          principal=publisher())
        await rate_plugin(store, "csv", "2.0.0", metric="m",
                          evidence_run="evaluation", evidence_event_seq=seq2,
                          principal=publisher())
        assert plugin_rating(store, "csv", version="1.0.0",
                             tenant_id="t", project_id="p") == 1.0
        assert plugin_rating(store, "csv", version="2.0.0",
                             tenant_id="t", project_id="p") == 0.0


class TestResourcesFace:
    def test_empty_resources_rejected(self) -> None:
        """缺口 M19：plugin.missing_resources 可达面锚定。"""
        with pytest.raises(VastaError) as e:
            manifest(resources={})
        assert e.value.code == "plugin.missing_resources"

    def test_empty_permission_item_rejected(self) -> None:
        with pytest.raises(VastaError) as e:
            manifest(permissions=[""])
        assert e.value.code == "plugin.empty_permissions"


class TestRatingVisibility:
    """item-35：评分可见性机制（public/private 字段 + 聚合过滤）。"""

    async def test_private_rating_excluded_from_public_aggregate(
            self, store) -> None:
        await publish_scanned(store)
        _, seq1 = await seed_eval_event(store, 0.8)
        _, seq2 = await seed_eval_event(store, 0.4)
        await rate_plugin(store, "csv", "1.0.0", metric="m",
                          evidence_run="evaluation", evidence_event_seq=seq1,
                          principal=publisher())  # 缺省 public
        await rate_plugin(store, "csv", "1.0.0", metric="m",
                          evidence_run="evaluation", evidence_event_seq=seq2,
                          principal=publisher(), visibility="private")
        # 公开聚合面只计 public
        assert plugin_rating(store, "csv", tenant_id="t",
                             project_id="p") == pytest.approx(0.8)
        # 作用域内全量读（None = 不过滤）
        assert plugin_rating(store, "csv", visibility=None,
                             tenant_id="t", project_id="p") \
            == pytest.approx(0.6)
        # 事件携带机制字段
        events = [e for e in store.iter_run_events("registry")
                  if e.type == "artifact.rated"]
        assert events[-1].payload["visibility"] == "private"

    async def test_invalid_visibility_rejected(self, store) -> None:
        from pydantic import ValidationError

        await publish_scanned(store)
        _, seq = await seed_eval_event(store, 0.8)
        with pytest.raises(ValidationError):
            PluginRating(plugin_id="csv", version="1.0.0", metric="m",
                         evidence_run="evaluation", evidence_event_seq=seq,
                         rated_by="op", visibility="secret")
