"""vasta-model-lab：世界模型沙箱、验证、规划（Epic 6）。"""

from .lab import (
    DSLWorldModel,
    MetaDecision,
    MetaSignals,
    PlanCaps,
    PythonWorldModel,
    RuleSet,
    SandboxExecutor,
    Trajectory,
    ValidationReport,
    WorldModelBridge,
    WorldModelManifest,
    decide_meta,
    emit_meta_decision,
    plan_bfs,
    validate_model,
)
from .pool import (
    PodmanBackend,
    SandboxPool,
    SubprocessBackend,
    make_sandbox_pool,
)

__version__ = "0.1.0"

__all__ = [
    "DSLWorldModel",
    "MetaDecision",
    "MetaSignals",
    "PlanCaps",
    "PythonWorldModel",
    "RuleSet",
    "SandboxExecutor",
    "SandboxPool",
    "PodmanBackend",
    "SubprocessBackend",
    "make_sandbox_pool",
    "Trajectory",
    "ValidationReport",
    "WorldModelBridge",
    "WorldModelManifest",
    "decide_meta",
    "emit_meta_decision",
    "plan_bfs",
    "validate_model",
]
