"""vasta-eval：消融、门禁、复现包、负载校准（Epic 7）。"""

from .evaluation import (
    ABLATION_GROUPS,
    GROUP_FLAGS,
    AgentSimulator,
    EvaluationConfig,
    EvaluationReport,
    GroupReport,
    TaskResult,
    VastaLabTask,
    generate_tasks,
    make_config,
    run_ablation,
    verify_config_complete,
)

__version__ = "0.1.0"

__all__ = [
    "ABLATION_GROUPS",
    "AgentSimulator",
    "EvaluationConfig",
    "EvaluationReport",
    "GROUP_FLAGS",
    "GroupReport",
    "TaskResult",
    "VastaLabTask",
    "generate_tasks",
    "make_config",
    "run_ablation",
    "verify_config_complete",
]
