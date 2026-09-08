"""GridWorldAdapter：4×4 确定网格世界（示例环境，Story 1.7）。

- start(0,0) → goal(3,3)，动作 up/down/left/right，到达目标即终局；
- 完全确定性（deterministic=True，AD-5 重放替身标记）；
- observation.detail 携带 agent/goal/step 坐标——检索与回放的消费素材；
- 通过 vastacore 契约套件 EnvironmentAdapterContract（Story 1.1）。
"""

from __future__ import annotations

from vasta_protocols.protocols import (
    ENVIRONMENT_PROTOCOL_VERSION,
    Action,
    EnvironmentStatus,
    Observation,
)

_SIZE = 4
_GOAL = (3, 3)
_MOVES: dict[str, tuple[int, int]] = {
    "up": (-1, 0),
    "down": (1, 0),
    "left": (0, -1),
    "right": (0, 1),
}
_ACTIONS = list(_MOVES)


class GridWorldAdapter:
    protocol_version = ENVIRONMENT_PROTOCOL_VERSION
    deterministic = True

    def __init__(self) -> None:
        self._agent = (0, 0)
        self._steps = 0

    def _decision_observation(self) -> Observation:
        at_goal = self._agent == _GOAL
        return Observation(
            kind="terminal" if at_goal else "decision",
            available_actions=[] if at_goal else list(_ACTIONS),
            detail={
                "agent": list(self._agent),
                "goal": list(_GOAL),
                "step": self._steps,
                "size": _SIZE,
            },
        )

    async def reset(self, seed: int | None = None) -> Observation:
        self._agent = (0, 0)
        self._steps = 0
        return self._decision_observation()

    async def observe(self) -> Observation:
        return self._decision_observation()

    async def execute(self, action: Action) -> list[Observation]:
        if action.tool not in _MOVES:
            raise ValueError(f"unknown action {action.tool!r}; expected one of {_ACTIONS}")
        dr, dc = _MOVES[action.tool]
        r, c = self._agent
        nr, nc = min(max(r + dr, 0), _SIZE - 1), min(max(c + dc, 0), _SIZE - 1)
        self._agent = (nr, nc)
        self._steps += 1
        transition = Observation(
            kind="transition",
            detail={"from": [r, c], "to": [nr, nc], "step": self._steps},
        )
        return [transition, self._decision_observation()]

    async def status(self) -> EnvironmentStatus:
        return EnvironmentStatus(running=self._agent != _GOAL)
