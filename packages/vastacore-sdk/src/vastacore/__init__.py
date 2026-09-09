"""vastacore-sdk：组装入口与便捷 API（AD-1 组装根）。"""

from ._version import __version__
from .agent import AgentSession, ContractTemplate, SessionSummary
from .probe import CapabilityReport, ProbeOutcome, probe_capabilities, save_capability_report
from .quickstart import RunSummary, quickstart
from .router import CostEntry, ModelRouter, RouterError
from .scaffold import ScaffoldResult, generate_tool_project, run_tool_protocol_checks
from .service import VastaService, create_app, serve
from .timetravel import DerivedRecall, claim_as_of, derived_recall
from .trajectory import ImportSummary, import_trajectory
from .versioning import (
    PublishedRef,
    VersionRecord,
    publish_model_version,
    publish_policy_snapshot,
    version_as_of,
)

__all__ = [
    "AgentSession",
    "CapabilityReport",
    "ProbeOutcome",
    "probe_capabilities",
    "publish_model_version",
    "publish_policy_snapshot",
    "save_capability_report",
    "version_as_of",
    "ContractTemplate",
    "DerivedRecall",
    "PublishedRef",
    "VersionRecord",
    "claim_as_of",
    "derived_recall",
    "CostEntry",
    "ModelRouter",
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
