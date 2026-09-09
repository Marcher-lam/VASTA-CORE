"""vastacore-sdk：组装入口与便捷 API（AD-1 组装根）。"""

from ._version import __version__
from .agent import AgentSession, ContractTemplate, SessionSummary
from .quickstart import RunSummary, quickstart
from .service import VastaService, create_app, serve
from .trajectory import ImportSummary, import_trajectory

__all__ = [
    "AgentSession",
    "ContractTemplate",
    "ImportSummary",
    "VastaService",
    "create_app",
    "serve",
    "RunSummary",
    "SessionSummary",
    "import_trajectory",
    "quickstart",
    "__version__",
]
