"""Plan/PlanStep 实体与偏差失效联动（FR-037，蓝图 §17.1，Story 3.5）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StepStatus = Literal["pending", "executing", "done", "invalidated", "failed"]
PlanStatus = Literal["active", "invalidated", "completed"]


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    args: dict[str, object] = Field(default_factory=dict)
    status: StepStatus = "pending"


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=1)
    goal: str = ""
    steps: list[PlanStep] = Field(default_factory=list)
    status: PlanStatus = "active"

    @property
    def executable_steps(self) -> list[PlanStep]:
        """仍可执行的步（失效后为零——AC-04 的核心保证）。"""
        if self.status != "active":
            return []
        return [s for s in self.steps if s.status in ("pending", "executing")]

    def invalidate(self, reason: str) -> list[PlanStep]:
        """整体失效：非终态步全部标 invalidated，返回被失效的步。

        幂等：已失效的 Plan 再调用返回空（不重复计副作用）。"""
        if self.status != "active":
            return []
        affected: list[PlanStep] = []
        for step in self.steps:
            if step.status in ("pending", "executing"):
                step.status = "invalidated"
                affected.append(step)
        self.status = "invalidated"
        self._invalidated_reason = reason  # type: ignore[attr-defined]
        return affected

    @property
    def invalidated_reason(self) -> str | None:
        return getattr(self, "_invalidated_reason", None)


__all__ = ["Plan", "PlanStep", "PlanStatus", "StepStatus"]
