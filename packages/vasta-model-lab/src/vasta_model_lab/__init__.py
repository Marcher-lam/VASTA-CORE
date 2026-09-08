"""vasta-model-lab：世界模型沙箱、验证、规划（Epic 6）。"""

from .lab import (
    DSLWorldModel,
    MetaDecision,
    MetaSignals,
    PlanCaps,
    PlanningLimitExceededError,
    PythonWorldModel,
    RuleSet,
    SandboxExecutor,
    Trajectory,
    ValidationReport,
    WorldModelBridge,
    WorldModelManifest,
    decide_meta,
    plan_bfs,
    validate_model,
)

__version__ = "0.1.0"

__all__ = [
    "DSLWorldModel",
    "MetaDecision",
    "MetaSignals",
    "PlanCaps",
    "PlanningLimitExceededError",
    "PythonWorldModel",
    "RuleSet",
    "SandboxExecutor",
    "Trajectory",
    "ValidationReport",
    "WorldModelBridge",
    "WorldModelManifest",
    "decide_meta",
    "plan_bfs",
    "validate_model",
]
