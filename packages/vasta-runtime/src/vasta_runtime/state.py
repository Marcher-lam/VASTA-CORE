"""Run 状态机（FR-004）。

created → started ⇄ paused → completed / failed / cancelled；
failed 兼容安全停止（预算超限，payload.safe_stop=true）。
"""

from __future__ import annotations

from enum import StrEnum

from vasta_protocols.errors import VastaError


class RunState(StrEnum):
    CREATED = "created"
    STARTED = "started"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}


_ALLOWED: dict[RunState, frozenset[RunState]] = {
    RunState.CREATED: frozenset({RunState.STARTED, RunState.CANCELLED}),
    RunState.STARTED: frozenset(
        {RunState.PAUSED, RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}
    ),
    RunState.PAUSED: frozenset({RunState.STARTED, RunState.FAILED, RunState.CANCELLED}),
    RunState.COMPLETED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.CANCELLED: frozenset(),
}


class InvalidTransitionError(VastaError):
    def __init__(self, current: RunState, target: RunState) -> None:
        super().__init__(
            code="run.invalid_transition",
            message=f"cannot transition run from {current.value} to {target.value}",
        )
        self.current = current
        self.target = target


def assert_transition(current: RunState, target: RunState) -> None:
    if target not in _ALLOWED[current]:
        raise InvalidTransitionError(current, target)
