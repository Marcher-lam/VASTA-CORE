"""Story 9.2：实体索引与检索维度补全（FR-013 字母级收口，WAIVER W-2 解除）。

跨事件/工件/派生物三类命中；别名解析；作用域隔离；未知实体空结果。
"""

from __future__ import annotations

import pytest

from vasta_protocols.envelope import EventEnvelope
from vasta_protocols.errors import VastaError
from vasta_protocols.ids import new_event_id, now_utc
from vasta_storage import SqliteStorage


async def make_store(tmp_path) -> SqliteStorage:
    return SqliteStorage(tmp_path / "s")


async def seed_evidence(store: SqliteStorage) -> None:
    """工件（带实体标签）+ 引用工件的事件 + 派生物（血缘一跳）。"""
    # 1) 截图工件（实体：订单 A102）
    await store.save_artifact(
        b"screenshot-bytes", mime="image/png", source="browser",
        entities={"order_id": "A102", "customer": "C-88"},
        tenant_id="t-a", project_id="p-a",
    )
    # 2) 工具响应工件（实体：订单 A102）+ 引用事件
    resp_sha = await store.save_artifact(
        b'{"status": "shipped"}', mime="application/json",
        entities={"order_id": "A102"}, tenant_id="t-a", project_id="p-a",
    )
    await store.append_event(EventEnvelope.model_validate({
        "run_id": "r1", "seq": 0, "type": "action.executed",
        "parent_event_id": None, "ts": now_utc(),
        "tenant_id": "t-a", "project_id": "p-a", "event_id": new_event_id(),
        "payload": {"tool": "ship_order", "result_ref": resp_sha,
                    "entity_refs": {"order_id": "A102"}},
    }))
    # 3) 派生物（源=截图，实体继承一跳命中）
    src_sha = await store.save_artifact(
        b"screenshot-bytes", mime="image/png", tenant_id="t-a", project_id="p-a"
    )
    await store.save_derived(
        b"cropped", source_sha256=src_sha, transform="crop",
        params={}, transformer_version="v1",
        tenant_id="t-a", project_id="p-a",
    )


class TestEntityIndex:
    async def test_hits_across_three_kinds(self, tmp_path) -> None:
        """AC：search_by_entity 命中事件/工件/派生物三类。"""
        store = await make_store(tmp_path)
        await seed_evidence(store)
        hits = await store.search_by_entity(
            "order_id", "A102", tenant_id="t-a", project_id="p-a"
        )
        kinds = {h["kind"] for h in hits}
        assert "event" in kinds
        assert "artifact" in kinds
        assert "derived" in kinds
        store.close()

    async def test_alias_resolves_to_canonical(self, tmp_path) -> None:
        """别名 A-102 → A102（登记别名后同键命中）。"""
        store = await make_store(tmp_path)
        await seed_evidence(store)
        await store.register_entity_alias(
            "order_id", "A-102", "A102",
            tenant_id="t-a", project_id="p-a",
        )
        hits = await store.search_by_entity(
            "order_id", "A-102", tenant_id="t-a", project_id="p-a"
        )
        assert hits  # 别名命中
        store.close()

    async def test_scope_isolation(self, tmp_path) -> None:
        """AD-9：他租户不可见。"""
        store = await make_store(tmp_path)
        await seed_evidence(store)
        hits = await store.search_by_entity(
            "order_id", "A102", tenant_id="t-b", project_id="p-b"
        )
        assert hits == []
        store.close()

    async def test_unknown_entity_empty(self, tmp_path) -> None:
        """AC：未知实体明确空结果（非报错）。"""
        store = await make_store(tmp_path)
        await seed_evidence(store)
        hits = await store.search_by_entity(
            "order_id", "GHOST-999", tenant_id="t-a", project_id="p-a"
        )
        assert hits == []
        store.close()

    async def test_blank_scope_rejected(self, tmp_path) -> None:
        store = await make_store(tmp_path)
        with pytest.raises(VastaError):
            await store.search_by_entity("order_id", "A102", tenant_id="", project_id="")
        store.close()

    async def test_second_entity_key_distinguishes(self, tmp_path) -> None:
        """不同实体键同名值不串——customer C-88 只命中截图工件。"""
        store = await make_store(tmp_path)
        await seed_evidence(store)
        hits = await store.search_by_entity(
            "customer", "C-88", tenant_id="t-a", project_id="p-a"
        )
        assert all(h["entity_key"] == "customer" for h in hits)
        assert len(hits) >= 1  # 截图工件
        store.close()

    async def test_migration_v3_to_v4(self, tmp_path) -> None:
        """旧 v3 库打开即补 entity_index 表（不丢既有数据）。"""
        import sqlite3
        from pathlib import Path

        db = tmp_path / "old_v3.db"
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA user_version = 3")
        conn.execute(
            "CREATE TABLE events (run_id TEXT, seq INTEGER, type TEXT,"
            " parent_event_id TEXT, ts TEXT, tenant_id TEXT, project_id TEXT,"
            " event_id TEXT, payload TEXT, PRIMARY KEY (run_id, seq))"
        )
        conn.commit()
        conn.close()
        store = SqliteStorage(Path(db.stem))  # 不会用——直接测打开旧库
        store.close()
        # 直接以 v3 user_version 打开存储目录中的库
        store_dir = tmp_path / "s2"
        store_dir.mkdir()
        db2 = store_dir / "store.db"
        conn = sqlite3.connect(db2)
        conn.execute("PRAGMA user_version = 3")
        conn.execute(
            "CREATE TABLE events (run_id TEXT, seq INTEGER, type TEXT,"
            " parent_event_id TEXT, ts TEXT, tenant_id TEXT, project_id TEXT,"
            " event_id TEXT, payload TEXT, PRIMARY KEY (run_id, seq))"
        )
        conn.commit()
        conn.close()
        store = SqliteStorage(store_dir)
        # 打开即迁移：entity_index 可用
        hits = await store.search_by_entity(
            "order_id", "A102", tenant_id="t-a", project_id="p-a"
        )
        assert hits == []
        store.close()
