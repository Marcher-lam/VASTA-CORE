"""vasta-policy：策略引擎、风险分级、自治等级（Epic 3）。"""

from .policy import (
    DEFAULT_RISK_POLICY,
    ApprovalRequestedError,
    Decision,
    PolicyDecision,
    PolicyEngine,
    Rule,
    fail_closed_fallback,
)

__version__ = "0.1.0"

__all__ = [
    "ApprovalRequestedError",
    "DEFAULT_RISK_POLICY",
    "Decision",
    "PolicyDecision",
    "PolicyEngine",
    "Rule",
    "fail_closed_fallback",
]
