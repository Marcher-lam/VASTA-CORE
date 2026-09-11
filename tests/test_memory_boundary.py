"""Story 11.4：Working Memory 私有与显式发布（FR-051，G1）。"""

from __future__ import annotations

import pytest

from vasta_cognition.cognition import Claim, CognitionService
from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.agents.memory_boundary import (
    private_project,
    publish_knowledge,
    unpublish_knowledge,
)
from vastacore.governance.rbac import Principal, Role


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


@pytest.fixture
def publisher() -> Principal:
    """目标作用域 cognition write 主体（operator）。"""
    return Principal(user="agent-a-op", role=Role.OPERATOR,
                     tenant_id="t", project_id="p-shared")


@pytest.fixture
def foreign_principal() -> Principal:
    """异作用域主体（不可写 p-shared）。"""
    return Principal(user="attacker", role=Role.OPERATOR,
                     tenant_id="t", project_id="agent:agent-b")


async def seed_accepted(store, agent="agent-a", cid="c1") -> None:
    cog = CognitionService(store, tenant_id="t",
                           project_id=private_project(agent))
    await cog.propose(Claim(claim_id=cid, memory_type="hypothesis",
                            statement="风机制假说",
                            evidence=["run:1"]))
    await cog.support(cid, ["run:1"])
    await cog.accept(cid)


class TestPrivacy:
    async def test_private_by_default(self, store) -> None:
        """AC：默认私有——其他 Agent 投影不含私有主张。"""
        await seed_accepted(store)
        other = CognitionService(store, tenant_id="t",
                                 project_id=private_project("agent-b"))
        assert other.get("c1") is None
        shared = CognitionService(store, tenant_id="t",
                                  project_id="p-shared")
        assert shared.get("c1") is None


class TestPublish:
    async def test_accepted_publishes_to_target(self, store,
                                               publisher) -> None:
        """AC：已验证知识显式发布共享。"""
        await seed_accepted(store)
        await publish_knowledge(store, "c1", agent_id="agent-a",
                                target_project="p-shared", tenant_id="t",
                                principal=publisher)
        shared = CognitionService(store, tenant_id="t",
                                  project_id="p-shared")
        assert shared.get("c1") is not None
        assert shared.get("c1").status == "accepted"
        events = [e for e in store.iter_run_events(
            "memory", tenant_id="t", project_id="p-shared")
            if e.type == "claim.published_knowledge"]
        assert events[-1].payload["from_agent"] == "agent-a"

    async def test_unverified_rejected(self, store,
                                       publisher) -> None:
        cog = CognitionService(store, tenant_id="t",
                               project_id=private_project("agent-a"))
        await cog.propose(Claim(claim_id="c2", memory_type="working",
                                statement="草稿", evidence=[]))
        with pytest.raises(VastaError) as e:
            await publish_knowledge(store, "c2", agent_id="agent-a",
                                    target_project="p-shared",
                                    tenant_id="t",
                                    principal=publisher)
        assert e.value.code == "knowledge.not_verified"

    async def test_unknown_claim_rejected(self, store,
                                          publisher) -> None:
        with pytest.raises(VastaError) as e:
            await publish_knowledge(store, "ghost", agent_id="agent-a",
                                    target_project="p-shared",
                                    tenant_id="t",
                                    principal=publisher)
        assert e.value.code == "knowledge.claim_not_found"


class TestUnpublish:
    async def test_revoke_restores_privacy(self, store,
                                           publisher) -> None:
        await seed_accepted(store)
        await publish_knowledge(store, "c1", agent_id="agent-a",
                                target_project="p-shared", tenant_id="t",
                                principal=publisher)
        await unpublish_knowledge(store, "c1", agent_id="agent-a",
                                  target_project="p-shared", tenant_id="t",
                                  principal=publisher)
        shared = CognitionService(store, tenant_id="t",
                                  project_id="p-shared")
        assert shared.get("c1").status == "retired"  # 收回可见性
        events = [e for e in store.iter_run_events(
            "memory", tenant_id="t", project_id="p-shared")
            if e.type == "claim.published_knowledge_revoked"]
        assert events[-1].payload["claim_id"] == "c1"
        # 私有原件不受影响
        private = CognitionService(store, tenant_id="t",
                                   project_id=private_project("agent-a"))
        assert private.get("c1").status == "accepted"


