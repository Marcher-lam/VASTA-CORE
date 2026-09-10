"""vastacore-sdk：组装入口与便捷 API（AD-1 组装根）。"""

from ._version import __version__
from .agent import AgentSession, ContractTemplate, SessionSummary
from .approvals import (
    ApprovalRecord,
    is_approval_valid,
    record_approval,
    revoke_approval,
    search_approvals,
)
from .batch import (
    BatchRunSummary,
    SolvePolicyStandIn,
    TaskRunResult,
    VastaLabEnv,
    run_tasks_as_runs,
)
from .derive import DerivedRef, DeriverRegistry, default_registry, derive_on_demand
from .offline_eval import (
    ActionComparison,
    OfflineEvalReport,
    offline_evaluate,
    replay_bundle_verifiers,
)
from .probe import CapabilityReport, ProbeOutcome, probe_capabilities, save_capability_report
from .quickstart import RunSummary, quickstart
from .quotas import CostLedger, QuotaEnforcer, QuotaExceededError, QuotaSpec
from .release import (
    ReleaseResult,
    ReleaseStatus,
    RollbackResult,
    compare_shadow,
    get_canary_percent,
    get_release_status,
    promote_release,
    rollback_release,
    set_canary_percent,
)
from .router import CostEntry, ModelRouter, RouterError
from .scaffold import ScaffoldResult, generate_tool_project, run_tool_protocol_checks
from .scheduling import CronSpec, FireRecord, Scheduler, ScheduleSpec
from .service import VastaService, create_app, serve
from .timetravel import DerivedRecall, claim_as_of, derived_recall
from .toolproxy import ProxyToolAdapter, browser_action_proxy, browser_read_proxy, proxy_tool
from .trajectory import ImportSummary, import_trajectory
from .transactions import BatchResult, BatchStep, TransactionBatch, execute_batch
from .versioning import (
    PublishedRef,
    VersionRecord,
    publish_model_version,
    publish_policy_snapshot,
    version_as_of,
)

__all__ = [
    "ActionComparison",
    "AgentSession",
    "ApprovalRecord",
    "is_approval_valid",
    "record_approval",
    "revoke_approval",
    "search_approvals",
    "BatchRunSummary",
    "SolvePolicyStandIn",
    "TaskRunResult",
    "VastaLabEnv",
    "run_tasks_as_runs",
    "CapabilityReport",
    "ProbeOutcome",
    "ProxyToolAdapter",
    "ReleaseResult",
    "ReleaseStatus",
    "RollbackResult",
    "compare_shadow",
    "get_canary_percent",
    "get_release_status",
    "promote_release",
    "rollback_release",
    "set_canary_percent",
    "browser_action_proxy",
    "browser_read_proxy",
    "proxy_tool",
    "probe_capabilities",
    "publish_model_version",
    "publish_policy_snapshot",
    "save_capability_report",
    "version_as_of",
    "ContractTemplate",
    "DerivedRef",
    "DeriverRegistry",
    "default_registry",
    "derive_on_demand",
    "BatchResult",
    "BatchStep",
    "TransactionBatch",
    "execute_batch",
    "CostLedger",
    "QuotaEnforcer",
    "QuotaExceededError",
    "QuotaSpec",
    "CronSpec",
    "FireRecord",
    "ScheduleSpec",
    "Scheduler",
    "DerivedRecall",
    "PublishedRef",
    "VersionRecord",
    "claim_as_of",
    "derived_recall",
    "CostEntry",
    "ModelRouter",
    "OfflineEvalReport",
    "offline_evaluate",
    "replay_bundle_verifiers",
    "RouterError",
    "ImportSummary",
    "ScaffoldResult",
    "VastaService",
    "create_app",
    "generate_tool_project",
    "run_tool_protocol_checks",
    "serve",
    "RunSummary",
    "SessionSummary",
    "import_trajectory",
    "quickstart",
    "__version__",
]
