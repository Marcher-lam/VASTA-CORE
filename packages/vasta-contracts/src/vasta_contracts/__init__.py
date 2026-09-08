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
from .verifiers import (
    INVARIANT_OPS,
    InvariantRule,
    InvariantVerifier,
    ReadBackVerifier,
    SchemaVerifier,
    VerificationPipeline,
)

__version__ = "0.1.0"

__all__ = [
    "ActionContract",
    "INVARIANT_OPS",
    "InvariantRule",
    "InvariantVerifier",
    "ReadBackVerifier",
    "SchemaVerifier",
    "VerificationPipeline",
    "ChainReport",
    "ContractIncompleteError",
    "Prediction",
    "REQUIRED_SEGMENTS",
    "SixSegmentAudit",
    "audit_six_segment",
    "make_complete_contract",
    "missing_segments",
]
