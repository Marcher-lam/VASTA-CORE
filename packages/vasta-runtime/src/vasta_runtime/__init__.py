"""vasta-runtime：Run 循环、Supervisor、Tool Gateway、RunContext（Epic 1/3）。"""

from .budget import Budget, BudgetExceededError, BudgetKind, BudgetSnapshot, BudgetTracker
from .checkpoint import Checkpoint, ObservationSignature
from .runner import ResumeReport, RunConfig, RunEngine
from .state import InvalidTransitionError, RunState, assert_transition

__version__ = "0.1.0"

__all__ = [
    "Budget",
    "BudgetExceededError",
    "BudgetKind",
    "BudgetSnapshot",
    "BudgetTracker",
    "Checkpoint",
    "InvalidTransitionError",
    "ObservationSignature",
    "ResumeReport",
    "RunConfig",
    "RunEngine",
    "RunState",
    "assert_transition",
]
