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


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


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
    async def test_accepted_publishes_to_target(self, store) -> None:
        """AC：已验证知识显式发布共享。"""
        await seed_accepted(store)
        await publish_knowledge(store, "c1", agent_id="agent-a",
                                target_project="p-shared", tenant_id="t")
        shared = CognitionService(store, tenant_id="t",
                                  project_id="p-shared")
        assert shared.get("c1") is not None
        assert shared.get("c1").status == "accepted"
        events = [e for e in store.iter_run_events(
            "memory", tenant_id="t", project_id="p-shared")
            if e.type == "claim.published_knowledge"]
        assert events[-1].payload["from_agent"] == "agent-a"

    async def test_unverified_rejected(self, store) -> None:
        cog = CognitionService(store, tenant_id="t",
                               project_id=private_project("agent-a"))
        await cog.propose(Claim(claim_id="c2", memory_type="working",
                                statement="草稿", evidence=[]))
        with pytest.raises(VastaError) as e:
            await publish_knowledge(store, "c2", agent_id="agent-a",
                                    target_project="p-shared",
                                    tenant_id="t")
        assert e.value.code == "knowledge.not_verified"

    async def test_unknown_claim_rejected(self, store) -> None:
        with pytest.raises(VastaError) as e:
            await publish_knowledge(store, "ghost", agent_id="agent-a",
                                    target_project="p-shared",
                                    tenant_id="t")
        assert e.value.code == "knowledge.claim_not_found"


class TestUnpublish:
    async def test_revoke_restores_privacy(self, store) -> None:
        await seed_accepted(store)
        await publish_knowledge(store, "c1", agent_id="agent-a",
                                target_project="p-shared", tenant_id="t")
        await unpublish_knowledge(store, "c1", agent_id="agent-a",
                                  target_project="p-shared", tenant_id="t")
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
