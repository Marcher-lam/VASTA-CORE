"""Working Memory 私有与显式发布（Story 11.4，FR-051，G1）。

Agent 间知识流动是授权动作不是默认泄漏：

- **默认私有**：每个 Agent 的主张/记忆落在私有作用域
  （``agent:{agent_id}`` 项目槽）——其他 Agent 的 CognitionService
  投影不包含；
- **显式发布**（publish_knowledge）：已验证（accepted）主张从私有
  槽发布到目标作用域（项目/组织）——``claim.published_knowledge``
  留痕（发布链可溯）；未验证主张拒发布（FR-051 字面）；
- **撤销发布**（unpublish_knowledge）：回收跨 Agent 可见性——
  留痕；目标作用域的已发布副本移除。
"""

from __future__ import annotations

from typing import Any

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

_MEMORY_RUN = "memory"


def private_project(agent_id: str) -> str:
    """Agent 私有项目槽（作用域隔离——其他 Agent 投影不含）。"""
    return f"agent:{agent_id}"


async def publish_knowledge(
    store: Any, claim_id: str, *, agent_id: str,
    target_project: str,
    tenant_id: str = "t-default",
) -> dict[str, Any]:
    """显式发布：已验证主张从私有槽发布到目标作用域。

    返回发布副本（目标作用域的重发布事件 payload）。未验证（非
    accepted）拒——FR-051「已验证知识显式发布共享」。"""
    from vasta_cognition.cognition import CognitionService

    private = CognitionService(
        store, tenant_id=tenant_id, project_id=private_project(agent_id))
    claim = private.get(claim_id)
    if claim is None:
        raise VastaError(
            code="knowledge.claim_not_found",
            message=f"主张 {claim_id!r} 不在 Agent {agent_id!r} 私有记忆",
        )
    if claim.status != "accepted":
        raise VastaError(
            code="knowledge.not_verified",
            message=(f"主张 {claim_id!r} 状态 {claim.status!r}——仅 "
                     "accepted 可发布（FR-051 已验证知识）"),
        )
    # 目标作用域重发布（claim.proposed + 直接收敛到 accepted——
    # 来源标记 agent）
    target = CognitionService(
        store, tenant_id=tenant_id, project_id=target_project)
    if target.get(claim_id) is None:
        from vasta_cognition.cognition import Claim
        await target.propose(Claim(
            claim_id=claim_id, memory_type=claim.memory_type,
            statement=claim.statement, scope=claim.scope,
            evidence=claim.evidence, confidence=claim.confidence,
        ))
        await target.support(claim_id, claim.evidence)
        await target.accept(claim_id)
    sequencer = EventSequencer(store, _MEMORY_RUN, tenant_id=tenant_id,
                               project_id=target_project)
    await sequencer.emit("claim.published_knowledge", {
        "claim_id": claim_id, "from_agent": agent_id,
        "target_project": target_project,
    })
    return {"claim_id": claim_id, "target_project": target_project}


async def unpublish_knowledge(
    store: Any, claim_id: str, *, agent_id: str,
    target_project: str,
    tenant_id: str = "t-default",
) -> None:
    """撤销发布：目标作用域副本收回 + 留痕。"""
    from vasta_cognition.cognition import CognitionService

    target = CognitionService(
        store, tenant_id=tenant_id, project_id=target_project)
    if target.get(claim_id) is not None:
        await target.retire(claim_id)  # 收回可见性（终态不可复活）
    sequencer = EventSequencer(store, _MEMORY_RUN, tenant_id=tenant_id,
                               project_id=target_project)
    await sequencer.emit("claim.published_knowledge_revoked", {
        "claim_id": claim_id, "by_agent": agent_id,
        "target_project": target_project,
    })


__all__ = ["private_project", "publish_knowledge",
           "unpublish_knowledge"]
