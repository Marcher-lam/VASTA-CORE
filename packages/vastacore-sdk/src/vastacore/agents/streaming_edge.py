"""实时流式环境与边缘协同（Story 11.13，FR-009，G5）。

流式输入与近数据端执行：

- **StreamingEnvironment**：事件序列输入按窗口成帧——帧级 CAS
  入证据库（``observation.stream_frame``——帧引用可溯）+ 帧内
  聚合摘要；窗口语义（时间窗 or 计数窗）；
- **EdgeBuffer**：边缘节点本地缓冲（断连期间累积帧）——连通后
  ``flush`` 批量回传（完整性校验：帧序连续 + 逐帧 CAS——缺口
  即拒，fail-closed）；
- **断连恢复语义**：复用 9.10 接管底座的形态——恢复时缺口检测
  （``run.gap_detected`` 留痕）而非静默丢帧；
- 流式与批量路径共存：StreamingEnvironment 是 EnvironmentAdapter
  的流式扩展（同一 Run 可混——帧事件与批量观察事件同流）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

_STREAM_RUN = "edge-stream"

#: 帧提交面：async (frame_bytes, frame_id) -> sha256（CAS 入库）。
FrameCommit = Callable[[bytes, str], Awaitable[str]]


class StreamFrame(BaseModel):
    """流式帧（窗口聚合产物）。"""

    model_config = ConfigDict(extra="forbid")

    frame_id: str
    seq: int = Field(ge=0, description="流内帧序（连续性锚）")
    event_count: int = Field(ge=0)
    payload_digest: str = Field(description="帧内容 SHA-256 摘要")
    cas_sha256: str | None = Field(
        default=None, description="CAS 入库哈希（提交后填充）")


class StreamingEnvironment:
    """流式环境：事件序列 → 窗口成帧 → 帧级 CAS。

    窗口语义：count_window（N 事件一帧）——时间窗属生产扩展
    （本 MVP 交计数窗）。"""

    def __init__(self, *, count_window: int = 10,
                 stream_id: str = "stream-1") -> None:
        if count_window < 1:
            raise VastaError(
                code="stream.bad_window",
                message=f"count_window 须 ≥1（得到 {count_window}）")
        self.count_window = count_window
        self.stream_id = stream_id
        self._buffer: list[dict[str, Any]] = []
        self._frame_seq = 0

    def push(self, event: dict[str, Any]) -> StreamFrame | None:
        """推入事件——窗口满即返回帧（否则 None 继续积累）。"""
        self._buffer.append(event)
        if len(self._buffer) >= self.count_window:
            return self._seal()
        return None

    def _seal(self) -> StreamFrame:
        digest = hashlib.sha256(
            json.dumps(self._buffer, sort_keys=True,
                       ensure_ascii=False).encode()).hexdigest()
        frame = StreamFrame(
            frame_id=f"{self.stream_id}:f{self._frame_seq}",
            seq=self._frame_seq, event_count=len(self._buffer),
            payload_digest=digest)
        self._frame_seq += 1
        self._buffer = []
        return frame

    async def commit_frame(
        self, store: Any, frame: StreamFrame,
        *, frame_commit: FrameCommit,
        tenant_id: str = "t-default", project_id: str = "p-default",
    ) -> StreamFrame:
        """帧级 CAS 入库 + ``observation.stream_frame`` 留痕。

        内容寻址锚定（Epic 11 评审修复——验证缺口 G1）：frame_commit
        返回的 sha 必须等于提交体的 SHA-256——任意返回值（stub/
        错位哈希）即拒，CAS 引用与帧内容强绑定。"""
        body = json.dumps({
            "frame_id": frame.frame_id, "seq": frame.seq,
            "event_count": frame.event_count,
            "payload_digest": frame.payload_digest,
        }, sort_keys=True).encode()
        sha = await frame_commit(body, frame.frame_id)
        expected_sha = hashlib.sha256(body).hexdigest()
        if sha != expected_sha:
            raise VastaError(
                code="stream.cas_mismatch",
                message=(f"帧 {frame.frame_id!r} CAS 返回哈希与提交体"
                         "不符——内容寻址锚定失败（拒绝存根/错位哈希）"),
            )
        sequencer = EventSequencer(
            store, _STREAM_RUN,
            tenant_id=tenant_id, project_id=project_id)
        await sequencer.emit("observation.stream_frame", {
            "stream_id": self.stream_id,
            "frame_id": frame.frame_id, "frame_seq": frame.seq,
            "event_count": frame.event_count,
            "frame_digest": frame.payload_digest,
            "artifact_refs": [sha],
        })
        return frame.model_copy(update={"cas_sha256": sha})


class EdgeBuffer:
    """边缘节点本地缓冲：断连累积 → 连通后批量回传。

    完整性校验：帧序连续（缺口即 ``run.gap_detected`` 留痕并拒
    ——fail-closed，复用 9.10 恢复语义的缺口检测形态）。

    Epic 11 评审修复（盲审 H3/M5、边界 E-1/E-2）：

    - 连续性锚随回传推进（``_next_expected_seq``）——第二次 flush
      不再以 0 为期望（断连-恢复-再断连可重复工作）；
    - 逐帧提交即逐帧出队：中途失败时已提交帧不重复提交（重试从
      失败帧续传——部分提交无重复入流）；
    - 同 seq 不同 digest 的重复缓冲即拒（前帧不可静默覆盖）；
    - flush 持锁——并发回传不产生同帧双提交。"""

    def __init__(self, edge_id: str) -> None:
        import asyncio

        self.edge_id = edge_id
        self._frames: dict[int, StreamFrame] = {}
        self._next_expected_seq = 0
        self._flush_lock = asyncio.Lock()

    def buffer(self, frame: StreamFrame) -> None:
        existing = self._frames.get(frame.seq)
        if existing is not None and \
                existing.payload_digest != frame.payload_digest:
            raise VastaError(
                code="run.duplicate_frame_seq",
                message=(f"边缘 {self.edge_id!r} 帧序 {frame.seq} 重复"
                         f"且 digest 不符（{existing.payload_digest[:8]}…"
                         f" vs {frame.payload_digest[:8]}…）"
                         "——前帧不可静默覆盖"),
            )
        self._frames[frame.seq] = frame

    async def flush(
        self, store: Any,
        *, stream_env: StreamingEnvironment,
        frame_commit: FrameCommit,
        tenant_id: str = "t-default", project_id: str = "p-default",
    ) -> list[StreamFrame]:
        """回传全部缓冲帧（序连续校验 → 逐帧 CAS 提交 → 出队）。

        失败语义：某帧提交异常即上抛——已提交帧已出队，重试从失败
        帧续传（不重复入流）。"""
        async with self._flush_lock:
            expected = self._next_expected_seq
            for seq in sorted(self._frames):
                if seq != expected:
                    sequencer = EventSequencer(
                        store, _STREAM_RUN,
                        tenant_id=tenant_id, project_id=project_id)
                    await sequencer.emit("run.gap_detected", {
                        "edge_id": self.edge_id,
                        "expected_seq": expected, "found_seq": seq,
                    })
                    raise VastaError(
                        code="run.gap_detected",
                        message=(f"边缘 {self.edge_id!r} 帧序缺口："
                                 f"期望 {expected} 实得 {seq}"
                                 "——缺口帧不可静默丢弃（9.10 恢复语义）"),
                    )
                expected += 1
            committed: list[StreamFrame] = []
            for seq in sorted(self._frames):
                frame = self._frames[seq]
                committed.append(await stream_env.commit_frame(
                    store, frame, frame_commit=frame_commit,
                    tenant_id=tenant_id, project_id=project_id))
                # 提交成功即出队——中途失败重试不重复提交已成功帧
                del self._frames[seq]
                self._next_expected_seq = seq + 1
            return committed


__all__ = ["EdgeBuffer", "StreamFrame", "StreamingEnvironment"]
