"""Epic 5：认知资产（Claim 生命周期/冲突/失效传播/上下文装配）。"""

from __future__ import annotations

import pytest

from vasta_cognition import (
    Claim,
    CognitionService,
    ConflictService,
    ContextBuilder,
)
from vasta_protocols.errors import VastaError

from .fakes import FakeStorageAdapter


def make_claim(claim_id: str, *, memory_type="hypothesis", **overrides) -> Claim:
    fields = dict(
        claim_id=claim_id,
        memory_type=memory_type,
        statement=f"statement-{claim_id}",
        evidence=["sha:abc123"],
        confidence=0.7,
    )
    fields.update(overrides)
    return Claim.model_validate(fields)


class TestClaimLifecycle:
    async def test_propose_to_accepted(self) -> None:
        store = FakeStorageAdapter()
        svc = CognitionService(store)
        await svc.propose(make_claim("c1"))
        assert svc.get("c1").status == "proposed"
        await svc.support("c1", ["sha:def456"])
        assert svc.get("c1").status == "supported"
        await svc.accept("c1")
        assert svc.get("c1").status == "accepted"  # 有证据才可 accepted

    async def test_no_evidence_cannot_accept(self) -> None:
        store = FakeStorageAdapter()
        svc = CognitionService(store)
        await svc.propose(make_claim("c2", evidence=[]))
        with pytest.raises(VastaError) as excinfo:
            await svc.accept("c2")
        assert excinfo.value.code == "claim.no_evidence"  # FR-021 后果

    async def test_refuted_not_deleted_with_impact_chain(self) -> None:
        store = FakeStorageAdapter()
        svc = CognitionService(store)
        await svc.propose(make_claim("c3"))
        await svc.refute("c3", ["sha:counter1"])
        claim = svc.get("c3")
        assert claim is not None
        assert claim.status == "refuted"  # 不删除
        assert "sha:counter1" in claim.counterevidence  # 影响链保留
        # 事件留痕
        types = [e.type for e in store.iter_run_events("cognition")]
        assert "claim.proposed" in types and "claim.refuted" in types

    async def test_projection_rebuild_from_events(self) -> None:
        """AD-2：投影从事件流重建（新实例恢复同一状态）。"""
        store = FakeStorageAdapter()
        svc1 = CognitionService(store)
        await svc1.propose(make_claim("c4"))
        await svc1.support("c4", ["sha:x"])
        await svc1.accept("c4")
        svc2 = CognitionService(store)  # 重建
        assert svc2.get("c4").status == "accepted"


class TestConflict:
    def test_mutex_claims_create_conflict(self) -> None:
        svc = ConflictService()
        claims = [
            make_claim("a1", memory_type="guide",
                       scope={"topic": "border-color"},
                       statement="蓝色边框=选中"),
            make_claim("a2", memory_type="guide",
                       scope={"topic": "border-color"},
                       statement="蓝色边框=只读标记"),
        ]
        conflict = svc.detect(claims, scope_key="topic")
        assert conflict is not None
        assert set(conflict.claim_ids) == {"a1", "a2"}  # 显式冲突不静默

    def test_different_scopes_no_conflict(self) -> None:
        svc = ConflictService()
        claims = [
            make_claim("b1", scope={"topic": "x"}),
            make_claim("b2", scope={"topic": "y"}),
        ]
        assert svc.detect(claims, scope_key="topic") is None

    def test_refuted_excluded_from_conflict(self) -> None:
        svc = ConflictService()
        claims = [
            make_claim("d1", scope={"topic": "z"}),
            make_claim("d2", scope={"topic": "z"}, counterevidence=["x"]),
        ]
        claims[1].status = "refuted"  # 已推翻不参与
        assert svc.detect(claims, scope_key="topic") is None

    async def test_resolution_keeps_one(self) -> None:
        svc = ConflictService()
        claims = [
            make_claim("e1", scope={"topic": "t"}),
            make_claim("e2", scope={"topic": "t"}),
        ]
        conflict = svc.detect(claims, scope_key="topic")
        resolved = await svc.resolve(conflict.conflict_id, keep="e1")
        assert resolved.resolved and resolved.kept == "e1"
        with pytest.raises(VastaError):
            await svc.resolve(conflict.conflict_id, keep="nonexistent")
        # 评审修复守卫：已解决的冲突不可重复解决
        with pytest.raises(VastaError):
            await svc.resolve(conflict.conflict_id, keep="e2")

    def test_detect_idempotent_same_set(self) -> None:
        """评审修复守卫：同一主张集合不重复建冲突。"""
        svc = ConflictService()
        claims = [
            make_claim("i1", scope={"topic": "k"}),
            make_claim("i2", scope={"topic": "k"}),
        ]
        first = svc.detect(claims, scope_key="topic")
        assert first is not None
        assert svc.detect(claims, scope_key="topic") is None  # 幂等

    async def test_detect_default_groups_by_full_scope(self) -> None:
        """评审修复守卫：默认按完整 scope 分组（原 statement 键永不分组）。"""
        svc = ConflictService()
        claims = [
            make_claim("j1", scope={"topic": "m", "page": "home"}),
            make_claim("j2", scope={"topic": "m", "page": "home"}),
        ]
        assert svc.detect(claims) is not None
        empty_scoped = [make_claim("j3"), make_claim("j4")]
        assert svc.detect(empty_scoped) is None  # 未声明范围不参与互斥


