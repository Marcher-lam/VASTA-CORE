"""vasta-storage：Evidence Store（CAS、事件库、派生索引、生命周期，Epic 1/2）。"""

from .images import Box, DiffResult, EvidenceImages, ImageInfo, InspectResult, PixelReading
from .lifecycle import (
    DeletionBlocker,
    DeletionResult,
    LifecyclePolicy,
    classify_artifacts,
    place_legal_hold,
    release_legal_hold,
    request_deletion,
)
from .lineage import DerivationRecord, LineageVerification, RecordVerification
from .pg_store import PostgresEventStore
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
from .s3_blobs import S3BlobStore
from .sqlite_store import (
    DEFAULT_PROJECT,
    DEFAULT_TENANT,
    ArtifactCorruptedError,
    ArtifactNotFoundError,
    SqliteStorage,
)

__version__ = "0.1.0"

__all__ = [
    "DeletionBlocker",
    "DeletionResult",
    "LifecyclePolicy",
    "PostgresEventStore",
    "S3BlobStore",
    "classify_artifacts",
    "place_legal_hold",
    "release_legal_hold",
    "request_deletion",
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
