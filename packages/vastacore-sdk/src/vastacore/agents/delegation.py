"""多 Agent 委派契约（Story 11.3，FR-050，G1）。

多 Agent 不是默认答案——启用时委派必须显式声明边界：

- **DelegationContract** 四要素（FR-050 字面）：输入范围（input
  scope——子 Agent 可读的作用域面）、权限清单（permissions——
  工具/动作白名单）、预算（budget——从主 Agent 划转的配额）、
  输出契约（output_contract——复用 Epic 3 ContractTemplate 形态）；
- **delegate**：契约校验（空权限拒/预算值须非负有限/输出契约缺拒
  ——fail-closed）→ 预算划转留痕（``run.delegation_created`` 事件
  携带预算——真实 CostLedger 记账由调用方接）；
- **validate_action**：子 Agent 动作在契约内校验——超输入范围/
  未授权工具/预算耗尽即拒（同步校验；violation 留痕由调用方经
  11.5 ``run.role_violation`` 面接）；
- **complete_delegation**：输出经输出契约核验后收回（偏差即
  verification 语义——复用 9.7 偏差窗口判定）。

Epic 11 评审修复（盲审 M1、边界 D-1/D-2/D-3/D-4）：

- 预算值 NaN/inf 构造期拒（比较判负对 NaN 全失效的家族根因）；
- ``delegate`` 对 parent_budget **缺键即拒**（原 ``available is
  None`` 跳过——fail-open），并支持 ``committed_budget`` 累计
  对拍（多份委派合计不可透支父配额）；
- ``validate_action`` 执行 input_scope（FR-050 四要素之「输入
  范围」原为纯声明）与 budget_used 有限性/非负校验。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

from ._finite import require_finite

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
                    "max_wall_seconds——键值非负有限）")
    output_contract: dict[str, Any] = Field(
        description="输出契约（Epic 3 ContractTemplate 形态——"
                    "goal/preconditions/prediction/success_criteria 等）")
    tenant_id: str = "t-default"
    project_id: str = "p-default"

    def model_post_init(self, __context: Any) -> None:
        for key, value in self.budget.items():
            require_finite(
                value, field=f"预算 {key}",
                code="delegation.bad_budget", non_negative=True)
        criteria = self.output_contract.get("success_criteria")
        if not criteria:
            raise VastaError(
                code="delegation.bad_output_contract",
                message="输出契约缺 success_criteria（核验面不可少）",
            )
        if not isinstance(criteria, list) or \
                not all(isinstance(c, str) and c for c in criteria):
            raise VastaError(
                code="delegation.bad_output_contract",
                message=(f"success_criteria 须为非空字符串列表"
                         f"（得到 {criteria!r}——字符串会逐字符"
                         "迭代核验、整数裸 TypeError）"),
            )


async def delegate(
    store: Any, contract: DelegationContract, *,
    parent_budget: dict[str, float] | None = None,
    committed_budget: dict[str, float] | None = None,
) -> None:
    """建立委派：契约校验 → 预算划转留痕 → 委派事件留痕。

    parent_budget 给定时校验划转不超主 Agent 自身配额（fail-closed
    ——**缺键即拒**，预算维度必须显式存在于父配额）；
    committed_budget 给定时按「已划转累计 + 本次 ≤ 父配额」对拍
    （多份委派合计不可透支）。"""
    if parent_budget is not None:
        for key, amount in contract.budget.items():
            available = parent_budget.get(key)
            if available is None:
                raise VastaError(
                    code="delegation.budget_dimension_unknown",
                    message=(f"父配额无预算维度 {key!r}——委派预算"
                             "维度必须显式存在（fail-closed）"),
                )
            already = (committed_budget or {}).get(key, 0.0)
            if amount + already > available:
                raise VastaError(
                    code="delegation.budget_exceeded",
                    message=(f"预算划转 {key}={amount}（累计 "
                             f"{already}）超主 Agent 配额 "
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


def _check_input_scope(contract: DelegationContract,
                       action: Any) -> None:
    """输入范围执行：action.inputs 的每个引用必须在契约作用域内。

    约定：action 携 ``inputs`` dict（键→实际值）；契约 input_scope
    键→允许值（str）或允许值清单（list[str]）。无 ``inputs`` 的
    动作无输入面可查（工具面仍受 permissions 校验）。"""
    inputs = getattr(action, "inputs", None)
    if not inputs:
        return
    for key, value in inputs.items():
        allowed = contract.input_scope.get(key)
        if allowed is None:
            raise VastaError(
                code="delegation.input_out_of_scope",
                message=(f"动作输入 {key}={value!r} 不在委派输入范围"
                         f"（契约作用域键 {sorted(contract.input_scope)}"
                         "——FR-050 输入范围）"),
            )
        allowed_values = allowed if isinstance(allowed, list) else [allowed]
        if value not in allowed_values:
            raise VastaError(
                code="delegation.input_out_of_scope",
                message=(f"动作输入 {key}={value!r} 超委派范围"
                         f"（允许 {allowed_values!r}）"),
            )


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
    _check_input_scope(contract, action)
    if budget_used is not None:
        for key, used in budget_used.items():
            require_finite(
                used, field=f"预算用量 {key}",
                code="delegation.bad_budget_usage", non_negative=True)
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