class TestInvalidationPropagation:
    async def test_dependent_claims_cascade(self) -> None:
        """Story 5.3：依赖主张失效 → 受影响主张级联标记。"""
        store = FakeStorageAdapter()
        svc = CognitionService(store)
        await svc.propose(make_claim("root"))
        await svc.propose(make_claim("mid", depends_on=["root"]))
        await svc.propose(make_claim("leaf", depends_on=["mid"]))
        await svc.propose(make_claim("independent"))

        affected = await svc.refute("root", ["sha:counter"])
        assert set(affected) == {"mid", "leaf"}  # 级联
        assert svc.get("independent").status == "proposed"  # 无关不受影响
        assert svc.get("leaf").status == "refuted"


class TestContextBuilder:
    def test_budget_assembly_traceable(self) -> None:
        claims = [
            make_claim("p1", memory_type="policy", statement="禁止超阈值",
                       confidence=0.9),
            make_claim("g1", memory_type="guide", statement="页面导航规则"),
            make_claim("h1", memory_type="hypothesis", statement="蓝框=选中"),
            make_claim("w1", memory_type="working", statement="当前页面"),
        ]
        claims[0].status = "accepted"
        bundle = ContextBuilder.assemble(
            goal="核验订单", claims=claims, budget=2
        )
        assert len(bundle.selections) == 2  # 预算内
        assert all(s.reason for s in bundle.selections)  # 依据可追溯
        assert len(bundle.pruned) == 2  # 被裁剪显式列出（不静默截断）
        # 优先级：policy > guide
        assert bundle.selections[0].claim_id == "p1"
        assert bundle.selections[1].claim_id == "g1"

    def test_refuted_excluded(self) -> None:
        claims = [make_claim("r1")]
        claims[0].status = "refuted"
        bundle = ContextBuilder.assemble(goal="g", claims=claims, budget=5)
        assert bundle.selections == []  # 被推翻的不入上下文

    def test_policy_readonly_to_agent(self) -> None:
        """Policy 类对 Agent 只读——由 memory_type 语义保证（写入需人/控制面）。"""
        claims = [make_claim("pol1", memory_type="policy")]
        bundle = ContextBuilder.assemble(goal="g", claims=claims, budget=1)
        assert bundle.selections[0].claim_id == "pol1"  # 可读


