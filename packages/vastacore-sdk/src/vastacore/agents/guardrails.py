"""enforcement 面组装接线（Story 12.2，Epic 11 复盘 F1/item-22，G0）。

「组件齐、组合碎」三连（Epic 9 缝 → Epic 10 装配缝 → Epic 11
enforcement 面零调用）的根治：agents/ 六个零入向调用的 enforcement
面积木在此组装为**单一动作闸门**，并由装配层（AgentSession 的
``action_guard`` 钩子——依赖倒置：execution 不 import agents，组装
方注入）在真实执行路径上强制：

- ``guard_action``：一次动作面前的组合校验——
  ① 角色边界（validate_role_action——超面即拒 + 留痕）；
  ② 委派契约（validate_action——工具白名单/input_scope/预算）；
  ③ 动态自治（assess_autonomy 四维评估 + 跃迁留痕）；
  ④ 审批矩阵（required_approval_for——forbidden 即拒）；
  ⑤ 组织风险预算（record_risk_exposure 敞口计量 + enforce_budget
     触顶降级留痕——触顶即拒）；
- ``make_action_guard``：生成 AgentSession 可注入的动作闸
  （``async (Action) -> None``——拒绝即抛，动作不执行）；
- ``leaderboard_from_tournament``（leaderboard.py）：竞赛→榜单的
  官方聚合缝（11.12 AC 点名——条目引用 settled 事件 seq）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action

from ._finite import require_finite
from .autonomy import (
    AutonomyInputs,
    AutonomyLevel,
    AutonomyPolicy,
    AutonomyState,
    assess_autonomy,
    required_approval_for,
    trace_adjustment,
)
from .delegation import DelegationContract, validate_action
from .risk_budget import (
    ExposureRecord,
    RiskBudget,
    enforce_budget,
    record_risk_exposure,
    trace_enforcement,
)
from .roles import AgentRoleConfig, validate_role_action

#: 动作闸形态：拒绝即抛 VastaError（动作不进入执行路径）。
ActionGuard = Callable[[Action], Awaitable[None]]


class GuardRailConfig(BaseModel):
    """闸门配置（角色 + 自治策略 + 风险预算 + 可选委派契约）。"""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    role_config: AgentRoleConfig
    autonomy_policy: AutonomyPolicy = AutonomyPolicy()
    risk_budget: RiskBudget
    contract: DelegationContract | None = Field(
        default=None,
        description="委派态下的契约（非 None 时动作须在契约内）")
    risk_weight: float = Field(
        default=1.0,
        description="高危动作的敞口权重（须非负有限）")
    tenant_id: str = "t-default"
    project_id: str = "p-default"

    def model_post_init(self, __context: Any) -> None:
        require_finite(
            self.risk_weight, field="risk_weight",
            code="guardrails.bad_weight", non_negative=True)


@dataclass
class GuardState:
    """闸门跨动作状态（自治等级 + 敞口快照——评估链可续）。

    两者均显式构造：autonomy 的 agent_id 与 exposure 的 scope 由
    装配方对齐（同一 Agent）。"""

    autonomy: AutonomyState
    exposure: ExposureRecord


class GuardDecision(BaseModel):
    """闸门裁决（allowed=False 的情况由 guard_action 直接抛出——
    本结构用于 allowed=True 时的审批标记与等级快照）。"""

    model_config = ConfigDict(extra="forbid")

    allowed: bool = True
    requires_approval: bool = False
    autonomy_level: AutonomyLevel
    reason: str = ""


async def guard_action(
    store: Any, config: GuardRailConfig, state: GuardState,
    action: Action, *,
    tool_category: str,
    operation_risk: float,
    inputs: AutonomyInputs | None = None,
    budget_used: dict[str, float] | None = None,
) -> GuardDecision:
    """组合闸门：角色 → 委派 → 自治 → 审批 → 风险预算（任一拒即
    抛 VastaError，动作不执行；全部拒路径均有留痕）。"""
    require_finite(
        operation_risk, field="operation_risk",
        code="guardrails.bad_operation_risk", non_negative=True)
    # ① 角色边界（超面拒 + 留痕）
    try:
        validate_role_action(
            store, config.role_config, action.tool, tool_category)
    except VastaError as exc:
        from .roles import trace_role_violation

        await trace_role_violation(
            store, config.role_config, action.tool, tool_category,
            error_message=exc.message)
        raise
    # ② 委派契约（工具白名单 + input_scope + 预算）
    if config.contract is not None:
        validate_action(store, config.contract, action,
                        budget_used=budget_used)
    # ③ 动态自治（四维评估 + 跃迁留痕）
    risk_inputs = inputs or AutonomyInputs(
        environment_risk=0.0, tool_risk=0.0,
        operation_risk=operation_risk, data_sensitivity=0.0)
    new_autonomy = assess_autonomy(
        state.autonomy, risk_inputs, config.autonomy_policy)
    if new_autonomy.level is not state.autonomy.level or \
            new_autonomy.promote_streak != state.autonomy.promote_streak:
        await trace_adjustment(
            store, state.autonomy, new_autonomy, inputs=risk_inputs,
            tenant_id=config.tenant_id, project_id=config.project_id)
    state.autonomy = new_autonomy
    # ④ 审批矩阵（forbidden 即拒；required 标记放行）
    approval = required_approval_for(new_autonomy.level, operation_risk)
    if approval == "forbidden":
        raise VastaError(
            code="guardrails.operation_forbidden",
            message=(f"Agent {config.agent_id!r} 自治等级 "
                     f"{new_autonomy.level.value} × 操作风险 "
                     f"{operation_risk}——动作禁批（FR-039 审批矩阵）"),
        )
    # ⑤ 组织风险预算（高危计量 + 触顶即拒 + 留痕）
    is_high_risk = operation_risk > 0.5
    new_exposure = await record_risk_exposure(
        store, state.exposure,
        risk_weight=config.risk_weight if is_high_risk else 0.0,
        is_high_risk=is_high_risk,
        tenant_id=config.tenant_id, project_id=config.project_id)
    allowed_level = enforce_budget(new_exposure, config.risk_budget)
    await trace_enforcement(
        store, new_exposure, config.risk_budget, allowed=allowed_level,
        tenant_id=config.tenant_id, project_id=config.project_id)
    if allowed_level is AutonomyLevel.L0_OBSERVE \
            and config.risk_budget.autonomy_ceiling is not AutonomyLevel.L0_OBSERVE:
        state.exposure = new_exposure
        raise VastaError(
            code="guardrails.risk_budget_breached",
            message=(f"Agent {config.agent_id!r} 风险敞口触顶"
                     f"（{new_exposure.risk_units_used}/"
                     f"{config.risk_budget.risk_units}）——组织级降 L0，"
                     "动作拒（FR-077 总量闸）"),
        )
    state.exposure = new_exposure
    return GuardDecision(
        requires_approval=approval == "required",
        autonomy_level=new_autonomy.level,
    )


def make_action_guard(
    store: Any, config: GuardRailConfig, state: GuardState, *,
    tool_category_of: Callable[[str], str],
    operation_risk_of: Callable[[str], float] | None = None,
    inputs_of: Callable[[str], AutonomyInputs] | None = None,
) -> ActionGuard:
    """生成 AgentSession 可注入的动作闸（``create(action_guard=…)``）。

    ``tool_category_of/operation_risk_of/inputs_of``：工具名 → 闸门
    入参的映射（装配方提供——如工具清单/契约模板的 risk 声明）。"""

    async def _guard(action: Action) -> None:
        await guard_action(
            store, config, state, action,
            tool_category=tool_category_of(action.tool),
            operation_risk=(operation_risk_of or (lambda _t: 0.1))(
                action.tool),
            inputs=inputs_of(action.tool) if inputs_of else None,
        )

    return _guard


__all__ = ["ActionGuard", "GuardDecision", "GuardRailConfig",
           "GuardState", "guard_action", "make_action_guard"]
