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
        """帧级 CAS 入库 + ``observation.stream_frame`` 留痕。"""
        body = json.dumps({
            "frame_id": frame.frame_id, "seq": frame.seq,
            "event_count": frame.event_count,
            "payload_digest": frame.payload_digest,
        }, sort_keys=True).encode()
        sha = await frame_commit(body, frame.frame_id)
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
    ——fail-closed，复用 9.10 恢复语义的缺口检测形态）。"""

    def __init__(self, edge_id: str) -> None:
        self.edge_id = edge_id
        self._frames: dict[int, StreamFrame] = {}

    def buffer(self, frame: StreamFrame) -> None:
        self._frames[frame.seq] = frame

    async def flush(
        self, store: Any,
        *, stream_env: StreamingEnvironment,
        frame_commit: FrameCommit,
        tenant_id: str = "t-default", project_id: str = "p-default",
    ) -> list[StreamFrame]:
        """回传全部缓冲帧（序连续校验 → 逐帧 CAS 提交）。"""
        seqs = sorted(self._frames)
        for expected, actual in enumerate(seqs):
            if actual != expected:
                sequencer = EventSequencer(
                    store, _STREAM_RUN,
                    tenant_id=tenant_id, project_id=project_id)
                await sequencer.emit("run.gap_detected", {
                    "edge_id": self.edge_id,
                    "expected_seq": expected, "found_seq": actual,
                })
                raise VastaError(
                    code="run.gap_detected",
                    message=(f"边缘 {self.edge_id!r} 帧序缺口："
                             f"期望 {expected} 实得 {actual}"
                             "——缺口帧不可静默丢弃（9.10 恢复语义）"),
                )
        committed: list[StreamFrame] = []
        for seq in seqs:
            frame = self._frames[seq]
            committed.append(await stream_env.commit_frame(
                store, frame, frame_commit=frame_commit,
                tenant_id=tenant_id, project_id=project_id))
        self._frames.clear()
        return committed


__all__ = ["EdgeBuffer", "StreamFrame", "StreamingEnvironment"]
