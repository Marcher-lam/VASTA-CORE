"""vasta-model-lab 门面（Story 8.13 拆分后公共 API 不变）。

实现分布于 manifest/dsl/python_model/sandbox/validation/meta/planner/bridge
八模块；本文件仅再导出——`from vasta_model_lab import X` 与
`from vasta_model_lab.lab import X` 双路径均可用（`__all__` 原样保留）。
"""

from __future__ import annotations

from .bridge import WorldModelBridge
from .dsl import DSLWorldModel, RuleSet
from .manifest import Observation_, WorldModelManifest
from .meta import MetaDecision, MetaSignals, decide_meta, emit_meta_decision
from .planner import PlanCaps, plan_bfs
from .python_model import ALLOWED_IMPORTS, PythonWorldModel
from .sandbox import SandboxExecutor
from .validation import Trajectory, ValidationReport, validate_model

#: 模型实验室工具版本（历史归属本文件顶层，门面保持）。
MODEL_LAB_VERSION = "vasta-model-lab/0.1"

__all__ = [
    "ALLOWED_IMPORTS",
    "DSLWorldModel",
    "MetaDecision",
    "MetaSignals",
    "MODEL_LAB_VERSION",
    "Observation_",
    "PlanCaps",
    "PythonWorldModel",
    "RuleSet",
    "SandboxExecutor",
    "Trajectory",
    "ValidationReport",
    "WorldModelManifest",
    "WorldModelBridge",
    "decide_meta",
    "emit_meta_decision",
    "plan_bfs",
    "validate_model",
]
