"""Story 9.1：Team 档双后端（PG 可选 extra / S3 注入客户端）。

S3 用内存 Fake 零服务覆盖；PG 集成测试 DSN 门控（无服务 skip）。
"""

from __future__ import annotations

import hashlib

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import S3BlobStore


class FakeS3Client:
    """内存 S3 客户端（put/get/head 契约形态，元数据保留）。"""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict] = {}

    def put_object(self, *, Bucket, Key, Body, ContentType=None, Metadata=None):
        self.objects[(Bucket, Key)] = {
            "Body": Body, "ContentType": ContentType,
            "Metadata": dict(Metadata or {}),
        }

    def get_object(self, *, Bucket, Key):
        key = (Bucket, Key)
        if key not in self.objects:
            raise KeyError(Key)

        class _Body:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def read(self) -> bytes:
                return self._data

        return {"Body": _Body(self.objects[key]["Body"])}

    def head_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise KeyError(Key)
        return {"Metadata": self.objects[(Bucket, Key)]["Metadata"]}


class TestS3BlobStore:
    async def test_save_returns_sha_and_key_layout(self) -> None:
        client = FakeS3Client()
        store = S3BlobStore("team-bucket", client=client, prefix="vasta/x")
        sha = await store.save_artifact(b"hello", mime="text/plain")
        assert sha == hashlib.sha256(b"hello").hexdigest()
        assert ("team-bucket", f"vasta/x/{sha[:2]}/{sha}") in client.objects

    async def test_save_dedup_same_sha_no_rewrite(self) -> None:
        """AD-14：字节全局去重——同内容二存 head 命中不重写。"""
        client = FakeS3Client()
        store = S3BlobStore("b", client=client)
        s1 = await store.save_artifact(b"same-bytes")
        s2 = await store.save_artifact(b"same-bytes")
        assert s1 == s2
        assert len(client.objects) == 1

    async def test_get_verifies_hash_corruption_detected(self) -> None:
        client = FakeS3Client()
        store = S3BlobStore("b", client=client)
        sha = await store.save_artifact(b"integrity")
        # 篡改底层对象
        key = ("b", f"vasta/artifacts/{sha[:2]}/{sha}")
        client.objects[key]["Body"] = b"tampered!!"
        with pytest.raises(VastaError) as excinfo:
            await store.get_artifact(sha)
        assert excinfo.value.code == "artifact.corrupted"

    async def test_get_unknown_not_found(self) -> None:
        store = S3BlobStore("b", client=FakeS3Client())
        with pytest.raises(VastaError) as excinfo:
            await store.get_artifact("0" * 64)
        assert excinfo.value.code == "artifact.not_found"

    async def test_metadata_carries_scope_and_tags(self) -> None:
        client = FakeS3Client()
        store = S3BlobStore("b", client=client)
        sha = await store.save_artifact(
            b"tagged", mime="image/png", source="screenshot",
            classification="raw", tenant_id="t-x", project_id="p-y",
        )
        meta = client.head_object(
            Bucket="b", Key=f"vasta/artifacts/{sha[:2]}/{sha}"
        )["Metadata"]
        assert meta["tenant_id"] == "t-x"
        assert meta["project_id"] == "p-y"
        assert meta["mime"] == "image/png"


