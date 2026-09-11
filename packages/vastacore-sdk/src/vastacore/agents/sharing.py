"""跨 Agent/项目/组织共享边界（Story 11.6，FR-027，G2）。

知识资产离开产生它的边界是授权动作：

- **共享三态**：private（默认）/ project（项目内共享）/
  organization（组织内共享）；
- **share_asset**：发布方授权 → 目标可见性变更留痕
  （``claim.shared`` 或 ``artifact.shared``——按资产类型）；
  **跨组织共享需双边授权**（发布方 grant + 接收方 accept——
  单边即 pending 态，未授权读取拒）；
- **check_shared_access**：读取方按（发布方组织, 接收方组织,
  可见性）评估——未授权拒（``access.denied`` 语义 + 留痕）；
- **unshare**：撤销共享（可见性回 private + 留痕）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vastacore.governance.rbac import Principal, evaluate_access

_SHARING_RUN = "sharing"


class Visibility(StrEnum):
    PRIVATE = "private"
    PROJECT = "project"
    ORGANIZATION = "organization"


class ShareGrant(BaseModel):
    """共享授权（资产 + 可见性 + 发布方）。"""

    model_config = ConfigDict(extra="forbid")

    asset_ref: str = Field(description="资产引用（claim_id 或 sha256）")
    asset_kind: str = Field(pattern="^(claim|artifact)$")
    visibility: Visibility
    publisher_org: str = Field(description="发布方组织（租户）")
    publisher_agent: str = Field(min_length=1)
    tenant_id: str = "t-default"
    project_id: str = "p-default"


class ShareAcceptance(BaseModel):
    """接收方授权（跨组织共享的第二边）。"""

    model_config = ConfigDict(extra="forbid")

    asset_ref: str
    accepting_org: str
    accepted_by: str


async def share_asset(
    store: Any, grant: ShareGrant,
    *, acceptance: ShareAcceptance | None = None,
) -> dict[str, Any]:
    """发布共享：同组织直发；跨组织需 acceptance（双边）。

    返回共享状态（active/pending bilateral）。PRIVATE 资产无可共享
    面（语义矛盾拒——评审修复 S-3）；acceptance 的资产引用须与
    grant 一致（他资产的接受不可激活本资产——S-2）。"""
    from vasta_protocols.sequencer import EventSequencer

    if grant.visibility is Visibility.PRIVATE:
        raise VastaError(
            code="sharing.private_not_shareable",
            message=(f"资产 {grant.asset_ref!r} 为 private——私有资产"
                     "无可共享面（先变更可见性语义）"),
        )
    if acceptance is not None             and acceptance.asset_ref != grant.asset_ref:
        raise VastaError(
            code="sharing.acceptance_mismatch",
            message=(f"接受引用资产 {acceptance.asset_ref!r} 与共享资产 "
                     f"{grant.asset_ref!r} 不符——B 资产的接受不可激活 "
                     "A 资产的跨组织共享"),
        )
    # 组织级共享：接收方已接受（他组织）→ active；否则 pending
    state = "active"
    if grant.visibility is Visibility.ORGANIZATION \
            and _needs_bilateral(grant, acceptance):
        state = "pending_bilateral"
    sequencer = EventSequencer(
        store, _SHARING_RUN,
        tenant_id=grant.tenant_id, project_id=grant.project_id)
    await sequencer.emit("claim.shared" if grant.asset_kind == "claim"
                         else "artifact.shared", {
        "asset_ref": grant.asset_ref,
        "visibility": grant.visibility.value,
        "publisher_org": grant.publisher_org,
        "publisher_agent": grant.publisher_agent,
        **({"accepting_org": acceptance.accepting_org,
            "accepted_by": acceptance.accepted_by}
           if acceptance is not None else {}),
        "state": state,
    })
    return {"asset_ref": grant.asset_ref, "state": state}


def _needs_bilateral(grant: ShareGrant,
                     acceptance: ShareAcceptance | None) -> bool:
    """双边是否**未完成**：组织级共享且尚无他组织的接受——
    无 acceptance 或 acceptance 来自发布组织自身 → True（pending）；
    他组织 acceptance 已给 → False（双边完成，active）。"""
    if acceptance is None:
        return True
    return acceptance.accepting_org == grant.publisher_org


def check_shared_access(
    store: Any | None, grant: ShareGrant, *,
    reader: Principal, reader_org: str,
    accepted_orgs: set[str] | None = None,
) -> None:
    """读取方共享访问校验（fail-closed）：

    - project 可见性：同租户+项目（RBAC evaluate_access）；
    - organization 可见性：同组织 或 接收方已接受（accepted_orgs）；
    - 未授权拒（access.denied 留痕由调用方接）。"""
    if grant.visibility is Visibility.PRIVATE:
        raise VastaError(
            code="access.denied",
            message=f"资产 {grant.asset_ref!r} 私有（未共享）",
        )
    if grant.visibility is Visibility.PROJECT:
        decision = evaluate_access(
            reader, "cognition", "read",
            tenant_id=grant.tenant_id, project_id=grant.project_id)
        if not decision.allowed:
            raise VastaError(
                code="access.denied",
                message=f"项目级共享——读者作用域不符（{decision.reason}）",
            )
        return
    # organization：org 同名不跨租户（评审修复 S-1——组织面原先
    # 只比 org 字符串，两租户同名 org 互相穿透）
    if reader.tenant_id != grant.tenant_id:
        raise VastaError(
            code="access.denied",
            message=(f"组织级共享跨租户拒——读者租户 {reader.tenant_id!r}"
                     f" ≠ 共享租户 {grant.tenant_id!r}"),
        )
    if reader_org == grant.publisher_org:
        return  # 同组织（同租户内）
    if accepted_orgs and reader_org in accepted_orgs:
        return  # 接收方已接受
    raise VastaError(
        code="access.denied",
        message=(f"组织级共享——{reader_org!r} 既非发布组织 "
                 f"{grant.publisher_org!r} 也未接受共享（双边未完成）"),
    )


async def unshare_asset(
    store: Any, grant: ShareGrant, *,
    revoked_by: str,
) -> None:
    """撤销共享（可见性回 private + 留痕）。"""
    from vasta_protocols.sequencer import EventSequencer

    sequencer = EventSequencer(
        store, _SHARING_RUN,
        tenant_id=grant.tenant_id, project_id=grant.project_id)
    await sequencer.emit(
        "claim.shared_revoked" if grant.asset_kind == "claim"
        else "artifact.shared_revoked", {
            "asset_ref": grant.asset_ref,
            "revoked_by": revoked_by,
        })


__all__ = ["ShareAcceptance", "ShareGrant", "Visibility",
           "check_shared_access", "share_asset", "unshare_asset"]
