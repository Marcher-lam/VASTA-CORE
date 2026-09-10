"""统一事件序列器（Story 9.1，复盘 B1——五处手工构造点收敛为一）。

- 七字段信封构造 + seq 分配的唯一实现；生产写路径不得再手搓
  EventEnvelope（守卫测试 grep 锚定）。
- 双模式：
  - 系统流模式（默认，resync_each_emit=True）：每次发射前全量同步
    存储 max(seq)——多实例/桥接并发写同一系统流安全（cognition、
    registry、import、bridge 语义）；
  - 引擎快道模式（resync_each_emit=False）：seq 只在 append 成功后
    推进（不留洞）；跨实例冲突由 (run_id,seq) 唯一约束兜底为
    DuplicateEventError（runner 语义）。
- 位置：vasta-protocols（依赖根）——cognition/runtime/model-lab 核心
  包与 sdk 全部可用（AD-1）；仅依赖 envelope + ids，零新依赖。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .envelope import EventEnvelope
from .ids import new_event_id, now_utc


class EventSequencer:
    """统一信封构造 + seq 分配（AD-2：事件追加唯一写路径的构造侧）。"""

    def __init__(
        self,
        store: Any,
        run_id: str,
        *,
        tenant_id: str = "t-default",
        project_id: str = "p-default",
        clock: Callable[[], Any] | None = None,
        event_id_factory: Callable[[], str] | None = None,
        resync_each_emit: bool = True,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._tenant = tenant_id
        self._project = project_id
        self._clock = clock or now_utc
        self._new_id = event_id_factory or new_event_id
        self._resync = resync_each_emit
        self._last_seq = -1
        self._last_event_id: str | None = None

    @classmethod
    def resuming(
        cls,
        store: Any,
        run_id: str,
        *,
        last_seq: int,
        last_event_id: str | None,
        tenant_id: str = "t-default",
        project_id: str = "p-default",
        clock: Callable[[], Any] | None = None,
        event_id_factory: Callable[[], str] | None = None,
    ) -> EventSequencer:
        """引擎快道模式的重建入口：从已知最大 seq/父 id 续接。"""
        sequencer = cls(
            store, run_id, tenant_id=tenant_id, project_id=project_id,
            clock=clock, event_id_factory=event_id_factory,
            resync_each_emit=False,
        )
        sequencer._last_seq = last_seq
        sequencer._last_event_id = last_event_id
        return sequencer

    def _sync_from_store(self) -> None:
        """全量同步（系统流模式）——与既有四处实现的策略一致。"""
        try:
            for event in self._store.iter_run_events(self._run_id):
                if event.seq > self._last_seq:
                    self._last_seq = event.seq
                    self._last_event_id = event.event_id
        except Exception:  # noqa: BLE001——adapter 不支持时退化为内存序
            pass

    async def emit(self, type_: str, payload: dict[str, Any]) -> EventEnvelope:
        """构造并追加一个事件（构造 + seq 分配唯一路径）。"""
        if self._resync:
            self._sync_from_store()
        envelope = EventEnvelope.model_validate({
            "run_id": self._run_id,
            "seq": self._last_seq + 1,
            "type": type_,
            "parent_event_id": self._last_event_id,
            "ts": self._clock(),
            "tenant_id": self._tenant,
            "project_id": self._project,
            "event_id": self._new_id(),
            "payload": payload,
        })
        await self._store.append_event(envelope)
        # 快道/系统流通用：append 成功才推进（写失败不留洞）
        self._last_seq = envelope.seq
        self._last_event_id = envelope.event_id
        return envelope

    @property
    def last_seq(self) -> int:
        return self._last_seq

    @property
    def last_event_id(self) -> str | None:
        return self._last_event_id


__all__ = ["EventSequencer"]