class TestS3ErrorRouting:
    """评审修复：head/get 异常分流——瞬态故障不再吞为不存在/未删除。"""

    async def test_head_transient_error_raises_not_reupload(self) -> None:
        class FlakyHead(FakeS3Client):
            def head_object(self, *, Bucket, Key):
                raise RuntimeError("503 slow down")

        client = FlakyHead()
        store = S3BlobStore("b", client=client)
        with pytest.raises(VastaError) as excinfo:
            await store.save_artifact(b"x")
        assert excinfo.value.code == "s3.head_failed"
        assert len(client.objects) == 0  # 不盲目重传

    async def test_get_transient_error_not_masquerading_deleted(
            self) -> None:
        class FlakyGet(FakeS3Client):
            def get_object(self, *, Bucket, Key):
                raise RuntimeError("SlowDown: too many requests")

        store = S3BlobStore("b", client=FlakyGet())
        with pytest.raises(VastaError) as excinfo:
            await store.get_artifact("0" * 64)
        # 限流 ≠ 已删除——审计/删除证明语义不被网络抖动污染
        assert excinfo.value.code == "s3.get_failed"

    async def test_get_404_still_not_found(self) -> None:
        class ClientError(RuntimeError):
            """botocore 形态（同名——异常分流按类型名识别）。"""

        class NotFound404(FakeS3Client):
            def get_object(self, *, Bucket, Key):
                raise ClientError(
                    "An error occurred (404) when calling the GetObject")

        store = S3BlobStore("b", client=NotFound404())
        with pytest.raises(VastaError) as excinfo:
            await store.get_artifact("0" * 64)
        assert excinfo.value.code == "artifact.not_found"


class StubPG:
    """stub asyncpg（sys.modules 注入——评审修复锚定用，无真实服务）。"""

    def __init__(self) -> None:
        import types
        from importlib.machinery import ModuleSpec

        self.sql_log: list[tuple[str, tuple]] = []
        self.scope_rows: dict[tuple, int] = {}  # (sha,tenant,project)→1
        self.closed_pools = 0
        mod = types.ModuleType("asyncpg")
        mod.__spec__ = ModuleSpec("asyncpg", "stub")
        mod.create_pool = self._create_pool
        mod.connect = self._connect
        self._mod = mod

    def install(self, monkeypatch) -> None:
        monkeypatch.setitem(__import__("sys").modules, "asyncpg", self._mod)

    # ---- 驱动面 ----
    async def _create_pool(self, dsn, min_size=1):
        return self._make_pool()

    async def _connect(self, dsn):
        return _StubConn(self)

    def _make_pool(self):
        stub = self

        class _Ctx:
            async def __aenter__(self_inner):
                return _StubConn(stub)

            async def __aexit__(self_inner, *exc):
                return False

        class _Pool:
            def acquire(self_inner):
                return _Ctx()

            async def close(self_inner):
                stub.closed_pools += 1

        return _Pool()


class _StubConn:
    def __init__(self, stub: StubPG) -> None:
        self._stub = stub

    async def execute(self, sql, *params):
        self._stub.sql_log.append((sql, params))

    async def fetchrow(self, sql, *params):
        s = " ".join(sql.split())
        if "artifact_scope" in s:
            hit = 1 if tuple(params) in self._stub.scope_rows else None
            return {"ok": hit} if hit else None
        if "FROM events" in s and "ORDER BY seq DESC" in s:
            return None
        return None

    async def fetchval(self, sql, *params):
        row = await self.fetchrow(sql, *params)
        return None if row is None else 1

    async def fetch(self, sql, *params):
        return []

    async def close(self):
        return None


