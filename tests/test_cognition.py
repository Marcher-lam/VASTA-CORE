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

    def test_resolution_keeps_one(self) -> None:
        svc = ConflictService()
        claims = [
            make_claim("e1", scope={"topic": "t"}),
            make_claim("e2", scope={"topic": "t"}),
        ]
        conflict = svc.detect(claims, scope_key="topic")
        assert svc.resolve(conflict.conflict_id, keep="e1")
        with pytest.raises(VastaError):
            svc.resolve(conflict.conflict_id, keep="nonexistent")


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
