"""Supervisor：循环检测与持续偏差监控（FR-053，Story 1.6）。

- 循环检测：同一 (状态签名, 动作) 模式**连续**重复 N 次（模式改变即重置）；
- 持续偏差：连续 M 次核验偏差（非偏差即重置）——Epic 3 核验链将经
  RunEngine.note_deviation 接线；
- 触发即升级：引擎发 incident.opened → run.paused → 抛
  SupervisorEscalationError；被检动作不执行、不耗预算；
- 复位语义：resume（人工已审阅）与 reset（新 episode）清零计数。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action

from .checkpoint import ObservationSignature


class SupervisorConfig(BaseModel):
    """阈值可配置（FR-053）；默认 loop=8 避开短序列误报。"""

    model_config = ConfigDict(extra="forbid")

    loop_threshold: int = Field(default=8, ge=1)
    deviation_threshold: int = Field(default=3, ge=1)


class EscalationReason(StrEnum):
    LOOP = "supervisor_loop"
    DEVIATIONS = "supervisor_deviations"


@dataclass(frozen=True)
class Escalation:
    reason: EscalationReason
    detail: dict[str, object] = field(default_factory=dict)


class SupervisorEscalationError(VastaError):
    def __init__(self, escalation: Escalation) -> None:
        super().__init__(
            code=f"supervisor.{escalation.reason.value.split('_', 1)[1]}",
            message=f"supervisor escalation: {escalation.reason.value}",
            retryable=False,
        )
        self.reason = escalation.reason
        self.detail = escalation.detail


def _pattern_key(
    signature: ObservationSignature, action: Action
) -> tuple[str, tuple[str, ...], str, str]:
    args_key = json.dumps(
        action.args, sort_keys=True, separators=(",", ":"), default=repr
    )
    return (signature.kind, signature.available_actions, action.tool, args_key)


class Supervisor:
    def __init__(self, config: SupervisorConfig | None = None) -> None:
        self.config = config or SupervisorConfig()
        self._last_key: tuple[str, tuple[str, ...], str, str] | None = None
        self._loop_count = 0
        self._deviation_streak = 0
        self.total_escalations = 0

    def check_loop(
        self, signature: ObservationSignature | None, action: Action
    ) -> Escalation | None:
        """预执行检测：同一模式连续达到阈值 → 升级。"""
        if signature is None:
            return None
        key = _pattern_key(signature, action)
        if key == self._last_key:
            self._loop_count += 1
        else:
            self._last_key = key
            self._loop_count = 1
        if self._loop_count >= self.config.loop_threshold:
            self.total_escalations += 1
            return Escalation(
                EscalationReason.LOOP,
                {
                    "count": self._loop_count,
                    "action": action.tool,
                    "signature_kind": signature.kind,
                    "available_actions": list(signature.available_actions),
                },
            )
        return None

    def note_deviation(self, deviation: bool) -> Escalation | None:
        """核验结果喂入（Epic 3 接线）：连续 M 次偏差 → 升级。"""
        if deviation:
            self._deviation_streak += 1
        else:
            self._deviation_streak = 0
        if self._deviation_streak >= self.config.deviation_threshold:
            self.total_escalations += 1
            return Escalation(
                EscalationReason.DEVIATIONS, {"streak": self._deviation_streak}
            )
        return None

    def reset_loop(self) -> None:
        """新 episode：清循环计数（偏差连续性跨 episode 保留由调用方决定，
        引擎 reset 时全清）。"""
        self._last_key = None
        self._loop_count = 0

    def reset_all(self) -> None:
        """人工 resume 后：全部计数清零。"""
        self.reset_loop()
        self._deviation_streak = 0
