"""StorageAdapter 协议（Evidence Store 端口，蓝图 §18.1 Storage 侧）。

AD-2：事件追加唯一写路径，(run_id, seq) 唯一；
AD-3：Artifact 先持久写入并校验哈希，之后才允许事件引用。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from ..envelope import EventEnvelope

#: Storage 协议版本。
STORAGE_PROTOCOL_VERSION = "0.1.0"


@runtime_checkable
class StorageAdapter(Protocol):
    """存储端口。SQLite/CAS 实现于 vasta-storage（Story 1.4），
    本协议定义其必须满足的行为；契约见 contract_suites.storage。"""

    protocol_version: str

    async def append_event(self, envelope: EventEnvelope) -> EventEnvelope:
        """追加事件；(run_id, seq) 冲突必须拒绝（AD-2）。"""
        ...

    async def get_event(self, run_id: str, seq: int) -> EventEnvelope: ...

    def iter_run_events(self, run_id: str) -> Iterator[EventEnvelope]: ...

    async def save_artifact(
        self,
        payload: bytes,
        *,
        mime: str | None = None,
        source: str | None = None,
        tenant_id: str = "t-default",
        project_id: str = "p-default",
    ) -> str:
        """持久写入载荷并返回 sha256（AD-3：哈希校验完成后才可被事件引用）。

        元数据/作用域参数为可选扩展（AD-9 minor）：实现方至少必须支持
        纯 payload 调用；支持元数据的实现按参数落库。"""
        ...

    async def get_artifact(self, sha256: str) -> bytes:
        """按哈希取回并校验载荷（FR-011 后果）。"""
        ...