class TestReviewGuards:
    """Epic 4-7 code-review 修复的守卫（存在性/终态/重复/版本/穿透/seq 同步）。"""

    async def test_ops_on_unknown_claim_rejected(self) -> None:
        """support/dispute/refute/retire 对不存在主张必须拒绝（原静默发事件）。"""
        svc = CognitionService(FakeStorageAdapter())
        for call in (
            lambda: svc.support("ghost", ["sha:x"]),
            lambda: svc.dispute("ghost", ["sha:x"]),
            lambda: svc.refute("ghost", ["sha:x"]),
            lambda: svc.retire("ghost"),
        ):
            with pytest.raises(VastaError) as excinfo:
                await call()
            assert excinfo.value.code == "claim.not_found"

    async def test_terminal_claim_cannot_revive(self) -> None:
        """终态主张不可再迁移（原实现可复活已推翻主张）。"""
        svc = CognitionService(FakeStorageAdapter())
        await svc.propose(make_claim("t1"))
        await svc.refute("t1", ["sha:c"])
        with pytest.raises(VastaError) as excinfo:
            await svc.accept("t1")
        assert excinfo.value.code == "claim.terminal"
        with pytest.raises(VastaError):
            await svc.refute("t1", ["sha:c2"])  # 重复 refute 也拒绝
        await svc.propose(make_claim("t2"))
        await svc.retire("t2")
        with pytest.raises(VastaError):
            await svc.support("t2", ["sha:x"])

    async def test_duplicate_propose_rejected(self) -> None:
        svc = CognitionService(FakeStorageAdapter())
        await svc.propose(make_claim("dup"))
        with pytest.raises(VastaError) as excinfo:
            await svc.propose(make_claim("dup"))
        assert excinfo.value.code == "claim.duplicate"

    async def test_version_increments_on_transitions(self) -> None:
        """FR-021：状态迁移版本化。"""
        svc = CognitionService(FakeStorageAdapter())
        await svc.propose(make_claim("v1"))
        assert svc.get("v1").version == 1
        await svc.support("v1", ["sha:a"])
        assert svc.get("v1").version == 2
        await svc.accept("v1")
        assert svc.get("v1").version == 3

    async def test_cascade_penetrates_refuted_intermediate(self) -> None:
        """评审实锤：A←B(已推翻)←C——C 在 B 推翻后才提出，推翻 A 时 C
        仍须失效（穿透已终态的 B；原实现跳过终态节点导致漏传播）。"""
        svc = CognitionService(FakeStorageAdapter())
        await svc.propose(make_claim("A"))
        await svc.propose(make_claim("B", depends_on=["A"]))
        await svc.refute("B", ["sha:x"])  # B 终态（当时无下游）
        await svc.propose(make_claim("C", depends_on=["B"]))  # 依赖已推翻主张
        affected = await svc.refute("A", ["sha:y"])
        assert "C" in affected
        assert svc.get("C").status == "refuted"

    async def test_cascade_cycle_safe(self) -> None:
        """依赖环不导致死循环。"""
        svc = CognitionService(FakeStorageAdapter())
        await svc.propose(make_claim("x", depends_on=["y"]))
        await svc.propose(make_claim("y", depends_on=["x"]))
        affected = await svc.refute("x", ["sha:z"])
        assert svc.get("y").status == "refuted"
        assert affected == ["y"]

    async def test_seq_syncs_with_bridge_writes(self) -> None:
        """评审实锤：桥接（AD-13）写 cognition run 后服务再写不撞 seq。"""
        from vasta_model_lab._bookkeeping_stub import emit_world_model_event

        store = FakeStorageAdapter()
        svc = CognitionService(store)
        await svc.propose(make_claim("s1"))
        await emit_world_model_event(store, "world_model.suspended", {"name": "m"})
        # 修复前：这里 DuplicateEventError（内存 seq 与存储脱节）
        await svc.support("s1", ["sha:b"])
        seqs = [e.seq for e in store.iter_run_events("cognition")]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

    async def test_propose_auto_detects_conflict_event(self) -> None:
        """同范围第二条主张 → claim.conflict_detected 事件（带触发者）。
        新主张加入同范围是新增事实，允许再报一次但须引用新触发者；
        同一成员集合不重复（ConflictService.detect 幂等性单测覆盖）。"""
        store = FakeStorageAdapter()
        svc = CognitionService(store)
        await svc.propose(make_claim("k1", scope={"topic": "z"}))
        await svc.propose(make_claim("k2", scope={"topic": "z"}))
        detected = [
            e for e in store.iter_run_events("cognition")
            if e.type == "claim.conflict_detected"
        ]
        assert len(detected) == 1
        assert detected[0].payload["triggered_by"] == "k2"
        assert set(detected[0].payload["claim_ids"]) == {"k1", "k2"}

    async def test_resolve_emits_event_when_store_attached(self) -> None:
        store = FakeStorageAdapter()
        svc = ConflictService(store)
        svc.detect(
            [make_claim("m1", scope={"topic": "q"}),
             make_claim("m2", scope={"topic": "q"})],
            scope_key="topic",
        )
        await svc.resolve("conflict-1", keep="m1")
        types = [e.type for e in store.iter_run_events("cognition")]
        assert "claim.conflict_resolved" in types

    def test_context_reason_carries_relevance_and_risk(self) -> None:
        """FR-025：reason 含相关性与风险数值；排序受 goal 影响。"""
        claims = [
            make_claim("rel1", memory_type="guide",
                       statement="核验 订单 需要 蓝框"),
            make_claim("rel2", memory_type="guide",
                       statement="天气 与 主题 无关"),
            make_claim("rel3", memory_type="guide",
                       statement="核验 需要 时间 截止",
                       counterevidence=["sha:ce1"]),
        ]
        bundle = ContextBuilder.assemble(goal="核验 订单", claims=claims, budget=3)
        by_id = {s.claim_id: s for s in bundle.selections}
        assert "relevance=" in by_id["rel1"].reason and "risk=" in by_id["rel1"].reason
        # 目标词重合者相关性更高
        assert by_id["rel1"].relevance > by_id["rel2"].relevance
        # 风险参与排序键（rel3 有反证 → risk=1）
        assert by_id["rel3"].risk == 1
