"""vasta-storage：Evidence Store（CAS、事件库、派生索引、生命周期，Epic 1/2）。"""

from .images import Box, DiffResult, EvidenceImages, ImageInfo, InspectResult, PixelReading
from .lineage import DerivationRecord, LineageVerification, RecordVerification
from .replay import (
    DeviationHit,
    RegressionTask,
    ReproBundle,
    Timeline,
    TimelineEntry,
    build_regression_task,
    export_repro_bundle,
    first_deviation,
    render_html,
    render_text,
    replay_non_model_events,
    timeline,
)
from .sqlite_store import (
    DEFAULT_PROJECT,
    DEFAULT_TENANT,
    ArtifactCorruptedError,
    ArtifactNotFoundError,
    SqliteStorage,
)

__version__ = "0.1.0"

__all__ = [
    "DeviationHit",
    "RegressionTask",
    "ReproBundle",
    "build_regression_task",
    "export_repro_bundle",
    "replay_non_model_events",
    "Timeline",
    "TimelineEntry",
    "render_html",
    "render_text",
    "first_deviation",
    "timeline",
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
