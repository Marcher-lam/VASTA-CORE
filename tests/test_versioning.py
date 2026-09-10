"""Story 8.8：模型与策略版本化（FR-061，G4）——「回到当时」补齐后两类对象。

模型资产入 CAS + 事件版本链；策略配置快照入事件流；as-of 取回完整 bundle。
"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.governance.versioning import (
    VersionRecord,
    publish_model_version,
    publish_policy_snapshot,
    version_as_of,
)

RULESET_V1 = {
    "rules": {"right": {"add": {"col": 1}}},
    "goal_check": "done",
}
RULESET_V2 = {
    "rules": {"right": {"add": {"col": 2}}, "finish": {"set": {"done": 1}}},
    "goal_check": "done",
}
MANIFEST = {
    "name": "grid", "version": "1.0", "scope": "grid",
    "unknowns": ["u"], "coverage": ["right"],
}


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


class TestModelVersioning:
    async def test_publish_and_latest_bundle(self, store) -> None:
        ref = await publish_model_version(
            store, "grid", "1.0.0", ruleset=RULESET_V1, manifest=MANIFEST,
        )
        assert ref.sha256 and ref.name == "grid" and ref.version == "1.0.0"
        record = await version_as_of(store, "model", "grid")
        assert isinstance(record, VersionRecord)
        assert record.version == "1.0.0"
        # bundle 可重建为 DSLWorldModel（可执行模型原样回来）
        model = record.rebuild_dsl()
        state = model.init_state({"detail": {"col": 0, "_steps": 0}})
        state = model.transition(state, {"tool": "right"})
        assert state["col"] == 1  # v1 语义

    async def test_old_version_survives_v2(self, store) -> None:
        """AC：旧版本可完整取回 + 回放不串版。"""
        await publish_model_version(
            store, "grid", "1.0.0", ruleset=RULESET_V1, manifest=MANIFEST,
        )
        v1_seq = max(e.seq for e in store.iter_run_events("registry"))
        await publish_model_version(
            store, "grid", "2.0.0", ruleset=RULESET_V2, manifest=MANIFEST,
        )
        latest = await version_as_of(store, "model", "grid")
        assert latest.version == "2.0.0"
        assert latest.rebuild_dsl().ruleset.rules["right"]["add"]["col"] == 2
        # as-of 当时 = v1（回放不串版）
        at_v1 = await version_as_of(store, "model", "grid", as_of_seq=v1_seq)
        assert at_v1.version == "1.0.0"
        assert at_v1.rebuild_dsl().ruleset.rules["right"]["add"]["col"] == 1

    async def test_same_version_same_content_idempotent(self, store) -> None:
        first = await publish_model_version(
            store, "grid", "1.0.0", ruleset=RULESET_V1, manifest=MANIFEST,
        )
        second = await publish_model_version(
            store, "grid", "1.0.0", ruleset=RULESET_V1, manifest=MANIFEST,
        )
        assert first.sha256 == second.sha256  # 同内容 → CAS 同址幂等

    async def test_same_version_different_content_rejected(self, store) -> None:
        await publish_model_version(
            store, "grid", "1.0.0", ruleset=RULESET_V1, manifest=MANIFEST,
        )
        with pytest.raises(VastaError) as excinfo:
            await publish_model_version(
                store, "grid", "1.0.0", ruleset=RULESET_V2, manifest=MANIFEST,
            )
        assert "conflict" in excinfo.value.code

    async def test_python_code_model_roundtrip(self, store) -> None:
        code = "result = {'col': state['col'] + 1}"
        await publish_model_version(
            store, "py", "1.0.0", code=code, manifest=MANIFEST,
        )
        record = await version_as_of(store, "model", "py")
        model = record.rebuild_python()
        nxt = model.transition({"col": 4}, {"tool": "right"})
        assert nxt["col"] == 5


class TestPolicyVersioning:
    async def test_snapshot_roundtrip_and_as_of(self, store) -> None:
        config_v1 = {"default": {"R3": "request_approval"}, "rules": []}
        config_v2 = {"default": {"R3": "deny"}, "rules": []}
        await publish_policy_snapshot(store, "main", "1", config_v1)
        v1_seq = max(e.seq for e in store.iter_run_events("registry"))
        await publish_policy_snapshot(store, "main", "2", config_v2)

        latest = await version_as_of(store, "policy", "main")
        assert latest.config == config_v2
        at_v1 = await version_as_of(store, "policy", "main", as_of_seq=v1_seq)
        assert at_v1.config == config_v1  # dict 原样往返
        assert at_v1.version == "1"

    async def test_policy_conflict_rejected(self, store) -> None:
        await publish_policy_snapshot(store, "p", "1", {"a": 1})
        with pytest.raises(VastaError):
            await publish_policy_snapshot(store, "p", "1", {"a": 2})


class TestErrorsAndSideEffects:
    async def test_unknown_name_rejected(self, store) -> None:
        with pytest.raises(VastaError) as excinfo:
            await version_as_of(store, "model", "ghost")
        assert "not_found" in excinfo.value.code

    async def test_not_found_before_first_publish(self, store) -> None:
        from datetime import timedelta

        await publish_model_version(
            store, "grid", "1.0.0", ruleset=RULESET_V1, manifest=MANIFEST,
        )
        first = next(e for e in store.iter_run_events("registry")
                     if e.type == "world_model.published")
        before = first.ts - timedelta(microseconds=1)
        with pytest.raises(VastaError):
            await version_as_of(store, "model", "grid", as_of_ts=before)

    async def test_reads_zero_side_effect(self, store) -> None:
        await publish_model_version(
            store, "grid", "1.0.0", ruleset=RULESET_V1, manifest=MANIFEST,
        )
        events_before = len(list(store.iter_run_events("registry")))
        arts_before = len(await store.list_artifacts("t-default", "p-default"))
        for _ in range(3):
            await version_as_of(store, "model", "grid")
        assert len(list(store.iter_run_events("registry"))) == events_before
        assert len(await store.list_artifacts("t-default", "p-default")) == arts_before

    async def test_registry_events_use_closed_families(self, store) -> None:
        await publish_model_version(
            store, "grid", "1.0.0", ruleset=RULESET_V1, manifest=MANIFEST,
        )
        await publish_policy_snapshot(store, "main", "1", {})
        types = [e.type for e in store.iter_run_events("registry")]
        assert "world_model.published" in types
        assert "artifact.published" in types


class TestRunReferencesVersion:
    """评审补齐（验收审计保留项 8.8）：历史 Run 事件引用当时版本——
    v2 发布后按 run 时点解析 = v1（回放不串版的 run 侧演示）。"""

    async def test_run_event_references_version_at_time(self, store) -> None:
        from vastacore.governance.versioning import _emit_registry  # noqa: PLC2701

        await publish_model_version(
            store, "grid", "1.0.0", ruleset=RULESET_V1, manifest=MANIFEST,
        )
        v1 = await version_as_of(store, "model", "grid")
        # 模拟一次 Run 使用 v1：run 事件携带版本 sha 引用（模型资产引用）
        await _emit_registry(store, "run.created",
                             {"model": "grid", "version": "1.0.0",
                              "sha256": v1.sha256, "note": "run-side ref demo"})
        run_seq = max(e.seq for e in store.iter_run_events("registry"))
        await publish_model_version(
            store, "grid", "2.0.0", ruleset=RULESET_V2, manifest=MANIFEST,
        )
        # run 时点之后解析：run 引用仍指 v1（内容寻址不可变）
        run_event = [e for e in store.iter_run_events("registry")
                     if e.seq == run_seq][0]
        assert run_event.payload["sha256"] == v1.sha256
        record = await version_as_of(store, "model", "grid",
                                     as_of_seq=run_seq)
        assert record.version == "1.0.0"  # 回放不串版
        assert record.rebuild_dsl().ruleset.rules["right"]["add"]["col"] == 1
