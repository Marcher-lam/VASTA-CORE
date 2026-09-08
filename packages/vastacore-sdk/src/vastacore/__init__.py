"""vastacore-sdk：组装入口与便捷 API（AD-1 组装根）。"""

from ._version import __version__
from .quickstart import RunSummary, quickstart

__all__ = ["RunSummary", "quickstart", "__version__"]