class TestPGBlobComboMetadata:
    """评审修复：blob 组合形态必须落 PG 元数据（scope/entity）——
    曾直接 return，租户可达性与实体检索双失效。"""

    async def test_blob_combo_writes_pg_scope_and_entity(
            self, monkeypatch) -> None:
        from vasta_storage import PostgresEventStore

        stub = StubPG()
        stub.install(monkeypatch)
        blob_calls: list[bytes] = []

        class FakeBlob:
            async def save_artifact(self, payload, **kw):
                blob_calls.append(payload)
                return hashlib.sha256(payload).hexdigest()

            async def get_artifact(self, sha, **kw):
                return b"from-blob"

        store = PostgresEventStore("postgresql://stub/x",
                                   blob_store=FakeBlob())
        sha = await store.save_artifact(
            b"combo-payload", entities={"order": "A1"},
            tenant_id="t-1", project_id="p-1",
        )
        assert blob_calls == [b"combo-payload"]  # 字节走 blob
        sqls = " ".join(s for s, _ in stub.sql_log)
        assert "INSERT INTO artifacts" in sqls  # 占位行（FK 锚）
        assert "INSERT INTO artifact_scope" in sqls  # 租户可达性
        assert "INSERT INTO entity_index" in sqls  # 实体检索
        assert sha == hashlib.sha256(b"combo-payload").hexdigest()

    async def test_pure_pg_get_respects_tenant_reachability(
            self, monkeypatch) -> None:
        from vasta_storage import PostgresEventStore

        stub = StubPG()
        stub.install(monkeypatch)
        store = PostgresEventStore("postgresql://stub/x")
        sha = await store.save_artifact(b"scoped", tenant_id="t-a",
                                        project_id="p-a")
        # t-a 可达（save 已登记）
        stub.scope_rows[(sha, "t-a", "p-a")] = 1
        # t-b 不可达 → not_found（AD-14——曾任何租户知 sha 即可取）
        with pytest.raises(VastaError) as excinfo:
            await store.get_artifact(sha, tenant_id="t-b", project_id="p-b")
        assert excinfo.value.code == "artifact.not_found"

    async def test_pool_created_once_under_concurrency(
            self, monkeypatch) -> None:
        """评审修复：并发首用只建一个 pool（曾双 pool 泄漏）。"""
        import asyncio

        from vasta_storage import PostgresEventStore

        stub = StubPG()
        stub.install(monkeypatch)
        creations = {"n": 0}
        real_create = stub._create_pool

        async def slow_create(dsn, min_size=1):
            creations["n"] += 1
            await asyncio.sleep(0.01)  # 放大交错窗口
            return await real_create(dsn, min_size)

        stub._mod.create_pool = slow_create
        store = PostgresEventStore("postgresql://stub/x")

        # 并发首用：两路同时触发 _ensure_pool
        await asyncio.gather(store._ensure_pool(), store._ensure_pool())
        assert creations["n"] == 1  # 只建一个
    def test_missing_driver_clear_error(self) -> None:
        """无 asyncpg 时构造期明确报错（不静默降级）。"""
        import sys

        from vasta_storage import PostgresEventStore

        had = sys.modules.pop("asyncpg", None)
        try:
            # 模拟无驱动：注入 None 使 import 失败路径可测
            import builtins

            real_import = builtins.__import__

            def no_asyncpg(name, *a, **kw):
                if name == "asyncpg":
                    raise ImportError("no asyncpg")
                return real_import(name, *a, **kw)

            builtins.__import__ = no_asyncpg
            try:
                PostgresEventStore("postgresql://localhost/x")
            except VastaError as exc:
                assert exc.code == "pg.driver_missing"
            else:
                pytest.fail("应报 pg.driver_missing")
            finally:
                builtins.__import__ = real_import
        finally:
            if had is not None:
                sys.modules["asyncpg"] = had

    @pytest.mark.skipif(
        not __import__("os").environ.get("VASTA_PG_DSN"),
        reason="VASTA_PG_DSN 未设——PG 集成测试跳过（DSN 门控）",
    )
    async def test_contract_suite_against_pg(self) -> None:
        """DSN 存在时：核心 StorageAdapter 契约对 PG 全绿。

        评审修复：曾导入不存在的 FakeStorageContract（死码——
        DSN 一设即 ImportError）；实为 StorageAdapterContract。"""
        import os

        from vasta_protocols.contract_suites.storage import (
            StorageAdapterContract,
        )
        from vasta_storage import PostgresEventStore

        class PGContract(StorageAdapterContract):
            def make_adapter(self):
                return PostgresEventStore(os.environ["VASTA_PG_DSN"])

        contract = PGContract()
        await contract.test_event_roundtrip()
        await contract.test_duplicate_seq_rejected()
        await contract.test_artifact_roundtrip_verified_by_hash()
        await contract.test_unknown_artifact_raises()
