"""验证流水线（Story 6.3）——静态/回放/性质 + 激活门槛。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError

from .manifest import PartialWorldModel
from .python_model import PythonWorldModel, _static_check


@dataclass
class Trajectory:
    """一条历史轨迹（回放测试输入）。"""

    initial_observation: dict[str, Any]
    actions: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    final_outcome: str


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_name: str
    static_check: bool
    replay_passed: int = 0
    replay_total: int = 0
    property_passed: int = 0
    property_total: int = 0
    activation_approved: bool = Field(default=False, description="MVP 人工批准（影子期 Stage 4）")

    @property
    def all_replay_passed(self) -> bool:
        return self.replay_total > 0 and self.replay_passed == self.replay_total

    @property
    def activatable(self) -> bool:
        """激活门槛：静态过 + 全部回放过 + 性质过 + 人工批准（FR-044/AC-05）。"""
        return (
            self.static_check
            and self.all_replay_passed
            and self.property_total > 0
            and self.property_passed == self.property_total
            and self.activation_approved
        )


def validate_model(
    model: PartialWorldModel,
    trajectories: list[Trajectory],
    *,
    properties: list[Any] | None = None,
    activation_approved: bool = False,
) -> ValidationReport:
    """静态检查 + 历史回放 + 性质测试（人工批准替代影子期，MVP）。

    回放判定（评审修复）：每条轨迹必须发生至少一次「预测键与实际键
    重叠且相等」的比较——零重叠（预测与观察无交集）视为未验证，不通过。"""
    static_ok = True
    if isinstance(model, PythonWorldModel):
        try:
            _static_check(model.code)
        except VastaError:
            static_ok = False
    replay_passed = 0
    for traj in trajectories:
        state = model.init_state(traj.initial_observation)
        ok = True
        compared = 0
        for i, action in enumerate(traj.actions):
            state = model.transition(state, action)
            predicted = model.observe(state)
            actual = traj.observations[i] if i < len(traj.observations) else {}
            if isinstance(actual, dict):
                for key, value in predicted.items():
                    if key in actual:
                        compared += 1
                        if actual[key] != value:
                            ok = False
        if compared == 0:
            ok = False  # 无任何键可比 → 回放空转（评审修复）
        if model.outcome(state) != traj.final_outcome:
            ok = False
        replay_passed += 1 if ok else 0
    props = properties or []
    prop_passed = sum(1 for p in props if p(model))
    return ValidationReport(
        model_name=model.manifest.name,
        static_check=static_ok,
        replay_passed=replay_passed,
        replay_total=len(trajectories),
        property_passed=prop_passed,
        property_total=len(props),
        activation_approved=activation_approved,
    )


