"""vasta-storage：Evidence Store（CAS、事件库、派生索引、生命周期，Epic 1/2）。"""

from .images import Box, DiffResult, EvidenceImages, ImageInfo, InspectResult, PixelReading
from .lineage import DerivationRecord, LineageVerification, RecordVerification
from .sqlite_store import (
    DEFAULT_PROJECT,
    DEFAULT_TENANT,
    ArtifactCorruptedError,
    ArtifactNotFoundError,
    SqliteStorage,
)

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_PROJECT",
    "DEFAULT_TENANT",
    "ArtifactCorruptedError",
    "ArtifactNotFoundError",
    "Box",
    "DerivationRecord",
    "DiffResult",
    "EvidenceImages",
    "ImageInfo",
    "InspectResult",
    "LineageVerification",
    "PixelReading",
    "RecordVerification",
    "SqliteStorage",
]
