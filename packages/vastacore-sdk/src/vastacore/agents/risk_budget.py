"""组织级风险预算（Story 11.8，FR-077，G3）。

多 Agent 规模化时组织风险有总量闸：

- **RiskBudget**：层级预算（组织/项目/Agent 三级——下级不超上级）：
  风险敞口总量（risk_units）+ 高危操作配额（high_risk_ops）+
  自治等级上限（autonomy_ceiling——L0~L3）；
- **风险敞口计量**（record_risk_exposure）：高危操作计数 × 风险
  权重累计——``run.risk_exposure_recorded`` 留痕；
- **预算校验**（enforce_budget）：敞口触顶 → 组织级降自治
  （``run.risk_budget_enforced`` 留痕——降至预算允许的 ceiling）；
  下级预算超上级拒（fail-closed 配置期）；
- 预算配置留痕（``run.risk_budget_configured``）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

from .autonomy import AutonomyLevel

_BUDGET_RUN = "risk-budgets"

_LEVEL_ORDER = [AutonomyLevel.L0_OBSERVE, AutonomyLevel.L1_SUGGEST,
                AutonomyLevel.L2_ASSIST, AutonomyLevel.L3_AUTONOMOUS]


class RiskBudget(BaseModel):
    """层级风险预算。"""

    model_config = ConfigDict(extra="forbid")

    scope: str = Field(description="org:{id} / project:{id} / "
                                    "agent:{id}")
    risk_units: float = Field(ge=0, description="风险敞口总量")
    high_risk_ops: int = Field(ge=0, description="高危操作配额")
    autonomy_ceiling: AutonomyLevel = Field(
        default=AutonomyLevel.L3_AUTONOMOUS,
        description="自治等级上限（预算内的最高允许等级）")
    tenant_id: str = "t-default"
    project_id: str = "p-default"


class ExposureRecord(BaseModel):
    """风险敞口快照。"""

    model_config = ConfigDict(extra="forbid")

    scope: str
    risk_units_used: float = Field(ge=0)
    high_risk_ops_used: int = Field(ge=0)


def validate_hierarchy(
    child: RiskBudget, parent: RiskBudget | None,
) -> None:
    """下级预算不超上级（配置期 fail-closed）。"""
    if parent is None:
        return
    if child.risk_units > parent.risk_units:
        raise VastaError(
            code="riskbudget.hierarchy_violation",
            message=(f"{child.scope} 风险总量 {child.risk_units} 超 "
                     f"上级 {parent.scope} {parent.risk_units}"),
        )
    if child.high_risk_ops > parent.high_risk_ops:
        raise VastaError(
            code="riskbudget.hierarchy_violation",
            message=(f"{child.scope} 高危配额 {child.high_risk_ops} 超 "
                     f"上级 {parent.scope} {parent.high_risk_ops}"),
        )
    child_idx = _LEVEL_ORDER.index(child.autonomy_ceiling)
    parent_idx = _LEVEL_ORDER.index(parent.autonomy_ceiling)
    if child_idx > parent_idx:
        raise VastaError(
            code="riskbudget.hierarchy_violation",
            message=(f"{child.scope} 自治上限 {child.autonomy_ceiling} "
                     f"超上级 {parent.scope} {parent.autonomy_ceiling}"),
        )


async def configure_budget(
    store: Any, budget: RiskBudget, *,
    parent: RiskBudget | None = None,
    configured_by: str,
) -> None:
    """预算配置（层级校验 + 留痕）。"""
    validate_hierarchy(budget, parent)
    sequencer = EventSequencer(
        store, _BUDGET_RUN,
        tenant_id=budget.tenant_id, project_id=budget.project_id)
    await sequencer.emit("run.risk_budget_configured", {
        **budget.model_dump(mode="json"), "configured_by": configured_by,
    })


async def record_risk_exposure(
    store: Any, exposure: ExposureRecord, *,
    risk_weight: float = 1.0,
    is_high_risk: bool = False,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> ExposureRecord:
    """敞口累计（高危 × 权重）——留痕，返回新快照。

    评审修复（盲审 M2、边界 R-1）：risk_weight 须非负有限——负值
    可把触顶敞口「洗白」回预算内、NaN 使 ``>=`` 比较恒 False 永不
    触顶；``model_copy(update=)`` 不走 pydantic 校验，故更新后显式
    重验（ge=0 约束不形同虚设）。"""
    import math

    if not math.isfinite(risk_weight) or risk_weight < 0:
        raise VastaError(
            code="riskbudget.bad_weight",
            message=(f"risk_weight={risk_weight!r} 须为非负有限数"
                     "（负值洗白敞口、NaN 解除预算闸）"),
        )
    units = exposure.risk_units_used + (
        risk_weight if is_high_risk else 0.0)
    ops = exposure.high_risk_ops_used + (1 if is_high_risk else 0)
    updated = ExposureRecord.model_validate(exposure.model_copy(update={
        "risk_units_used": round(units, 6),
        "high_risk_ops_used": ops}))
    sequencer = EventSequencer(
        store, _BUDGET_RUN, tenant_id=tenant_id, project_id=project_id)
    await sequencer.emit("run.risk_exposure_recorded", {
        "scope": exposure.scope,
        "risk_weight": risk_weight, "is_high_risk": is_high_risk,
        "total_units": updated.risk_units_used,
        "total_high_risk_ops": updated.high_risk_ops_used,
    })
    return updated


def enforce_budget(
    exposure: ExposureRecord, budget: RiskBudget,
) -> AutonomyLevel:
    """预算校验 → 允许的自治等级：

    - 敞口与高危配额均在预算内 → 预算 ceiling；
    - 任一触顶 → 降至 L0（组织级降自治——安全侧）；
    - 敞口非有限（NaN——毒记录）→ fail-closed 降 L0；
    留痕由调用方接（enforce 与 trace 分离——同 11.5 模式）。"""
    import math

    if not math.isfinite(exposure.risk_units_used):
        return AutonomyLevel.L0_OBSERVE  # 毒记录 fail-closed
    if exposure.risk_units_used >= budget.risk_units or \
            exposure.high_risk_ops_used >= budget.high_risk_ops:
        return AutonomyLevel.L0_OBSERVE  # 触顶降级
    return budget.autonomy_ceiling


async def trace_enforcement(
    store: Any, exposure: ExposureRecord, budget: RiskBudget, *,
    allowed: AutonomyLevel,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> None:
    import contextlib

    with contextlib.suppress(Exception):
        sequencer = EventSequencer(
            store, _BUDGET_RUN,
            tenant_id=tenant_id, project_id=project_id)
        await sequencer.emit("run.risk_budget_enforced", {
            "scope": budget.scope,
            "units_used": exposure.risk_units_used,
            "units_budget": budget.risk_units,
            "ops_used": exposure.high_risk_ops_used,
            "ops_budget": budget.high_risk_ops,
            "allowed_level": allowed.value,
            "breached": allowed is AutonomyLevel.L0_OBSERVE
            and budget.autonomy_ceiling is not AutonomyLevel.L0_OBSERVE,
        })


__all__ = ["ExposureRecord", "RiskBudget", "configure_budget",
           "enforce_budget", "record_risk_exposure",
           "trace_enforcement", "validate_hierarchy"]
