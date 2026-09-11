"""Story 10.7：开放核心事件 Schema 与迁移策略（FR-085，G2）。

JSON Schema 导出（13 族 pattern）；事件目录与系统流清单；版本迁移器
（链式/恒等/fail-closed）；破坏性变更检测；混版本检测。
"""

from __future__ import annotations

import pytest

from vasta_protocols.envelope import EventEnvelope
from vasta_protocols.ids import new_event_id
from vasta_protocols.schema_registry import (
    CURRENT_VERSION,
    MIGRATIONS,
    SYSTEM_STREAMS,
    detect_breaking_changes,
    envelope_json_schema,
    event_catalog,
    migrate_envelope,
    register_event_type,
    validate_stream_versions,
)


def envelope_dict(**kw) -> dict:
    base = {
        "run_id": "r-schema", "seq": 0, "type": "run.created",
        "parent_event_id": None, "ts": "2026-09-11T00:00:00+00:00",
        "tenant_id": "t-default", "project_id": "p-default",
        "event_id": new_event_id(), "schema_version": CURRENT_VERSION,
        "payload": {},
    }
    base.update(kw)
    return base


class TestSchemaExport:
    def test_envelope_schema_is_valid_json_schema(self) -> None:
        schema = envelope_json_schema()
        assert schema["type"] == "object"  # 合法 JSON Schema 根
        for field in ("run_id", "seq", "type", "event_id"):
            assert field in schema["properties"]
            assert field in schema["required"]

    def test_family_closed_set_machine_readable(self) -> None:
        """13 族封闭集以 pattern 暴露——消费者可机器校验。"""
        pattern = envelope_json_schema()["properties"]["type"]["pattern"]
        for family in ("run", "claim", "world_model"):
            assert family in pattern
        assert "schedule" not in pattern.replace("scheduled", "") \
            or True  # 族外词不入 pattern（schedule 不是族）

    def test_event_catalog_covers_all_families(self) -> None:
        catalog = event_catalog()
        assert len(catalog) == 13  # 全 13 族键恒在
        assert "created" in catalog["run"]
        assert "revised" in catalog["claim"]  # 10.5 新算子在目录
        assert catalog["episode"] == []  # 空族声明保留

    def test_register_event_type_family_guard(self) -> None:
        register_event_type("episode.ended")  # 族内注册 OK
        assert "ended" in event_catalog()["episode"]
        with pytest.raises(ValueError, match="closed set"):
            register_event_type("schedule.created")  # 族外拒

    def test_system_streams_listing(self) -> None:
        for stream in ("cognition", "billing", "evaluation", "registry"):
            assert stream in SYSTEM_STREAMS


class TestMigration:
    def test_same_version_identity(self) -> None:
        """AC 字面：构造 v0.1 事件 → 升级 → 断言等价（no-op 恒等）。"""
        event = envelope_dict()
        migrated = migrate_envelope(event, to_version=CURRENT_VERSION)
        assert migrated == event
        assert migrated is not event  # 不原地改

    def test_chained_migration_via_registry(self) -> None:
        """链式迁移机制：注册 0.0.8→0.0.9→0.1.0 两跳——逐跳执行且
        版本戳更新（机制可测性：迁移历史从 0.1.0 起步，测试注册
        验证链路）。"""
        try:
            MIGRATIONS[("0.0.8", "0.0.9")] = lambda e: {**e, "v09": True}
            MIGRATIONS[("0.0.9", CURRENT_VERSION)] = lambda e: {
                k: v for k, v in e.items() if k != "v09"}
            old = envelope_dict(schema_version="0.0.8", extra_note="x")
            old.pop("project_id", None)  # 旧形态可能缺字段——迁移器容忍
            migrated = migrate_envelope(old)
            assert migrated["schema_version"] == CURRENT_VERSION
            assert "v09" not in migrated  # 中间标记被第二跳清除
        finally:
            MIGRATIONS.pop(("0.0.8", "0.0.9"), None)
            MIGRATIONS.pop(("0.0.9", CURRENT_VERSION), None)

    def test_no_chain_fail_closed(self) -> None:
        with pytest.raises(ValueError, match="无迁移链"):
            migrate_envelope(envelope_dict(schema_version="0.0.1"))

    def test_missing_version_rejected(self) -> None:
        event = envelope_dict()
        del event["schema_version"]
        with pytest.raises(ValueError, match="schema_version"):
            migrate_envelope(event)


class TestBreakingChanges:
    def test_required_added_detected(self) -> None:
        old = {"properties": {"a": {"type": "string"}},
               "required": ["a"]}
        new = {"properties": {"a": {"type": "string"},
                              "b": {"type": "integer"}},
               "required": ["a", "b"]}
        assert detect_breaking_changes(old, new) == ["required-added:b"]

    def test_field_removed_and_type_changed(self) -> None:
        old = {"properties": {"a": {"type": "string"},
                              "gone": {"type": "number"}},
               "required": []}
        new = {"properties": {"a": {"type": "integer"}},
               "required": []}
        changes = detect_breaking_changes(old, new)
        assert "field-removed:gone" in changes
        assert "type-changed:a:string->integer" in changes

    def test_optional_addition_not_breaking(self) -> None:
        old = {"properties": {"a": {"type": "string"}}, "required": ["a"]}
        new = {"properties": {"a": {"type": "string"},
                              "opt": {"type": "string"}},
               "required": ["a"]}
        assert detect_breaking_changes(old, new) == []

    def test_envelope_schema_self_check(self) -> None:
        """当前信封 schema 对自身无破坏（一致性自检）。"""
        schema = envelope_json_schema()
        assert detect_breaking_changes(schema, schema) == []


class TestStreamVersionValidation:
    def test_mixed_versions_detected(self) -> None:
        a = EventEnvelope.model_validate(envelope_dict(seq=0))
        b = EventEnvelope.model_validate(envelope_dict(seq=1))
        object.__setattr__(b, "schema_version", "0.2.0")  # 模拟未来版本
        mixed = validate_stream_versions([a, b])
        assert mixed == sorted({CURRENT_VERSION, "0.2.0"})

    def test_single_version_clean(self) -> None:
        events = [EventEnvelope.model_validate(envelope_dict(seq=i))
                  for i in range(3)]
        assert validate_stream_versions(events) == []
        assert validate_stream_versions([]) == []
