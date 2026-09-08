"""StorageAdapter 契约：事件唯一性（AD-2）与 Artifact 先落盘后引用（AD-3）。"""

from __future__ import annotations

import pytest

from ..envelope import EventEnvelope
from ..errors import DuplicateEventError
from ..ids import new_event_id
from ..protocols import StorageAdapter
from .event_envelope import make_envelope


class StorageAdapterContract:
    def make_adapter(self) -> StorageAdapter:
        raise NotImplementedError("storage package must provide make_adapter()")

    async def test_event_roundtrip(self) -> None:
        store = self.make_adapter()
        env = make_envelope()
        await store.append_event(env)
        assert await store.get_event(env.run_id, 0) == env

    async def test_duplicate_seq_rejected(self) -> None:
        store = self.make_adapter()
        env = make_envelope()
        await store.append_event(env)
        dup = EventEnvelope.model_validate(
            {**env.model_dump(), "event_id": new_event_id()}
        )
        with pytest.raises(DuplicateEventError):
            await store.append_event(dup)

    async def test_artifact_roundtrip_verified_by_hash(self) -> None:
        store = self.make_adapter()
        payload = b"vasta-evidence"
        sha = await store.save_artifact(payload)
        import hashlib

        assert sha == hashlib.sha256(payload).hexdigest()
        assert await store.get_artifact(sha) == payload

    async def test_unknown_artifact_raises(self) -> None:
        store = self.make_adapter()
        with pytest.raises(Exception):  # noqa: B017 (具体异常类型由实现契约化)
            await store.get_artifact("0" * 64)
