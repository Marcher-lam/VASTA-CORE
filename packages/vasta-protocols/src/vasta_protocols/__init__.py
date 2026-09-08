"""vasta-protocols：VastaCore 依赖根（AD-1）。

事件信封 + 五协议接口 + 契约测试套件。本包对本仓库其他包零依赖
（import-linter 契约 "AD-1: vasta-protocols is the dependency root" 校验）。
"""

from .envelope import (
    ENVELOPE_SCHEMA_VERSION,
    EVENT_FAMILIES,
    EventEnvelope,
    InMemoryEventLog,
    VerificationOutcome,
)
from .errors import DuplicateEventError, VastaError
from .idempotency import canonical_args, canonical_args_hash, idempotency_key
from .ids import new_event_id, new_run_id, now_utc
from .protocols import (
    ENVIRONMENT_PROTOCOL_VERSION,
    MODEL_PROTOCOL_VERSION,
    STORAGE_PROTOCOL_VERSION,
    TOOL_PROTOCOL_VERSION,
    VERIFIER_PROTOCOL_VERSION,
)

__version__ = "0.1.0"

#: 协议族整体版本（FR-001：协议携带版本字段；semver，AD-9）。
PROTOCOL_VERSION = "0.1.0"

__all__ = [
    "ENVELOPE_SCHEMA_VERSION",
    "ENVIRONMENT_PROTOCOL_VERSION",
    "EVENT_FAMILIES",
    "InMemoryEventLog",
    "MODEL_PROTOCOL_VERSION",
    "PROTOCOL_VERSION",
    "STORAGE_PROTOCOL_VERSION",
    "TOOL_PROTOCOL_VERSION",
    "VERIFIER_PROTOCOL_VERSION",
    "DuplicateEventError",
    "EventEnvelope",
    "VastaError",
    "VerificationOutcome",
    "canonical_args",
    "canonical_args_hash",
    "idempotency_key",
    "new_event_id",
    "new_run_id",
    "now_utc",
]
