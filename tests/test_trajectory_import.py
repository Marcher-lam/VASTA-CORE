"""Story 8.2：轨迹导入——一等接入形态（FR-002 第六种，G1）。

外部历史日志 → 13 族事件 + CAS；all-or-nothing fail-closed；
导入产物可被 search/timeline/复现包消费；同输入确定性。
"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.trajectory import ImportSummary, import_trajectory

# ---- OpenAI messages 风格样例 ----
OPENAI_TRAJECTORY = [
    {"type": "message", "role": "user", "content": "帮我把订单 A102 标记发货"},
    {"type": "message", "role": "assistant", "content": None,
     "tool_calls": [{"id": "call_1", "name": "ship_order",
                     "arguments": {"order_id": "A102"}}]},
    {"type": "tool_call", "call_id": "call_1", "name": "ship_order",
     "output": {"ok": True, "status": "shipped"}},
    {"type": "message", "role": "assistant", "content": "A102 已发货"},
]

# ---- 自定义 JSONL（显式 type）样例 ----
GENERIC_TRAJECTORY = [
    {"type": "observation", "kind": "external", "source": "webhook",
     "detail": {"event": "order_paid"}},
    {"type": "action", "tool": "ship_order", "args": {"order_id": "A102"},
     "ok": True, "result": {"status": "shipped"}},
    {"type": "note", "text": "本轮完成"},
]


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "store")
    yield s
    s.close()


class TestOpenAIFormat:
    async def test_maps_to_valid_events(self, store) -> None:
        summary = await import_trajectory(
            store, OPENAI_TRAJECTORY, run_id="imp-1", source_format="openai"
        )
        assert isinstance(summary, ImportSummary)
        events = list(store.iter_run_events("imp-1"))
        types = [e.type for e in events]
        assert types[0] == "run.created"
        assert types[-1] == "run.completed"
        # 用户消息 → 外部观察；助手文本 → 决策观察
        assert "observation.external" in types
        assert "observation.decision" in types
        # 工具调用 → 契约+执行对（imported 标记）
        assert "action.contracted" in types and "action.executed" in types
        # 逐条父链可溯（timeline 全覆盖的前提）
        id_to_seq = {e.event_id: e.seq for e in events}
        parents = [e.parent_event_id for e in events[1:]]
        assert all(p in id_to_seq for p in parents)

    async def test_tool_result_in_cas_hash_verifiable(self, store) -> None:
        """AC：工具响应入 CAS 可哈希取回（AD-3）。"""
        await import_trajectory(
            store, OPENAI_TRAJECTORY, run_id="imp-2", source_format="openai"
        )
        executed = [e for e in store.iter_run_events("imp-2")
                    if e.type == "action.executed"][-1]
        sha = executed.payload["result_ref"]
        blob = await store.get_artifact(sha)
        assert b"shipped" in blob  # 原始响应可取回
        import hashlib
        assert hashlib.sha256(blob).hexdigest() == sha  # 哈希校验过

    async def test_imported_action_marked(self, store) -> None:
        """导入动作不伪装六段链管辖：imported=True 诚实标记。"""
        await import_trajectory(
            store, OPENAI_TRAJECTORY, run_id="imp-3", source_format="openai"
        )
        contracted = [e for e in store.iter_run_events("imp-3")
                      if e.type == "action.contracted"][-1]
        assert contracted.payload.get("imported") is True


class TestGenericFormat:
    async def test_explicit_type_mapping(self, store) -> None:
        summary = await import_trajectory(
            store, GENERIC_TRAJECTORY, run_id="imp-g1", source_format="generic"
        )
        events = list(store.iter_run_events("imp-g1"))
        types = [e.type for e in events]
        assert "observation.external" in types
        assert "action.contracted" in types and "action.executed" in types
        # note → 备忘类事件（memory.note）
        assert "memory.note" in types
        assert summary.records == len(GENERIC_TRAJECTORY)
        assert summary.events == len(events)


class TestFailClosed:
    async def test_invalid_record_rejects_whole_import(self, store) -> None:
        """AC：不合法轨迹明确报错不入库——all-or-nothing。"""
        bad = [
            {"type": "message", "role": "user", "content": "hi"},
            {"type": "totally_unknown", "wow": True},  # 未知类型
        ]
        with pytest.raises(VastaError) as excinfo:
            await import_trajectory(
                store, bad, run_id="imp-bad", source_format="openai"
            )
        assert excinfo.value.code == "trajectory.invalid_record"
        assert "1" in str(excinfo.value)  # 错误信息含记录序号
        # 零事件写入（无部分导入态）
        assert list(store.iter_run_events("imp-bad")) == []

    async def test_missing_required_field_rejected(self, store) -> None:
        bad = [{"type": "tool_call", "output": {"ok": True}}]  # 缺 call_id/name
        with pytest.raises(VastaError):
            await import_trajectory(store, bad, run_id="imp-bad2",
                                    source_format="openai")
        assert list(store.iter_run_events("imp-bad2")) == []

    async def test_existing_run_rejected(self, store) -> None:
        await import_trajectory(store, OPENAI_TRAJECTORY, run_id="imp-dup",
                                source_format="openai")
        with pytest.raises(VastaError) as excinfo:
            await import_trajectory(store, OPENAI_TRAJECTORY, run_id="imp-dup",
                                    source_format="openai")
        assert excinfo.value.code == "trajectory.run_exists"


class TestConsumability:
    async def test_timeline_full_coverage(self, store) -> None:
        """AC：导入产物可被 timeline 消费（全覆盖投影）。"""
        from vasta_storage import timeline

        await import_trajectory(store, OPENAI_TRAJECTORY, run_id="imp-t1",
                                source_format="openai")
        events = list(store.iter_run_events("imp-t1"))
        tl = timeline(events)
        assert tl.covers_all_events
        assert tl.max_depth >= 1

    async def test_search_consumable(self, store) -> None:
        """AC：导入产物可被 search_events 消费（动作维度检索）。"""
        await import_trajectory(store, OPENAI_TRAJECTORY, run_id="imp-s1",
                                source_format="openai")
        hits = await store.search_events(
            "t-default", "p-default", run_id="imp-s1",
            event_type="action.", payload_equals={"tool": "ship_order"},
        )
        assert len(hits) >= 2  # contracted + executed

    async def test_repro_bundle_exportable(self, store) -> None:
        """AC：导入产物可被复现包消费。"""
        from vasta_storage import export_repro_bundle, replay_non_model_events

        await import_trajectory(store, OPENAI_TRAJECTORY, run_id="imp-r1",
                                source_format="openai")
        bundle, event_bytes = await export_repro_bundle(store, "imp-r1")
        assert bundle.event_count >= 6
        assert bundle.artifact_refs  # CAS 引用在清单
        replayed = replay_non_model_events(event_bytes)
        assert len(replayed) == bundle.event_count

    async def test_deterministic_same_input(self, tmp_path) -> None:
        """同输入两导入（不同 run/库）→ 归一化事件流逐字节一致。"""
        import json

        streams = []
        for sub in ("a", "b"):
            s = SqliteStorage(tmp_path / sub)
            await import_trajectory(s, OPENAI_TRAJECTORY, run_id="same",
                                    source_format="openai")
            rows = [
                {"seq": e.seq, "type": e.type, "payload": e.payload}
                for e in s.iter_run_events("same")
            ]
            streams.append(json.dumps(rows, sort_keys=True, ensure_ascii=False))
            s.close()
        assert streams[0] == streams[1]
