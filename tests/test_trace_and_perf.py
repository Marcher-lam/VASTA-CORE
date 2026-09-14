"""NFR-010 trace 贯穿 + NFR-005 性能开销可测（终检 §六-3 补齐）。"""

from __future__ import annotations

import time

from vasta_protocols.sequencer import EventSequencer
from vasta_protocols.telemetry import (
    bind_trace_id,
    current_trace_id,
    trace_span,
)
from vasta_storage import SqliteStorage


class TestTraceContext:
    """NFR-010：trace_id 贯穿事件（OTel 兼容最小接线）。"""

    def test_span_sets_and_clears(self) -> None:
        assert current_trace_id() is None
        with trace_span("trace-abc"):
            assert current_trace_id() == "trace-abc"
            with trace_span("trace-inner"):  # 嵌套覆盖
                assert current_trace_id() == "trace-inner"
            assert current_trace_id() == "trace-abc"
        assert current_trace_id() is None

    def test_sequencer_injects_trace_id(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        try:
            seq = EventSequencer(store, "trace-run", tenant_id="t",
                                 project_id="p")
            with trace_span("trace-xyz"):
                import asyncio

                envelope = asyncio.run(
                    seq.emit("run.created", {}))
            assert envelope.trace_id == "trace-xyz"
            # span 外发射不携带
            envelope2 = asyncio.run(seq.emit("run.started", {}))
            assert envelope2.trace_id is None
            # 落库往返保持
            events = list(store.iter_run_events("trace-run",
                                                tenant_id="t",
                                                project_id="p"))
            assert events[0].trace_id == "trace-xyz"
            assert events[1].trace_id is None
        finally:
            store.close()

    def test_external_provider_binding(self) -> None:
        try:
            bind_trace_id(lambda: "otel-provided")
            assert current_trace_id() == "otel-provided"
        finally:
            bind_trace_id(None)


class TestOverheadSmoke:
    """NFR-005（工程内档）：平台开销可测且有量级护栏。

    蓝图 §21 目标（非模型编排 P95<500ms）属地化负载验证；工程内
    护栏取数量级宽松上限（单动作六段链 < 2s、事件追加吞吐
    > 200/s）——防三个数量级级回归，不作达标断言。"""

    def test_six_segment_chain_latency_smoke(self, tmp_path) -> None:
        import asyncio

        from tests.test_agent_sdk import STATUS_CONTRACT, SetStatusTool, TodoEnv
        from vastacore.execution.agent import AgentSession

        async def run() -> list[str]:
            session = await AgentSession.create(
                env=TodoEnv(), tools=[SetStatusTool()],
                contracts={"set_status": STATUS_CONTRACT},
                root=tmp_path / "store", seed=7,
                budget={"max_actions": 100})
            async with session:
                await session.start()
                await session.reset()
                from vasta_protocols.protocols import Action

                for i in range(20):
                    await session.act(Action(tool="set_status",
                                              args={"status":
                                                    f"done-{i}"}))
                types = [e.type for e in session.events()]
            return types

        start = time.monotonic()
        types = asyncio.run(run())
        elapsed = time.monotonic() - start
        assert "action.executed" in types and "verification.passed" in types
        assert elapsed < 40.0, f"20 动作全链 {elapsed:.1f}s——数量级回归"

    def test_event_append_throughput_smoke(self, tmp_path) -> None:
        import asyncio

        store = SqliteStorage(tmp_path / "s")
        try:

            async def emit_many() -> None:
                seq = EventSequencer(store, "perf-run", tenant_id="t",
                                     project_id="p")
                for i in range(200):
                    await seq.emit("run.created", {"i": i})

            start = time.monotonic()
            asyncio.run(emit_many())
            elapsed = time.monotonic() - start
            rate = 200 / elapsed
            assert rate > 50.0, f"追加吞吐 {rate:.0f}/s——数量级回归"
        finally:
            store.close()
