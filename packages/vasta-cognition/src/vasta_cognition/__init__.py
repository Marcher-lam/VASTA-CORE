"""vasta-cognition：Claim 图、记忆、冲突、晋升、上下文装配（Epic 5）。"""

from .cognition import (
    MVP_MEMORY_TYPES,
    Claim,
    ClaimStatus,
    CognitionService,
    Conflict,
    ConflictService,
    ContextBuilder,
    ContextBundle,
    ContextSelection,
    MemoryType,
)

__version__ = "0.1.0"

__all__ = [
    "Claim",
    "ClaimStatus",
    "Conflict",
    "ConflictService",
    "ContextBuilder",
    "ContextBundle",
    "ContextSelection",
    "CognitionService",
    "MVP_MEMORY_TYPES",
    "MemoryType",
]
