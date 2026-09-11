"""动态自治等级（Story 11.7，FR-039，G3）。

自治不是全有全无——按环境/工具/操作/数据范围四维动态调整：

- **AutonomyInputs**：四维风险输入（环境风险 0-1 / 工具风险 0-1 /
  操作风险 0-1 / 数据敏感度 0-1）；
- **AutonomyPolicy**：四维权重与等级阈值——综合分映射 L0 观察～
  L3 自主四档；
- **assess_autonomy**：输入 → 等级（纯函数可单测）——维度变化
  与等级跃迁留痕（``run.autonomy_adjusted``）；
- **降级即时、升级需条件**：升档需连续 N 次评估达标（防抖动），
  降档一次即生效（安全优先）；与策略引擎联动
  （``required_approval_for``——等级决定动作免批/需批/禁批）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.sequencer import EventSequencer

_AUTONOMY_RUN = "autonomy"


class AutonomyLevel(StrEnum):
    L0_OBSERVE = "L0"  # 观察只读
    L1_SUGGEST = "L1"  # 建议需批
    L2_ASSIST = "L2"   # 低危免批高危需批
    L3_AUTONOMOUS = "L3"  # 自主（保留收回权）


#: 综合分阈值（升序——score < t0 → L0；< t1 → L1；…）。
_DEFAULT_THRESHOLDS = (0.25, 0.50, 0.75)


class AutonomyInputs(BaseModel):
    """四维风险输入（各 0-1，越高风险越高）。"""

    model_config = ConfigDict(extra="forbid")

    environment_risk: float = Field(ge=0.0, le=1.0)
    tool_risk: float = Field(ge=0.0, le=1.0)
    operation_risk: float = Field(ge=0.0, le=1.0)
    data_sensitivity: float = Field(ge=0.0, le=1.0)


class AutonomyPolicy(BaseModel):
    """四维权重（和为 1）与阈值。"""

    model_config = ConfigDict(extra="forbid")

    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "environment": 0.2, "tool": 0.3,
            "operation": 0.3, "data": 0.2})
    thresholds: tuple[float, float, float] = _DEFAULT_THRESHOLDS
    promote_streak: int = Field(
        default=2, ge=1,
        description="升档需连续 N 次达标（防抖动）")

    def model_post_init(self, __context: Any) -> None:
        import math

        dimension_keys = {"environment", "tool", "operation", "data"}
        if set(self.weights) != dimension_keys:
            raise ValueError(
                f"权重键集须恰为四维 {sorted(dimension_keys)}"
                f"（得到 {sorted(self.weights)}）")
        for key, weight in self.weights.items():
            if not math.isfinite(weight) or weight < 0:
                raise ValueError(
                    f"权重 {key}={weight!r} 须为非负有限数"
                    "（负权重使风险方向反转、NaN 使档位静默失效）")
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"权重和须为 1（得到 {total}）")
        t0, t1, t2 = self.thresholds
        if not all(math.isfinite(t) for t in (t0, t1, t2)) \
                or not t0 < t1 < t2:
            raise ValueError(
                f"阈值须严格递增且有限（得到 {self.thresholds}）"
                "——非单调阈值使档位互斥失效")


class AutonomyState(BaseModel):
    """Agent 当前自治状态（等级 + 升档连胜计数）。"""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    level: AutonomyLevel = AutonomyLevel.L0_OBSERVE
    promote_streak: int = 0


def compute_score(
    inputs: AutonomyInputs, policy: AutonomyPolicy,
) -> float:
    """四维加权综合分（风险分——越高越受限）。"""
    return (
        inputs.environment_risk * policy.weights["environment"]
        + inputs.tool_risk * policy.weights["tool"]
        + inputs.operation_risk * policy.weights["operation"]
        + inputs.data_sensitivity * policy.weights["data"]
    )


def _level_for_score(score: float, policy: AutonomyPolicy
                     ) -> AutonomyLevel:
    t0, t1, t2 = policy.thresholds
    if score < t0:
        return AutonomyLevel.L3_AUTONOMOUS  # 低风险 → 高自治
    if score < t1:
        return AutonomyLevel.L2_ASSIST
    if score < t2:
        return AutonomyLevel.L1_SUGGEST
    return AutonomyLevel.L0_OBSERVE  # 高风险 → 只观察


_LEVEL_ORDER = [AutonomyLevel.L0_OBSERVE, AutonomyLevel.L1_SUGGEST,
                AutonomyLevel.L2_ASSIST, AutonomyLevel.L3_AUTONOMOUS]


def assess_autonomy(
    state: AutonomyState, inputs: AutonomyInputs,
    policy: AutonomyPolicy | None = None,
) -> AutonomyState:
    """评估 → 新状态（纯函数）：

    - 目标等级低于当前（降级）→ 即时生效，连胜清零；
    - 目标等级高于当前（升档蓄势）→ 仅「读数达到高于当前档」
      的评估计连胜；连胜满 promote_streak 升**一级**（逐级推进
      ——不跳级）；
    - 同级 → 状态不变（同级读数不蓄势——升档连胜只由升档级
      读数构成，单次低危读数不可携历史同级计数跳档）。

    Epic 11 评审修复（盲审 H4/边界 A-4）：原实现同级评估也递增
    streak，且升档直跳目标档——L1 上同级蓄势任意次后，单次低危
    读数即 L1→L3，防抖动承诺失效。"""
    policy = policy or AutonomyPolicy()
    score = compute_score(inputs, policy)
    target = _level_for_score(score, policy)
    current_idx = _LEVEL_ORDER.index(state.level)
    target_idx = _LEVEL_ORDER.index(target)
    if target_idx < current_idx:
        return state.model_copy(update={
            "level": target, "promote_streak": 0})  # 降级即时
    if target_idx > current_idx:
        streak = state.promote_streak + 1
        if streak >= policy.promote_streak:
            return state.model_copy(update={
                "level": _LEVEL_ORDER[current_idx + 1],
                "promote_streak": 0})  # 逐级升档
        return state.model_copy(update={"promote_streak": streak})
    return state.model_copy()  # 同级：不蓄势


def required_approval_for(level: AutonomyLevel,
                          operation_risk: float) -> str:
    """等级 × 操作风险 → 审批要求（与 FR-033 策略引擎联动）：
    free（免批）/ required（需批）/ forbidden（禁批）。"""
    if level is AutonomyLevel.L0_OBSERVE:
        return "forbidden" if operation_risk > 0.1 else "required"
    if level is AutonomyLevel.L1_SUGGEST:
        return "forbidden" if operation_risk > 0.7 else "required"
    if level is AutonomyLevel.L2_ASSIST:
        if operation_risk > 0.8:
            return "forbidden"
        return "free" if operation_risk <= 0.5 else "required"
    # L3：全免批（人工保留收回权——FR-052）
    return "free"


async def trace_adjustment(
    store: Any, old: AutonomyState, new: AutonomyState, *,
    inputs: AutonomyInputs,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> None:
    """维度变化与等级跃迁留痕（run.autonomy_adjusted）。"""
    if old.level == new.level and \
            old.promote_streak == new.promote_streak:
        return  # 无变化不留痕（幂等）
    sequencer = EventSequencer(
        store, _AUTONOMY_RUN,
        tenant_id=tenant_id, project_id=project_id)
    await sequencer.emit("run.autonomy_adjusted", {
        "agent_id": new.agent_id,
        "from_level": old.level.value, "to_level": new.level.value,
        "inputs": inputs.model_dump(),
        "promote_streak": new.promote_streak,
    })


__all__ = ["AutonomyInputs", "AutonomyLevel", "AutonomyPolicy",
           "AutonomyState", "assess_autonomy", "compute_score",
           "required_approval_for", "trace_adjustment"]