class TestReviewRegressions:
    """Epic 11 评审修复回归（盲审 M3、边界 M-1/M-2/M-3/M-4/M-5）。"""

    async def test_publish_without_principal_rejected(self, store) -> None:
        """M3.1：发布是授权动作——无 principal 即拒（fail-closed）。"""
        await seed_accepted(store)
        with pytest.raises(VastaError) as e:
            await publish_knowledge(store, "c1", agent_id="agent-a",
                                    target_project="p-shared",
                                    tenant_id="t")
        assert e.value.code == "access.denied"

    async def test_publish_foreign_principal_rejected(self, store,
                                                      publisher,
                                                      foreign_principal
                                                      ) -> None:
        """M3.1：异作用域主体不可发布。"""
        await seed_accepted(store)
        with pytest.raises(VastaError) as e:
            await publish_knowledge(store, "c1", agent_id="agent-a",
                                    target_project="p-shared",
                                    tenant_id="t",
                                    principal=foreign_principal)
        assert e.value.code == "access.denied"

    async def test_unpublish_attacker_rejected(self, store,
                                               publisher) -> None:
        """M3.1/M-3：任意 agent_id 不可撤他人发布——RBAC 拦截。"""
        await seed_accepted(store)
        await publish_knowledge(store, "c1", agent_id="agent-a",
                                target_project="p-shared", tenant_id="t",
                                principal=publisher)
        attacker = Principal(user="attacker", role=Role.OPERATOR,
                             tenant_id="t", project_id="agent:agent-b")
        with pytest.raises(VastaError) as e:
            await unpublish_knowledge(store, "c1", agent_id="attacker",
                                      target_project="p-shared",
                                      tenant_id="t", principal=attacker)
        assert e.value.code == "access.denied"
        # 目标副本未被撤
        shared = CognitionService(store, tenant_id="t",
                                  project_id="p-shared")
        assert shared.get("c1").status == "accepted"

    async def test_publish_to_private_slot_rejected(self, store,
                                                    publisher) -> None:
        """M-2/M-5：私有槽（agent: 前缀）不是合法发布目标。"""
        await seed_accepted(store)
        with pytest.raises(VastaError) as e:
            await publish_knowledge(store, "c1", agent_id="agent-a",
                                    target_project="agent:agent-b",
                                    tenant_id="t", principal=publisher)
        assert e.value.code == "knowledge.private_target"

    async def test_collision_same_content_idempotent(self, store,
                                                     publisher) -> None:
        """M-4：同 ID 同内容重复发布幂等（不重复 propose）。"""
        await seed_accepted(store)
        first = await publish_knowledge(store, "c1", agent_id="agent-a",
                                        target_project="p-shared",
                                        tenant_id="t",
                                        principal=publisher)
        second = await publish_knowledge(store, "c1", agent_id="agent-a",
                                         target_project="p-shared",
                                         tenant_id="t",
                                         principal=publisher)
        assert first == second
        shared = CognitionService(store, tenant_id="t",
                                  project_id="p-shared")
        assert shared.get("c1").status == "accepted"

    async def test_collision_content_mismatch_rejected(self, store,
                                                       publisher) -> None:
        """M-4：同 ID 不同内容——错误归属拒（不再静默跳过+假事件）。"""
        # 先在目标作用域放一条同 ID 不同内容的已接受主张
        shared = CognitionService(store, tenant_id="t",
                                  project_id="p-shared")
        await shared.propose(Claim(claim_id="c1",
                                   memory_type="hypothesis",
                                   statement="完全不同的主张",
                                   evidence=["run:9"]))
        await shared.support("c1", ["run:9"])
        await shared.accept("c1")
        await seed_accepted(store)
        with pytest.raises(VastaError) as err:
            await publish_knowledge(store, "c1", agent_id="agent-a",
                                    target_project="p-shared",
                                    tenant_id="t", principal=publisher)
        assert err.value.code == "knowledge.claim_collision"
        assert shared.get("c1").statement == "完全不同的主张"

    async def test_republish_after_unpublish_rejected_honestly(
            self, store, publisher) -> None:
        """M3.3/M-1：撤销后再发布——原 ID 已消费，诚实拒（原先
        假成功：事件说已发布、投影仍 retired）。"""
        await seed_accepted(store)
        await publish_knowledge(store, "c1", agent_id="agent-a",
                                target_project="p-shared", tenant_id="t",
                                principal=publisher)
        await unpublish_knowledge(store, "c1", agent_id="agent-a",
                                  target_project="p-shared", tenant_id="t",
                                  principal=publisher)
        with pytest.raises(VastaError) as err:
            await publish_knowledge(store, "c1", agent_id="agent-a",
                                    target_project="p-shared",
                                    tenant_id="t", principal=publisher)
        assert err.value.code == "knowledge.target_claim_retired"
        events = [ev for ev in store.iter_run_events(
            "memory", tenant_id="t", project_id="p-shared")
            if ev.type == "claim.published_knowledge"]
        # 事件链不出现第二条 published（无假成功）
        assert len(events) == 1
