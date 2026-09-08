"""检查点（FR-004 / 蓝图 §9.3）：恢复比对与剩余预算的最小载体。

完整检查点（生效策略/模型版本、未决批准等）随对应 Epic 扩充；
active_plans 此处为占位（计划实体属 Epic 3/6）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.protocols import Action, Observation

from .budget import BudgetSnapshot
from .state import RunState


class ObservationSignature(BaseModel):
    """观察的可比对签名：类型 + 可用动作（环境变化检测的最小形态）。"""

    model_config = ConfigDict(extra="forbid")

    kind: str
    available_actions: tuple[str, ...]

    @classmethod
    def from_observation(cls, obs: Observation) -> ObservationSignature:
        return cls(kind=obs.kind, available_actions=tuple(obs.available_actions))


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    state: RunState
    last_event_seq: int
    last_action: Action | None = None
    active_plans: list[str] = Field(default_factory=list)
    budget: BudgetSnapshot
    last_observation: ObservationSignature | None = None
