"""三档预算：动作数 / 模型调用数 / 墙钟秒（FR-004）。

AD-15：墙钟属于安全强制 → 默认真实时钟；时钟可注入（测试 / Story 1.5
的 RunContext 将统一供给）。超限即 BudgetExceededError，由引擎转为安全停止。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.ids import now_utc


class BudgetKind(StrEnum):
    ACTIONS = "actions"
    MODEL_CALLS = "model_calls"
    WALL_SECONDS = "wall_seconds"


#: 默认时钟经 protocols.ids 供给点（AD-5 静态禁令的唯一许可来源）。
_default_clock = now_utc


class Budget(BaseModel):
    """三档上限；None 表示该档不设限。"""

    model_config = ConfigDict(extra="forbid")

    max_actions: int | None = Field(default=None, ge=0)
    max_model_calls: int | None = Field(default=None, ge=0)
    max_wall_seconds: float | None = Field(default=None, ge=0)


class BudgetSnapshot(BaseModel):
    """剩余预算快照（检查点字段之一）。"""

    model_config = ConfigDict(extra="forbid")

    actions_used: int
    model_calls_used: int
    wall_seconds_used: float
    max_actions: int | None
    max_model_calls: int | None
    max_wall_seconds: float | None


class BudgetExceededError(VastaError):
    def __init__(self, kind: BudgetKind, detail: str) -> None:
        super().__init__(
            code=f"budget.exceeded.{kind.value}",
            message=detail,
            retryable=False,
        )
        self.kind = kind


class BudgetTracker:
    """计数与墙钟跟踪；check() 在超限档上抛出。"""

    def __init__(self, budget: Budget, clock: Callable[[], datetime] | None = None) -> None:
        self._budget = budget
        self._clock = clock or _default_clock
        self._actions = 0
        self._model_calls = 0
        self._started_at: datetime | None = None
        self._paused_since: datetime | None = None
        self._paused_seconds = 0.0

    def start(self) -> None:
        if self._started_at is None:
            self._started_at = self._clock()

    def pause(self) -> None:
        """暂停墙钟计费（评审修复：人工审阅等待不计入 max_wall_seconds）。"""
        if self._started_at is not None and self._paused_since is None:
            self._paused_since = self._clock()

    def resume(self) -> None:
        if self._paused_since is not None:
            self._paused_seconds += (self._clock() - self._paused_since).total_seconds()
            self._paused_since = None

    def record_action(self) -> None:
        self._actions += 1

    def record_model_call(self) -> None:
        self._model_calls += 1

    @property
    def wall_seconds_used(self) -> float:
        if self._started_at is None:
            return 0.0
        elapsed = (self._clock() - self._started_at).total_seconds()
        if self._paused_since is not None:
            elapsed -= (self._clock() - self._paused_since).total_seconds()
        return max(elapsed - self._paused_seconds, 0.0)

    def exceeded_kind(self) -> BudgetKind | None:
        """无余量即视为超限（预检语义）：计数档 used >= max 拒绝下一次，
        墙钟档 used > max 拒绝（时间不可预扣）。"""
        b = self._budget
        if b.max_actions is not None and self._actions >= b.max_actions:
            return BudgetKind.ACTIONS
        if b.max_model_calls is not None and self._model_calls >= b.max_model_calls:
            return BudgetKind.MODEL_CALLS
        if b.max_wall_seconds is not None and self.wall_seconds_used > b.max_wall_seconds:
            return BudgetKind.WALL_SECONDS
        return None

    def check(self) -> None:
        kind = self.exceeded_kind()
        if kind is None:
            return
        raise BudgetExceededError(
            kind,
            f"budget exceeded: {kind.value} "
            f"(actions={self._actions}/{self._budget.max_actions}, "
            f"model_calls={self._model_calls}/{self._budget.max_model_calls}, "
            f"wall={self.wall_seconds_used:.3f}s/{self._budget.max_wall_seconds}s)",
        )

    def snapshot(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            actions_used=self._actions,
            model_calls_used=self._model_calls,
            wall_seconds_used=self.wall_seconds_used,
            max_actions=self._budget.max_actions,
            max_model_calls=self._budget.max_model_calls,
            max_wall_seconds=self._budget.max_wall_seconds,
        )
