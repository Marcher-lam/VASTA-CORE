"""ObservationCollector：五类观察的采集与分类保证（FR-005，Story 1.3）。

结构不变量：
- 只有决策帧可成为可行动状态（INV-04）——last_actionable 仅在
  kind == "decision" 时更新，非决策帧在结构上无法进入该槽位；
- episode_ended 仅由终局帧置位、由 reset 清除；外部事件不算终局；
- 每条观察事件的 payload 携带 actionable 标志，下游核验器可直接断言。
"""

from __future__ import annotations

from typing import Any

from vasta_protocols.protocols import Observation

_FIVE_KINDS = ("decision", "transition", "terminal", "reset", "external")


class TerminalObservationError(Exception):
    """终局后尝试行动（蓝图 §33.1 性质：终局后不行动）。"""


class ObservationCollector:
    def __init__(self) -> None:
        self.last_actionable: Observation | None = None
        self.episode_ended: bool = False
        self.counts: dict[str, int] = {kind: 0 for kind in _FIVE_KINDS}

    def record(self, obs: Observation) -> dict[str, Any]:
        """记录一条观察并返回事件 payload。"""
        if obs.kind == "decision":
            self.last_actionable = obs
        elif obs.kind == "terminal":
            self.episode_ended = True
        elif obs.kind == "reset":
            self.episode_ended = False
        self.counts[obs.kind] += 1
        return {
            "kind": obs.kind,
            "available_actions": list(obs.available_actions),
            "artifact_refs": list(obs.artifact_refs),
            "actionable": obs.actionable,  # 只有 decision 为 True（INV-04）
        }

    def reset_episode(self) -> None:
        self.episode_ended = False

    def ensure_actable(self) -> None:
        if self.episode_ended:
            raise TerminalObservationError("cannot act after terminal observation")

    @property
    def total(self) -> int:
        return sum(self.counts.values())
