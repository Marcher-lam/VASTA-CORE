"""MetaController 规则版（Story 6.4，FR-040）——决策可解释且留痕。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class MetaDecision(StrEnum):
    BUILD = "build"
    USE = "use"
    REPAIR = "repair"
    BYPASS = "bypass"
    PROBE = "probe"
    STOP = "stop"


@dataclass
class MetaSignals:
    """元决策输入信号（蓝图 §13.4 受益公式的一阶近似）。"""

    planning_horizon: int = 0
    real_action_risk: str = "R0"
    mechanism_reuse: int = 0
    repeated_prediction_failure: int = 0
    hypothesis_conflict: int = 0
    has_validated_model: bool = False


def decide_meta(signals: MetaSignals) -> MetaDecision:
    """规则版元决策（可解释；学习版需离线门禁，蓝图 §13.4）。

    评审修复：补 STOP 可达路径——持续预测失败且无可修模型（建/修/探
    都无收益）时停止并上抛，避免无限探针循环。"""
    if signals.repeated_prediction_failure >= 5 and not signals.has_validated_model:
        return MetaDecision.STOP
    if signals.repeated_prediction_failure >= 3 and signals.has_validated_model:
        return MetaDecision.REPAIR
    if signals.hypothesis_conflict >= 2 and signals.has_validated_model:
        return MetaDecision.REPAIR
    if signals.planning_horizon >= 5 and signals.real_action_risk in ("R2", "R3"):
        if signals.has_validated_model:
            return MetaDecision.USE
        return MetaDecision.BUILD
    if signals.mechanism_reuse >= 3:
        if signals.has_validated_model:
            return MetaDecision.USE
        return MetaDecision.BUILD
    if signals.repeated_prediction_failure >= 2 and not signals.has_validated_model:
        return MetaDecision.PROBE
    return MetaDecision.BYPASS


async def emit_meta_decision(
    store: Any,
    decision: MetaDecision,
    signals: MetaSignals,
    *,
    reason: str,
) -> None:
    """元决策留痕（FR-040，评审修复：决策不落事件 → 统一写 world_model.meta_decision）。"""
    from ._bookkeeping_stub import emit_world_model_event  # 延迟防环

    await emit_world_model_event(
        store,
        "world_model.meta_decision",
        {
            "decision": str(decision),
            "reason": reason,
            "signals": {
                "planning_horizon": signals.planning_horizon,
                "real_action_risk": signals.real_action_risk,
                "mechanism_reuse": signals.mechanism_reuse,
                "repeated_prediction_failure": signals.repeated_prediction_failure,
                "hypothesis_conflict": signals.hypothesis_conflict,
                "has_validated_model": signals.has_validated_model,
            },
        },
    )


