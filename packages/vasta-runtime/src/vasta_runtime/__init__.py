"""vasta-runtime：Run 循环、Supervisor、Tool Gateway、RunContext（Epic 1/3）。"""

from .budget import Budget, BudgetExceededError, BudgetKind, BudgetSnapshot, BudgetTracker
from .checkpoint import Checkpoint, ObservationSignature
from .contracted import PolicyDeniedError, PolicyOutcome
from .control import (
    HumanControlMixin,
    RevocationError,
    TakeoverRequiredError,
)
from .gateway import (
    DuplicateToolError,
    ToolGateway,
    ToolNotRegisteredError,
    canonical_args_hash,
    idempotency_key,
)
from .observation import ObservationCollector, TerminalObservationError
from .recovery import (
    FaultClass,
    RecoveryDecision,
    RecoveryInput,
    RecoveryLimitExceededError,
    RecoveryPolicy,
    RecoveryTracker,
)
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
    "HumanControlMixin",
    "RevocationError",
    "TakeoverRequiredError",
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
    "FaultClass",
    "PolicyDeniedError",
    "RecoveryDecision",
    "RecoveryInput",
    "RecoveryLimitExceededError",
    "RecoveryPolicy",
    "RecoveryTracker",
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
