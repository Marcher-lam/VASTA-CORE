"""Story 11.13：实时流式环境与边缘协同（FR-009，G5）。"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.agents.streaming_edge import (
    EdgeBuffer,
    StreamFrame,
    StreamingEnvironment,
)


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


async def cas_commit(body: bytes, frame_id: str) -> str:
    import hashlib

    return hashlib.sha256(body).hexdigest()


def frame(seq: int, count: int = 5) -> StreamFrame:
    import hashlib

    return StreamFrame(
        frame_id=f"s:f{seq}", seq=seq, event_count=count,
        payload_digest=hashlib.sha256(b"x").hexdigest())


class TestStreamingEnvironment:
    def test_count_window_frames(self) -> None:
        """AC：事件序列按窗口成帧。"""
        env = StreamingEnvironment(count_window=3, stream_id="s")
        assert env.push({"e": 1}) is None
        assert env.push({"e": 2}) is None
        f = env.push({"e": 3})  # 窗口满
        assert f is not None
        assert f.seq == 0 and f.event_count == 3

    def test_sequential_frames(self) -> None:
        env = StreamingEnvironment(count_window=2, stream_id="s")
        f1 = env.push({"e": 1}) or env.push({"e": 1})
        f2 = env.push({"e": 1}) or env.push({"e": 1})
        assert (f1.seq, f2.seq) == (0, 1)

    def test_bad_window_rejected(self) -> None:
        with pytest.raises(VastaError):
            StreamingEnvironment(count_window=0)

    async def test_frame_cas_and_trace(self, store) -> None:
        """AC：帧级 CAS 入证据库 + observation.stream_frame 留痕。"""
        env = StreamingEnvironment(count_window=2, stream_id="s")
        f = env.push({"e": 1})
        f = env.push({"e": 2})
        committed = await env.commit_frame(
            store, f, frame_commit=cas_commit,
            tenant_id="t", project_id="p")
        assert committed.cas_sha256 is not None
        events = [e for e in store.iter_run_events(
            "edge-stream", tenant_id="t", project_id="p")
            if e.type == "observation.stream_frame"]
        assert events[-1].payload["frame_id"] == "s:f0"
        assert events[-1].payload["artifact_refs"] == \
            [committed.cas_sha256]


class TestEdgeBuffer:
    async def test_flush_commits_in_order(self, store) -> None:
        """AC：断连累积 → 连通后回传合并（序连续全提交）。"""
        env = StreamingEnvironment(count_window=1, stream_id="s")
        buf = EdgeBuffer("edge-1")
        for seq in range(3):
            buf.buffer(frame(seq))
        committed = await buf.flush(
            store, stream_env=env, frame_commit=cas_commit,
            tenant_id="t", project_id="p")
        assert [f.seq for f in committed] == [0, 1, 2]
        assert all(f.cas_sha256 for f in committed)

    async def test_gap_detected_and_rejected(self, store) -> None:
        """AC：断连恢复语义——帧序缺口即拒（不静默丢帧）+
        run.gap_detected 留痕。"""
        env = StreamingEnvironment(count_window=1, stream_id="s")
        buf = EdgeBuffer("edge-2")
        buf.buffer(frame(0))
        buf.buffer(frame(2))  # 缺 1
        with pytest.raises(VastaError) as e:
            await buf.flush(store, stream_env=env,
                            frame_commit=cas_commit,
                            tenant_id="t", project_id="p")
        assert e.value.code == "run.gap_detected"
        events = [e for e in store.iter_run_events(
            "edge-stream", tenant_id="t", project_id="p")
            if e.type == "run.gap_detected"]
        assert events[-1].payload["expected_seq"] == 1
        assert events[-1].payload["found_seq"] == 2

    async def test_flush_empty_noop(self, store) -> None:
        env = StreamingEnvironment(count_window=1)
        buf = EdgeBuffer("edge-3")
        assert await buf.flush(
            store, stream_env=env, frame_commit=cas_commit,
            tenant_id="t", project_id="p") == []
