"""Story 1.4：SqliteStorage 真实实现——契约套件 + 分桶/去重/作用域/原子性/篡改/持久化。"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest

from vasta_protocols.contract_suites import StorageAdapterContract
from vasta_protocols.envelope import EventEnvelope
from vasta_protocols.errors import DuplicateEventError, VastaError
from vasta_protocols.ids import new_event_id, new_run_id, now_utc
from vasta_protocols.protocols import Action, Observation
from vasta_storage.sqlite_store import ArtifactNotFoundError, SqliteStorage


class TestSqliteStorageContract(StorageAdapterContract):
    """Story 1.1 的存储契约套件，首次由真实 SQLite 实现驱动。"""

    def make_adapter(self) -> SqliteStorage:
        self._tmp = tempfile.TemporaryDirectory()  # 测试存续期间保持有效
        return SqliteStorage(Path(self._tmp.name) / "store")


class TestShardedCas:
    async def test_blob_written_to_sharded_path(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        payload = b"vasta-evidence"
        sha = await store.save_artifact(payload, mime="image/png")
        blob = tmp_path / "s" / "objects" / sha[:2] / sha
        assert blob.exists()
        assert blob.read_bytes() == payload
        assert sha == hashlib.sha256(payload).hexdigest()

    async def test_same_bytes_dedup_one_blob_two_refs(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        sha1 = await store.save_artifact(b"duplicate", tenant_id="t-a", project_id="p")
        sha2 = await store.save_artifact(b"duplicate", tenant_id="t-b", project_id="p")
        assert sha1 == sha2  # 字节全局单份（AD-14）
        total = len(await store.list_artifacts("t-a", "p")) + len(
            await store.list_artifacts("t-b", "p")
        )
        assert total == 2  # 各租户引用映射独立

    async def test_metadata_transactional(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        payload = b'{"k":1}'
        sha = await store.save_artifact(
            payload,
            mime="application/json",
            source="tool.response",
            classification="internal",
            retention="90d",
        )
        info = await store.artifact_info(sha)
        assert info is not None
        assert info["mime"] == "application/json"
        assert info["source"] == "tool.response"
        assert info["classification"] == "internal"
        assert info["retention"] == "90d"
        assert info["size"] == len(payload)

    async def test_blob_failure_leaves_no_captured_state(self, tmp_path) -> None:
        """AD-3：落盘失败 → 无元数据/引用（先落盘后引用，无部分状态）。"""
        store = SqliteStorage(tmp_path / "s")
        payload = b"atomic-fail"
        sha = hashlib.sha256(payload).hexdigest()
        objects_dir = tmp_path / "s" / "objects"
        objects_dir.mkdir(parents=True, exist_ok=True)
        (objects_dir / sha[:2]).write_text("file blocking the shard dir", encoding="utf-8")

        with pytest.raises(OSError):
            await store.save_artifact(payload)
        assert await store.artifact_info(sha) is None
        assert await store.list_artifacts("t-default", "p-default") == []


class TestScopeAndVerification:
    async def test_tenant_reachability_enforced(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        sha = await store.save_artifact(b"scoped", tenant_id="t-a", project_id="p")
        assert await store.get_artifact(sha, tenant_id="t-a", project_id="p") == b"scoped"
        with pytest.raises(ArtifactNotFoundError):
            await store.get_artifact(sha, tenant_id="t-b", project_id="p")  # 跨租户不可达

    async def test_unknown_hash_raises(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        with pytest.raises(ArtifactNotFoundError):
            await store.get_artifact("0" * 64)

    async def test_tampered_blob_detected(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        sha = await store.save_artifact(b"trust-me")
        blob = tmp_path / "s" / "objects" / sha[:2] / sha
        blob.write_bytes(b"tampered!!")  # 磁盘级篡改
        with pytest.raises(VastaError) as excinfo:
            await store.get_artifact(sha)
        assert excinfo.value.code == "artifact.corrupted"

    async def test_list_scoped_by_tenant_and_classification(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        await store.save_artifact(b"a", tenant_id="t-a", project_id="p", classification="x")
        await store.save_artifact(b"b", tenant_id="t-b", project_id="p")
        only_a = await store.list_artifacts("t-a", "p")
        assert len(only_a) == 1 and only_a[0]["classification"] == "x"
        assert await store.list_artifacts("t-a", "p", classification="nope") == []


class TestEventStore:
    async def test_duplicate_seq_on_real_sqlite(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        base = {
            "run_id": new_run_id(),
            "seq": 0,
            "type": "run.created",
            "ts": now_utc(),
            "tenant_id": "t",
            "project_id": "p",
            "event_id": new_event_id(),
        }
        await store.append_event(EventEnvelope.model_validate(base))
        with pytest.raises(DuplicateEventError):
            await store.append_event(
                EventEnvelope.model_validate({**base, "event_id": new_event_id()})
            )

    async def test_missing_event_raises(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        with pytest.raises(VastaError):
            await store.get_event("run-none", 0)


class _GridEnv:
    """最小网格环境（引擎持久化集成用）。"""

    protocol_version = "0.1.0"

    async def reset(self, seed: int | None = None) -> Observation:
        return Observation(kind="decision", available_actions=["go"])

    async def observe(self) -> Observation:
        return Observation(kind="decision", available_actions=["go"])

    async def execute(self, action: Action) -> list[Observation]:
        return [Observation(kind="transition"), Observation(kind="decision")]

    async def status(self) -> object:
        class _S:
            running = True

        return _S()


class TestEngineIntegration:
    async def test_run_persists_and_reopens(self, tmp_path) -> None:
        from vasta_runtime.runner import RunConfig, RunEngine

        root = tmp_path / "engine-store"
        store = SqliteStorage(root)
        engine = await RunEngine.create(
            env=_GridEnv(), store=store, config=RunConfig(run_id="run-persist")
        )
        await engine.start()
        await engine.reset(seed=7)
        await engine.step(Action(tool="go"))
        sha = await store.save_artifact(b"frame-0", source="observation", mime="image/png")
        store.close()

        # 重开同一根目录：事件与证据俱在
        reopened = SqliteStorage(root)
        types = [e.type for e in reopened.iter_run_events("run-persist")]
        assert types == [
            "run.created",
            "run.started",
            "observation.reset",
            "observation.decision",
            "action.executed",  # env 路径动作留痕（Story 9.10 补口）
            "observation.transition",
            "observation.decision",
        ]
        assert await reopened.get_artifact(sha) == b"frame-0"
        for e in reopened.iter_run_events("run-persist"):
            assert e.tenant_id == "t-default" and e.project_id == "p-default"
        reopened.close()
