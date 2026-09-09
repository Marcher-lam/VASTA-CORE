"""vastacore-sdk：组装入口与便捷 API（AD-1 组装根）。"""

from ._version import __version__
from .agent import AgentSession, ContractTemplate, SessionSummary
from .probe import CapabilityReport, ProbeOutcome, probe_capabilities, save_capability_report
from .quickstart import RunSummary, quickstart
from .router import CostEntry, ModelRouter, RouterError
from .scaffold import ScaffoldResult, generate_tool_project, run_tool_protocol_checks
from .service import VastaService, create_app, serve
from .trajectory import ImportSummary, import_trajectory

__all__ = [
    "AgentSession",
    "CapabilityReport",
    "ProbeOutcome",
    "probe_capabilities",
    "save_capability_report",
    "ContractTemplate",
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
