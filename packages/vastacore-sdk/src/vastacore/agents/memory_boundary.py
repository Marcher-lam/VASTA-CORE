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

Epic 11 评审修复（盲审 M3、边界 M-2/M-3/M-4/M-5）：

- 发布/撤销是**授权动作**：两函数均要求 ``principal``（RBAC
  cognition write——原先任意调用者可撤他人发布）；
- 私有槽（``agent:`` 前缀）不是合法发布目标（写穿他人私有面拒）；
- 目标同 ID 撞号**不静默**：内容一致 → 幂等；内容分歧 → 拒
  （防错误归属与两条记忆分叉）；目标副本已 retired → 拒并指引
  以 revised ID 重发（撤销后原 ID 在该作用域已消费——原先
  「事件说已发布、投影仍 retired」的假成功根治）。
"""

from __future__ import annotations

from typing import Any

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

from ..governance.rbac import Principal, evaluate_access

_MEMORY_RUN = "memory"


def private_project(agent_id: str) -> str:
    """Agent 私有项目槽（作用域隔离——其他 Agent 投影不含）。"""
    return f"agent:{agent_id}"


def _require_publish_principal(principal: Principal, *,
                               tenant_id: str,
                               target_project: str) -> None:
    """发布/撤销授权：cognition write on 目标作用域（fail-closed）。"""
    decision = evaluate_access(
        principal, "cognition", "write",
        tenant_id=tenant_id, project_id=target_project)
    if not decision.allowed:
        raise VastaError(
            code="access.denied",
            message=(f"知识发布/撤销需目标作用域 cognition write"
                     f"（{decision.reason}）"),
        )


async def publish_knowledge(
    store: Any, claim_id: str, *, agent_id: str,
    target_project: str,
    tenant_id: str = "t-default",
    principal: Principal | None = None,
) -> dict[str, Any]:
    """显式发布：已验证主张从私有槽发布到目标作用域。

    返回发布副本（目标作用域的重发布事件 payload）。未验证（非
    accepted）拒——FR-051「已验证知识显式发布共享」。

    授权：principal（cognition write on 目标作用域）必填。
    撞号：目标同 ID 内容一致幂等；分歧拒；已 retired 拒（以
    revised ID 重发）。"""
    from vasta_cognition.cognition import CognitionService

    if principal is None:
        raise VastaError(
            code="access.denied",
            message="知识发布需授权主体（principal 必填——fail-closed）",
        )
    if target_project.startswith("agent:"):
        raise VastaError(
            code="knowledge.private_target",
            message=(f"目标作用域 {target_project!r} 是私有槽"
                     "——私有作用域不是合法发布目标"),
        )
    _require_publish_principal(principal, tenant_id=tenant_id,
                               target_project=target_project)
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
    target = CognitionService(
        store, tenant_id=tenant_id, project_id=target_project)
    existing = target.get(claim_id)
    if existing is None:
        # 目标作用域重发布（claim.proposed + 直接收敛到 accepted——
        # 来源标记 agent）
        from vasta_cognition.cognition import Claim
        await target.propose(Claim(
            claim_id=claim_id, memory_type=claim.memory_type,
            statement=claim.statement, scope=claim.scope,
            evidence=claim.evidence, confidence=claim.confidence,
        ))
        await target.support(claim_id, claim.evidence)
        await target.accept(claim_id)
    elif existing.status in ("retired", "refuted"):
        raise VastaError(
            code="knowledge.target_claim_retired",
            message=(f"主张 {claim_id!r} 在目标作用域已 {existing.status}"
                     "（撤销即消费——重发布须以 revised ID 发新主张，"
                     "原 ID 不可复活）"),
        )
    elif existing.statement != claim.statement:
        raise VastaError(
            code="knowledge.claim_collision",
            message=(f"主张 {claim_id!r} 在目标作用域已存在且内容分歧"
                     "（{existing.statement!r} vs {claim.statement!r}）"
                     "——不可覆盖归属，须走 revised 流程"),
        )
    # 内容一致：幂等（不重复 propose——claim.duplicate 语义由
    # cognition 保证，此处显式跳过）
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
    principal: Principal | None = None,
) -> None:
    """撤销发布：目标作用域副本收回 + 留痕。

    授权：principal（cognition write on 目标作用域）必填——撤销是
    治理动作，任意调用者不可撤他人发布。"""
    from vasta_cognition.cognition import CognitionService

    if principal is None:
        raise VastaError(
            code="access.denied",
            message="知识撤销需授权主体（principal 必填——fail-closed）",
        )
    _require_publish_principal(principal, tenant_id=tenant_id,
                               target_project=target_project)
    target = CognitionService(
        store, tenant_id=tenant_id, project_id=target_project)
    existing = target.get(claim_id)
    if existing is not None and existing.status not in ("retired",
                                                        "refuted"):
        await target.retire(claim_id)  # 收回可见性（终态不可复活）
    sequencer = EventSequencer(store, _MEMORY_RUN, tenant_id=tenant_id,
                               project_id=target_project)
    await sequencer.emit("claim.published_knowledge_revoked", {
        "claim_id": claim_id, "by_agent": agent_id,
        "target_project": target_project,
    })


__all__ = ["private_project", "publish_knowledge",
           "unpublish_knowledge"]
