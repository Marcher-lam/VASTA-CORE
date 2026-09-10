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


class TestPGStore:
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
        """DSN 存在时：核心 StorageAdapter 契约对 PG 全绿。"""
        import os

        from vasta_protocols.contract_suites.storage import (
            FakeStorageContract,
        )
        from vasta_storage import PostgresEventStore

        class PGContract(FakeStorageContract):
            def make_store(self):
                import asyncio

                store = PostgresEventStore(os.environ["VASTA_PG_DSN"])
                loop = asyncio.new_event_loop()
                loop.run_until_complete(store.close())
                return PostgresEventStore(os.environ["VASTA_PG_DSN"])

        contract = PGContract()
        await contract.test_event_roundtrip()
