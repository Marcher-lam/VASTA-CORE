"""模型实验室供给点：安全墙钟（AD-15）与 world_model.* 事件发射。"""

from __future__ import annotations

from typing import Any

from vasta_protocols.envelope import EventEnvelope
from vasta_protocols.ids import new_event_id, now_utc


def default_monotonic() -> float:
    """安全墙钟供给点（规划超时上限属 AD-15 强制机制）。"""
    import time

    return time.monotonic()


async def emit_world_model_event(
    store: Any, type_: str, payload: dict[str, Any]
) -> EventEnvelope:
    """以 cognition run 落 world_model.* 事件（因果链续接）。"""
    events = list(store.iter_run_events("cognition"))
    seq = (events[-1].seq + 1) if events else 0
    parent = events[-1].event_id if events else None
    envelope = EventEnvelope.model_validate(
        {
            "run_id": "cognition",
            "seq": seq,
            "type": type_,
            "parent_event_id": parent,
            "ts": now_utc(),
            "tenant_id": "t-default",
            "project_id": "p-default",
            "event_id": new_event_id(),
            "payload": payload,
        }
    )
    await store.append_event(envelope)
    return envelope
