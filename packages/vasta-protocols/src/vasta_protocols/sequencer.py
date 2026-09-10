"""统一事件序列器（Story 9.1，复盘 B1——五处手工构造点收敛为一）。

- 七字段信封构造 + seq 分配的唯一实现；生产写路径不得再手搓
  EventEnvelope（守卫测试 grep 锚定）。
- 双模式：
  - 系统流模式（默认，resync_each_emit=True）：每次发射前同步存储
    尾部（优先 ``last_event_info`` 点查，退化全量扫描）——多实例/
    桥接并发写同一系统流安全（cognition、registry、import、bridge
    语义）；
  - 引擎快道模式（resync_each_emit=False）：seq 只在 append 成功后
    推进（不留洞）；跨实例冲突由 (run_id,seq) 唯一约束兜底为
    DuplicateEventError，撞号时同步一次存储后续接重试（自愈——
    resume 时点落后不再永久卡死；runner 语义）。
- emit 全程持实例锁——同一 sequencer 的并发 emit 串行化（评审修复：
    sync 与 append 之间的 await 交错窗口不再产生必败一路）。
- 位置：vasta-protocols（依赖根）——cognition/runtime/model-lab 核心
  包与 sdk 全部可用（AD-1）；仅依赖 envelope + ids，零新依赖。
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any

from .envelope import EventEnvelope
from .errors import DuplicateEventError
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
        # 延迟绑定（Python≥3.10：首次使用时绑定运行循环）
        self._emit_lock = asyncio.Lock()

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

    def _absorb(self, seq: int, event_id: str | None) -> None:
        """吸收存储尾部（只前进——本地已见更大 seq 时不回退）。"""
        if seq > self._last_seq:
            self._last_seq = seq
            self._last_event_id = event_id

    async def _sync_from_store(self) -> None:
        """同步存储尾部（系统流模式 / 快道冲突自愈）。

        优先级：``last_event_info`` 点查（O(1)——评审修复 O(n²) 全量
        重扫）→ ``aiter_run_events``（PG 等异步原生 store）→ 同步
        ``iter_run_events`` 全量扫描（不支持前两者的端口）。
        端口缺失（AttributeError/NotImplementedError）退化为内存序；
        其他异常（如存储故障）上抛——不静默吞（评审修复：
        pg.sync_iter_in_loop 类错误必须暴露而非假性成功）。"""
        info_fn = getattr(self._store, "last_event_info", None)
        if callable(info_fn):
            info = info_fn(self._run_id)
            if inspect.isawaitable(info):
                info = await info
            if info is not None:
                self._absorb(int(info[0]), info[1])
            return
        aiter_fn = getattr(self._store, "aiter_run_events", None)
        if callable(aiter_fn):
            for event in await aiter_fn(self._run_id):
                self._absorb(event.seq, event.event_id)
            return
        try:
            for event in self._store.iter_run_events(self._run_id):
                self._absorb(event.seq, event.event_id)
        except (AttributeError, NotImplementedError, TypeError):
            pass  # 端口不支持——退化为内存序（FakeStore 最小实现）

    def _build(self, type_: str, payload: dict[str, Any]) -> EventEnvelope:
        return EventEnvelope.model_validate({
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

    async def emit(self, type_: str, payload: dict[str, Any]) -> EventEnvelope:
        """构造并追加一个事件（构造 + seq 分配唯一路径）。

        append 成功才推进本地 seq/event_id（写失败不留洞）；
        快道模式撞号（DuplicateEventError）时同步存储尾部并重试一次
        （跨实例续接自愈——二次仍撞则上抛）。
        **rerun 例外**：本地一无所知（last_seq<0）即撞号 = 声称空流
        对非空流从头重放（同 run_id 重跑）——上抛不自愈
        （quickstart.rerun_conflict 检测依赖此路径）。"""
        async with self._emit_lock:
            if self._resync:
                await self._sync_from_store()
            try:
                envelope = self._build(type_, payload)
                await self._store.append_event(envelope)
            except DuplicateEventError:
                if self._resync or self._last_seq < 0:
                    # 系统流模式刚同步过仍撞（真并发写），或
                    # 快道声称空流撞非空流（rerun）——上抛
                    raise
                await self._sync_from_store()  # 快道：吸收他实例进度
                envelope = self._build(type_, payload)
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
