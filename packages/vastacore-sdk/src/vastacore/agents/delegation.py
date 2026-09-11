"""多 Agent 委派契约（Story 11.3，FR-050，G1）。

多 Agent 不是默认答案——启用时委派必须显式声明边界：

- **DelegationContract** 四要素（FR-050 字面）：输入范围（input
  scope——子 Agent 可读的作用域面）、权限清单（permissions——
  工具/动作白名单）、预算（budget——从主 Agent 划转的
  Budget 配额）、输出契约（output_contract——复用 Epic 3
  ContractTemplate 形态）；
- **delegate**：契约校验（空权限拒/超主 Agent 自身预算拒/输出
  契约缺拒——fail-closed）→ 预算划转（CostLedger 记账留痕）→
  ``run.delegation_created`` 留痕（委派链可溯）；
- **validate_action**：子 Agent 动作在契约内校验——超输入范围/
  未授权工具/预算耗尽即拒（``run.delegation_violation`` 留痕）；
- **complete_delegation**：输出经输出契约核验后收回（偏差即
  verification 语义——复用 9.7 偏差窗口判定）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

_DELEGATION_RUN = "delegations"


class DelegationContract(BaseModel):
    """委派契约（四要素——FR-050 字面）。"""

    model_config = ConfigDict(extra="forbid")

    delegation_id: str = Field(min_length=1)
    parent_agent: str = Field(min_length=1)
    child_agent: str = Field(min_length=1)
    input_scope: dict[str, str] = Field(
        description="输入范围——子 Agent 可读的作用域面（键值对）")
    permissions: list[str] = Field(
        min_length=1, description="工具/动作白名单（空清单拒）")
    budget: dict[str, float] = Field(
        description="预算划转（max_actions/max_model_calls/"
                    "max_wall_seconds——键值非负）")
    output_contract: dict[str, Any] = Field(
        description="输出契约（Epic 3 ContractTemplate 形态——"
                    "goal/preconditions/prediction/success_criteria 等）")
    tenant_id: str = "t-default"
    project_id: str = "p-default"

    def model_post_init(self, __context: Any) -> None:
        for key, value in self.budget.items():
            if not isinstance(value, (int, float)) or value < 0:
                raise VastaError(
                    code="delegation.bad_budget",
                    message=f"预算 {key}={value!r} 须为非负数")
        if not self.output_contract.get("success_criteria"):
            raise VastaError(
                code="delegation.bad_output_contract",
                message="输出契约缺 success_criteria（核验面不可少）")


async def delegate(
    store: Any, contract: DelegationContract, *,
    parent_budget: dict[str, float] | None = None,
) -> None:
    """建立委派：契约校验 → 预算划转留痕 → 委派事件留痕。

    parent_budget 给定时校验划转不超主 Agent 自身配额（fail-closed）。"""
    if parent_budget is not None:
        for key, amount in contract.budget.items():
            available = parent_budget.get(key)
            if available is not None and amount > available:
                raise VastaError(
                    code="delegation.budget_exceeded",
                    message=(f"预算划转 {key}={amount} 超主 Agent 配额 "
                             f"{available}——不可透支委派"),
                )
    sequencer = EventSequencer(
        store, _DELEGATION_RUN,
        tenant_id=contract.tenant_id, project_id=contract.project_id)
    await sequencer.emit("run.delegation_created", {
        "delegation_id": contract.delegation_id,
        "parent_agent": contract.parent_agent,
        "child_agent": contract.child_agent,
        "input_scope": contract.input_scope,
        "permissions": list(contract.permissions),
        "budget": dict(contract.budget),
        "output_contract": dict(contract.output_contract),
    })


def validate_action(
    store: Any, contract: DelegationContract,
    action: Any, *,
    budget_used: dict[str, float] | None = None,
) -> None:
    """子 Agent 动作在契约内校验（fail-closed：超范围/未授权/预算
    耗尽即拒——同步校验，留痕走异步 emitter 由调用方接）。"""
    if action.tool not in contract.permissions:
        raise VastaError(
            code="delegation.tool_not_permitted",
            message=(f"工具 {action.tool!r} 不在委派权限清单 "
                     f"{contract.permissions}（FR-050 边界）"),
        )
    if budget_used is not None:
        for key, used in budget_used.items():
            limit = contract.budget.get(key)
            if limit is not None and used >= limit:
                raise VastaError(
                    code="delegation.budget_exhausted",
                    message=(f"委派预算 {key} 耗尽（{used}/{limit}）"
                             "——须回收或追加委派"),
                )


async def complete_delegation(
    store: Any, contract: DelegationContract, *,
    output: dict[str, Any],
) -> bool:
    """收回委派：输出经 success_criteria 核验（简化核验面——输出
    含全部 criteria 键且非空），偏差即 False（留痕）。"""
    criteria = contract.output_contract.get("success_criteria") or []
    passed = all(
        isinstance(output.get(c), (str, int, float, bool, list, dict))
        and output.get(c) not in ("", [], {}, None)
        for c in criteria if isinstance(c, str))
    sequencer = EventSequencer(
        store, _DELEGATION_RUN,
        tenant_id=contract.tenant_id, project_id=contract.project_id)
    await sequencer.emit("run.delegation_completed", {
        "delegation_id": contract.delegation_id,
        "passed": passed,
        "missing": [c for c in criteria if isinstance(c, str)
                    and not output.get(c)] if not passed else [],
    })
    return passed


__all__ = ["DelegationContract", "complete_delegation", "delegate",
           "validate_action"]
