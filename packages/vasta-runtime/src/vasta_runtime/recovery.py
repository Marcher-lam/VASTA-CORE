"""有界恢复序列（FR-037，Story 3.5）。

序列：等待稳定窗 → 读回复核 → 回看证据（记录前后事件引用）→ 故障分类
→ 分派（retry / compensate / replan / human_takeover / safe_stop）。

- 每次恢复落 `action.recovered`（成功）或计入恢复预算；
- 达上限 → run.failed{safe_stop, reason:"recovery_limit"}；
- 故障分类（最小规则版）：environment_delay / tool_error /
  permission_denied / model_misconception / external_change；
- 补偿与重新规划在 MVP 记录决策（执行属 FR-038 / 模型侧）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError

#: 恢复决策动作（蓝图 §12.5）。
RecoveryAction = Literal[
    "retry", "compensate", "replan", "human_takeover", "safe_stop"
]


class FaultClass(StrEnum):
    ENVIRONMENT_DELAY = "environment_delay"
    TOOL_ERROR = "tool_error"
    PERMISSION_DENIED = "permission_denied"
    MODEL_MISCONCEPTION = "model_misconception"
    EXTERNAL_CHANGE = "external_change"


class RecoveryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_retries: int = Field(default=2, ge=0)
    max_side_effects: int = Field(default=4, ge=0, description="恢复动作总上限（含补偿/重规划）")
    wait_ms: int = Field(default=0, ge=0, description="稳定窗（MVP 记录不睡眠）")


class RecoveryInput(BaseModel):
    """一次偏差的恢复输入（分类证据）。"""

    model_config = ConfigDict(extra="forbid")

    tool_ok: bool = True  # 工具返回是否成功
    read_back_ok: bool = True  # 读回复核是否通过
    permission_denied: bool = False
    external_change_in_window: bool = False
    verification_deviated: bool = True


class RecoveryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt: int = Field(ge=1)
    fault_class: str
    action: RecoveryAction
    reason: str


class RecoveryLimitExceededError(VastaError):
    def __init__(self, attempts: int, limit_kind: str) -> None:
        super().__init__(
            code="recovery.limit_exceeded",
            message=f"恢复达上限（{limit_kind}，{attempts} 次）——安全停止",
            retryable=False,
        )
        self.attempts = attempts
        self.limit_kind = limit_kind


def classify_fault(incident: RecoveryInput) -> FaultClass:
    """最小规则分类（顺序即优先级）。"""
    if incident.permission_denied:
        return FaultClass.PERMISSION_DENIED
    if incident.external_change_in_window:
        return FaultClass.EXTERNAL_CHANGE
    if not incident.tool_ok:
        return FaultClass.TOOL_ERROR
    if not incident.read_back_ok and incident.verification_deviated:
        return FaultClass.ENVIRONMENT_DELAY
    return FaultClass.MODEL_MISCONCEPTION


#: 分类 → 默认决策（蓝图 §12.5 的最小映射）。
_DEFAULT_ACTION: dict[str, RecoveryAction] = {
    FaultClass.ENVIRONMENT_DELAY: "retry",
    FaultClass.TOOL_ERROR: "compensate",
    FaultClass.PERMISSION_DENIED: "human_takeover",
    FaultClass.MODEL_MISCONCEPTION: "replan",
    FaultClass.EXTERNAL_CHANGE: "replan",
}


class RecoveryTracker:
    """有界恢复状态机（每 Run 一个实例）。"""

    def __init__(self, policy: RecoveryPolicy | None = None) -> None:
        self.policy = policy or RecoveryPolicy()
        self._retries = 0
        self._side_effects = 0
        self.history: list[RecoveryDecision] = []

    @property
    def retries_used(self) -> int:
        return self._retries

    @property
    def side_effects_used(self) -> int:
        return self._side_effects

    def decide(self, incident: RecoveryInput) -> RecoveryDecision:
        """分类并分派；超限抛 RecoveryLimitExceededError（调用方转安全停止）。"""
        fault = classify_fault(incident)
        attempt = len(self.history) + 1

        # 副作用总上限优先于一切分派（含重试升级路径——不得绕过总闸）
        if self._side_effects >= self.policy.max_side_effects:
            raise RecoveryLimitExceededError(attempt, "max_side_effects")

        if self._retries >= self.policy.max_retries and fault == FaultClass.ENVIRONMENT_DELAY:
            # 重试额度耗尽 → 升级为接管（不再盲目重试）
            action: RecoveryAction = "human_takeover"
        else:
            action = _DEFAULT_ACTION[fault]

        decision = RecoveryDecision(
            attempt=attempt,
            fault_class=fault.value,
            action=action,
            reason=f"{fault.value} → {action}",
        )
        self.history.append(decision)
        # 评审修复：retry 是真实重执行——同样计入副作用总闸
        if action == "retry":
            self._retries += 1
        self._side_effects += 1
        return decision

    def payload(self) -> dict[str, Any]:
        return {
            "retries_used": self._retries,
            "side_effects_used": self._side_effects,
            "history": [d.model_dump() for d in self.history],
        }


__all__ = [
    "FaultClass",
    "RecoveryAction",
    "RecoveryDecision",
    "RecoveryInput",
    "RecoveryLimitExceededError",
    "RecoveryPolicy",
    "RecoveryTracker",
    "classify_fault",
]
