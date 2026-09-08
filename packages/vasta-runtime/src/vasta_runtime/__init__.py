"""vasta-runtime：Run 循环、Supervisor、Tool Gateway、RunContext（Epic 1/3）。"""

from .budget import Budget, BudgetExceededError, BudgetKind, BudgetSnapshot, BudgetTracker
from .checkpoint import Checkpoint, ObservationSignature
from .contracted import PolicyDeniedError, PolicyOutcome
from .observation import ObservationCollector, TerminalObservationError
from .runcontext import RunContext
from .runner import ResumeReport, RunConfig, RunEngine
from .state import InvalidTransitionError, RunState, assert_transition
from .supervisor import (
    Escalation,
    EscalationReason,
    Supervisor,
    SupervisorConfig,
    SupervisorEscalationError,
)

__version__ = "0.1.0"

__all__ = [
    "PolicyDeniedError",
    "PolicyOutcome",
    "Budget",
    "BudgetExceededError",
    "BudgetKind",
    "BudgetSnapshot",
    "BudgetTracker",
    "Checkpoint",
    "Escalation",
    "EscalationReason",
    "InvalidTransitionError",
    "ObservationCollector",
    "ObservationSignature",
    "ResumeReport",
    "RunConfig",
    "RunContext",
    "RunEngine",
    "RunState",
    "Supervisor",
    "SupervisorConfig",
    "SupervisorEscalationError",
    "TerminalObservationError",
    "assert_transition",
]
