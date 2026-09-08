"""vasta-runtime：Run 循环、Supervisor、Tool Gateway、RunContext（Epic 1/3）。"""

from .budget import Budget, BudgetExceededError, BudgetKind, BudgetSnapshot, BudgetTracker
from .checkpoint import Checkpoint, ObservationSignature
from .contracted import PolicyDeniedError, PolicyOutcome
from .gateway import (
    DuplicateToolError,
    ToolGateway,
    ToolNotRegisteredError,
    canonical_args_hash,
    idempotency_key,
)
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
    "Budget",
    "BudgetExceededError",
    "BudgetKind",
    "BudgetSnapshot",
    "BudgetTracker",
    "Checkpoint",
    "DuplicateToolError",
    "Escalation",
    "EscalationReason",
    "InvalidTransitionError",
    "ObservationCollector",
    "ObservationSignature",
    "PolicyDeniedError",
    "PolicyOutcome",
    "ResumeReport",
    "RunConfig",
    "RunContext",
    "RunEngine",
    "RunState",
    "Supervisor",
    "SupervisorConfig",
    "SupervisorEscalationError",
    "TerminalObservationError",
    "ToolGateway",
    "ToolNotRegisteredError",
    "assert_transition",
    "canonical_args_hash",
    "idempotency_key",
]
