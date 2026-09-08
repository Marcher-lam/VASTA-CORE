"""vasta-contracts：ActionContract 与核验器协议实现（Epic 3）。"""

from .contract import (
    REQUIRED_SEGMENTS,
    ActionContract,
    ChainReport,
    ContractIncompleteError,
    Prediction,
    SixSegmentAudit,
    audit_six_segment,
    make_complete_contract,
    missing_segments,
)

__version__ = "0.1.0"

__all__ = [
    "ActionContract",
    "ChainReport",
    "ContractIncompleteError",
    "Prediction",
    "REQUIRED_SEGMENTS",
    "SixSegmentAudit",
    "audit_six_segment",
    "make_complete_contract",
    "missing_segments",
]
