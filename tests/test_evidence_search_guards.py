"""Epic 2 评审修复的守卫测试（检索/标签/迁移/quickstart 端到端）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action
from vasta_storage import SqliteStorage

from .test_evidence_search import P, SearchEnv, T, seed_run


class TestLastActionLeakGuard:
    async def test_no_leak_to_non_step_paths(self, tmp_path) -> None:
        """泄漏守卫：step 之外的观察路径不得携带 last_action。"""
        from vasta_runtime import RunContext, RunEngine

        store = SqliteStorage(tmp_path / "s")
        engine = await RunEngine.create(
            env=SearchEnv(), store=store,
            run_context=RunContext.create(
                run_id="run-leak", tenant_id=T, project_id=P, seed=1
            ),
        )
        await engine.start()
        await engine.reset(seed=1)
        await engine.step(Action(tool="go"))
        await engine.observe()  # 非步骤路径
        await engine.ingest_external({"src": "test"})  # 非步骤路径

        hits = await store.search_events(
            T, P, run_id="run-leak", payload_equals={"last_action": "go"}
        )
        assert len(hits) == 2  # 仅 step("go") 的 transition+decision
        for e in store.iter_run_events("run-leak"):
            if e.type == "observation.external":
                assert "last_action" not in e.payload
            if e.type == "observation.reset":
                assert "last_action" not in e.payload
        store.close()


class TestSearchGuards:
    async def test_limit_must_be_positive(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        for bad in (0, -1):
            with pytest.raises(VastaError) as excinfo:
                await store.search_events(T, P, limit=bad)
            assert excinfo.value.code == "search.bad_limit"
        assert await store.search_events(T, P, limit=1) == []
        store.close()

    async def test_family_prefix_wildcards_rejected(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        with pytest.raises(VastaError) as excinfo:
            await store.search_events(T, P, event_type="obs%.")
        assert excinfo.value.code == "search.bad_type"
        with pytest.raises(VastaError):
            await store.search_events(T, P, event_type="ob_.")  # 下划线同拒
        store.close()

    async def test_payload_value_type_rejected(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        with pytest.raises(VastaError) as excinfo:
            await store.search_events(T, P, payload_equals={"k": None})
        assert excinfo.value.code == "search.bad_value"
        with pytest.raises(VastaError):
            await store.search_events(T, P, payload_equals={"k": {"nested": 1}})
        store.close()

    async def test_naive_datetime_rejected(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        with pytest.raises(VastaError) as excinfo:
            await store.search_events(T, P, ts_from=datetime(2026, 1, 1))
        assert excinfo.value.code == "search.bad_ts"
        store.close()

    async def test_blank_scope_rejected(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        with pytest.raises(VastaError) as excinfo:
            await store.search_events("", P)
        assert excinfo.value.code == "scope.blank"
        store.close()

    async def test_artifact_search_dead_blob_raises(self, tmp_path) -> None:
        """FR-013 无死链在 Artifact 检索侧（评审修复）。"""
        store = SqliteStorage(tmp_path / "s")
        run_id = await seed_run(store)
        events = await store.search_events(T, P, run_id=run_id)
        ref = events[-1].payload["artifact_refs"][0]
        assert await store.search_artifacts(T, P)  # 正常路径非空
        (tmp_path / "s" / "objects" / ref[:2] / ref).unlink()
        with pytest.raises(VastaError) as excinfo:
            await store.search_artifacts(T, P)
        assert excinfo.value.code == "search.dead_links"
        store.close()

    async def test_verify_hashes_detects_tampered_blob(self, tmp_path) -> None:
        """verify_hashes=True：被篡改 blob 检索期即拒（默认存在性校验）。"""
        store = SqliteStorage(tmp_path / "s")
        run_id = await seed_run(store)
        events = await store.search_events(T, P, run_id=run_id)
        ref = events[-1].payload["artifact_refs"][0]
        (tmp_path / "s" / "objects" / ref[:2] / ref).write_bytes(b"tampered")

        assert await store.search_events(T, P, run_id=run_id)  # 默认通过
        with pytest.raises(VastaError) as excinfo:
            await store.search_events(T, P, run_id=run_id, verify_hashes=True)
        assert excinfo.value.code == "search.dead_links"
        store.close()

    async def test_artifact_created_window(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        await store.save_artifact(b"w1", tenant_id=T, project_id=P)
        future = datetime.now(UTC) + timedelta(hours=1)
        assert await store.search_artifacts(T, P, created_from=future) == []
        assert len(await store.search_artifacts(T, P, created_to=future)) == 1
        store.close()

    async def test_result_ordering_ts_run_seq(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        await seed_run(store, run_tag="b")
        await seed_run(store, run_tag="a")
        results = await store.search_events(T, P)
        keys = [(e.ts, e.run_id, e.seq) for e in results]
        assert keys == sorted(keys)
        store.close()


class TestTagSemantics:
    async def test_tag_key_validated_at_save(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        with pytest.raises(VastaError) as excinfo:
            await store.save_artifact(
                b"t", tags={"bad-key": "v"}, tenant_id=T, project_id=P
            )
        assert excinfo.value.code == "search.bad_key"  # 存查对称
        store.close()

    async def test_tag_first_wins_no_cross_overwrite(self, tmp_path) -> None:
        """同键冲突保留先到值；新键仍并入（评审修复）。"""
        store = SqliteStorage(tmp_path / "s")
        payload = b"shared"
        await store.save_artifact(
            payload, tags={"region": "first"}, tenant_id="t-a", project_id=P
        )
        await store.save_artifact(
            payload, tags={"region": "second", "extra": "x"}, tenant_id="t-b", project_id=P
        )
        assert len(await store.search_artifacts("t-a", P, tags={"region": "first"})) == 1
        assert await store.search_artifacts("t-a", P, tags={"region": "second"}) == []
        assert len(await store.search_artifacts("t-b", P, tags={"extra": "x"})) == 1
        store.close()


class TestMigrationWithData:
    async def test_migration_preserves_existing_rows(self, tmp_path) -> None:
        """带数据的 v2 库迁移后行存活（空表迁移之外的补充）。"""
        import sqlite3

        root = tmp_path / "legacy-data"
        root.mkdir()
        db = sqlite3.connect(root / "store.db")
        db.execute("PRAGMA user_version=2")
        db.executescript(
            "CREATE TABLE artifacts (sha256 TEXT PRIMARY KEY, mime TEXT,"
            " size INTEGER NOT NULL, source TEXT, classification TEXT,"
            " retention TEXT, created_at TEXT NOT NULL,"
            " tags_json TEXT NOT NULL DEFAULT '{}');"
            "CREATE TABLE artifact_refs (tenant_id TEXT NOT NULL,"
            " project_id TEXT NOT NULL, sha256 TEXT NOT NULL,"
            " referenced_at TEXT NOT NULL,"
            " PRIMARY KEY (tenant_id, project_id, sha256));"
        )
        db.execute(
            "INSERT INTO artifacts VALUES ('aabb', 'text/plain', 3, 'old', NULL,"
            " NULL, '2026-01-01T00:00:00+00:00', '{}')"
        )
        db.execute("INSERT INTO artifact_refs VALUES ('t', 'p', 'aabb', '2026-01-01')")
        db.commit()
        db.close()

        store = SqliteStorage(root)
        info = await store.artifact_info("aabb", tenant_id="t", project_id="p")
        assert info is not None and info["source"] == "old"
        assert await store.list_artifacts("t", "p")
        store.close()


class TestQuickstartActionSearchE2E:
    async def test_right_action_hits(self, tmp_path) -> None:
        """Story 2.1 Task 7 原始形态：quickstart 数据上 last_action=right 命中。"""
        import vastacore

        await vastacore.quickstart(tmp_path / "qs", seed=42, run_id="run-qs-right")
        store = SqliteStorage(tmp_path / "qs" / "store")
        rights = await store.search_events(
            "t-default", "p-default",
            run_id="run-qs-right", payload_equals={"last_action": "right"},
        )
        downs = await store.search_events(
            "t-default", "p-default",
            run_id="run-qs-right", payload_equals={"last_action": "down"},
        )
        assert len(rights) == 6  # right×3 步 × 每步 2 观察
        assert len(downs) == 6
        store.close()
