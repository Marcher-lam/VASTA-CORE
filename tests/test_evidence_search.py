"""Story 2.1：证据多维检索（FR-013，AD-7/14）。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from vasta_protocols.errors import VastaError
from vasta_protocols.ids import now_utc
from vasta_protocols.protocols import Action, Observation
from vasta_storage import SqliteStorage

T, P = "t-search", "p-search"


class SearchEnv:
    protocol_version = "0.1.0"

    async def reset(self, seed: int | None = None) -> Observation:
        return Observation(kind="decision", available_actions=["go", "stop"])

    async def observe(self) -> Observation:
        return Observation(kind="decision", available_actions=["go", "stop"])

    async def execute(self, action: Action) -> list[Observation]:
        if action.tool == "stop":
            return [Observation(kind="transition"), Observation(kind="terminal")]
        return [Observation(kind="transition"), Observation(kind="decision")]

    async def status(self) -> object:
        class _S:
            running = True

        return _S()


async def seed_run(store: SqliteStorage, *, tenant: str = T, run_tag: str = "r1") -> str:
    from vasta_runtime import RunContext, RunEngine

    run_id = f"run-{run_tag}"
    engine = await RunEngine.create(
        env=SearchEnv(),
        store=store,
        run_context=RunContext.create(
            run_id=run_id, tenant_id=tenant, project_id=P, seed=1
        ),
        capture_observations=True,
    )
    await engine.start()
    await engine.reset(seed=1)
    await engine.step(Action(tool="go"))
    await engine.step(Action(tool="stop"))
    return run_id


class TestEventSearchDimensions:
    async def test_scope_isolation(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        await seed_run(store, tenant="t-a", run_tag="a")
        await seed_run(store, tenant="t-b", run_tag="b")

        only_a = await store.search_events("t-a", P)
        assert {e.run_id for e in only_a} == {"run-a"}
        assert all(e.tenant_id == "t-a" for e in only_a)

    async def test_half_scope_rejected(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        with pytest.raises(VastaError) as excinfo:
            await store.search_events("t-a", None)  # type: ignore[arg-type]
        assert excinfo.value.code == "scope.half_pair"

    async def test_event_type_exact_and_family_prefix(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        run_id = await seed_run(store)

        exact = await store.search_events(T, P, run_id=run_id, event_type="run.created")
        assert len(exact) == 1

        family = await store.search_events(T, P, run_id=run_id, event_type="observation.")
        kinds = {e.type for e in family}
        assert kinds == {"observation.reset", "observation.decision",
                         "observation.transition", "observation.terminal"}
        # 全部事件均可按 (run_id, seq) 取回（无死键）
        for e in family:
            assert (await store.get_event(e.run_id, e.seq, tenant_id=T, project_id=P)) == e

    async def test_time_window(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        run_id = await seed_run(store)
        base = now_utc()

        future = await store.search_events(
            T, P, run_id=run_id, ts_from=base + timedelta(hours=1)
        )
        assert future == []

        past = await store.search_events(T, P, run_id=run_id, ts_to=base + timedelta(hours=1))
        assert len(past) >= 7

    async def test_payload_equals_action_dimension(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        run_id = await seed_run(store)

        go_events = await store.search_events(
            T, P, run_id=run_id, payload_equals={"last_action": "go"}
        )
        assert go_events, "last_action 维度未命中"
        assert all(e.payload.get("last_action") == "go" for e in go_events)
        assert len(go_events) == 2  # transition + decision
        # reset/terminal 观察不带 last_action（非 step 产生/终局后）

    async def test_payload_key_injection_rejected(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        with pytest.raises(VastaError) as excinfo:
            await store.search_events(T, P, payload_equals={'x" OR 1=1--': "v"})
        assert excinfo.value.code == "search.bad_key"

    async def test_combined_dimensions(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        run_id = await seed_run(store)
        results = await store.search_events(
            T, P,
            run_id=run_id,
            event_type="observation.",
            payload_equals={"last_action": "stop"},
        )
        assert [e.type for e in results] == ["observation.transition", "observation.terminal"]
        assert results[1].kind if hasattr(results[1], "kind") else True


class TestArtifactSearch:
    async def test_tags_search_and_merge(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        payload = b"tagged-evidence"
        sha1 = await store.save_artifact(
            payload, tags={"region": "top-left"}, tenant_id=T, project_id=P
        )
        sha2 = await store.save_artifact(  # 同内容去重：标签并集合并
            payload, tags={"entity": "order-1024"}, tenant_id=T, project_id=P
        )
        assert sha1 == sha2

        by_region = await store.search_artifacts(T, P, tags={"region": "top-left"})
        by_entity = await store.search_artifacts(T, P, tags={"entity": "order-1024"})
        assert len(by_region) == 1 and len(by_entity) == 1
        assert by_region[0]["sha256"] == sha1 == by_entity[0]["sha256"]

        both = await store.search_artifacts(
            T, P, tags={"region": "top-left", "entity": "order-1024"}
        )
        assert len(both) == 1  # 并集合并后两标签同时命中

    async def test_source_and_classification_dimensions(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        await store.save_artifact(b"a", source="observation.capture",
                                  classification="internal", tenant_id=T, project_id=P)
        await store.save_artifact(b"b", source="model.exchange",
                                  classification="secret", tenant_id=T, project_id=P)

        caps = await store.search_artifacts(T, P, source="observation.capture")
        assert len(caps) == 1 and caps[0]["classification"] == "internal"
        secrets = await store.search_artifacts(T, P, classification="secret")
        assert len(secrets) == 1

    async def test_refs_join_visibility(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        await store.save_artifact(b"scoped", tenant_id=T, project_id=P)
        # t-other 无引用 → 不可见（AD-14）
        assert await store.search_artifacts("t-other", P) == []
        assert len(await store.search_artifacts(T, P)) == 1


class TestNoDeadLinks:
    async def test_dead_blob_raises(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        run_id = await seed_run(store)

        # 删除一个被引用的 blob → 检索必须响亮失败（不静默）
        events = await store.search_events(T, P, run_id=run_id)
        ref = events[-1].payload["artifact_refs"][0]
        blob = tmp_path / "s" / "objects" / ref[:2] / ref
        blob.unlink()
        with pytest.raises(VastaError) as excinfo:
            await store.search_events(T, P, run_id=run_id)
        assert excinfo.value.code == "search.dead_links"

    async def test_all_refs_retrievable_and_hash_verified(self, tmp_path) -> None:
        """AC：返回的引用全部可取回且哈希校验通过。"""
        import hashlib
        import json as jsonlib

        store = SqliteStorage(tmp_path / "s")
        run_id = await seed_run(store)
        for event in await store.search_events(T, P, run_id=run_id):
            for ref in event.payload.get("artifact_refs", []):
                content = await store.get_artifact(ref, tenant_id=T, project_id=P)
                assert hashlib.sha256(content).hexdigest() == ref
                jsonlib.loads(content)  # 采集载荷可解析


class TestSchemaMigration:
    async def test_v1_database_migrates_to_v2(self, tmp_path) -> None:
        import sqlite3

        root = tmp_path / "legacy"
        root.mkdir()
        db = sqlite3.connect(root / "store.db")
        db.execute("PRAGMA user_version=1")
        db.execute(
            "CREATE TABLE artifacts (sha256 TEXT PRIMARY KEY, mime TEXT,"
            " size INTEGER NOT NULL, source TEXT, classification TEXT,"
            " retention TEXT, created_at TEXT NOT NULL)"
        )
        db.commit()
        db.close()

        store = SqliteStorage(root)  # v1 旧库直接升级到当前 schema 版本
        version = store._conn.execute("PRAGMA user_version").fetchone()[0]  # noqa: SLF001
        assert version >= 2
        await store.save_artifact(b"after-migration",
                                        tags={"region": "r"}, tenant_id=T, project_id=P)
        assert len(await store.search_artifacts(T, P, tags={"region": "r"})) == 1
        store.close()

    async def test_future_schema_rejected(self, tmp_path) -> None:
        import sqlite3

        root = tmp_path / "future"
        root.mkdir()
        db = sqlite3.connect(root / "store.db")
        db.execute("PRAGMA user_version=99")
        db.commit()
        db.close()
        with pytest.raises(VastaError) as excinfo:
            SqliteStorage(root)
        assert excinfo.value.code == "store.schema_too_new"
