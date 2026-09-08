"""Story 2.3：派生血缘与回链校验（FR-012 / AC-03）。"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage

T, P = "t-lin", "p-lin"


@pytest.fixture
async def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


async def seed_source(store: SqliteStorage, content: bytes, *, tenant: str = T) -> str:
    return await store.save_artifact(
        content, mime="image/png", source="observation.capture",
        tenant_id=tenant, project_id=P,
    )


class TestSaveAndLineage:
    async def test_register_and_link_back_full_green(self, store) -> None:
        source_sha = await seed_source(store, b"frame-bytes-1")
        derived_sha = await store.save_derived(
            b'{"summary": "a red square"}',
            source_sha256=source_sha,
            transform="summarize.vision",
            params={"model": "demo-v1", "max_tokens": 64},
            transformer_version="0.3.1",
            tenant_id=T,
            project_id=P,
        )

        records = await store.lineage(derived_sha, tenant_id=T, project_id=P)
        assert len(records) == 1
        rec = records[0]
        assert rec.source_sha256 == source_sha
        assert rec.transform == "summarize.vision"
        assert rec.params == {"model": "demo-v1", "max_tokens": 64}  # 变换参数完整
        assert rec.transformer_version == "0.3.1"  # 版本完整展示

        verification = await store.verify_lineage(derived_sha, tenant_id=T, project_id=P)
        assert verification.all_verified
        assert verification.derived_retrievable
        # AC-03：派生物一键回到原始证据并校验
        source_back = await store.get_artifact(source_sha, tenant_id=T, project_id=P)
        assert source_back == b"frame-bytes-1"

    async def test_multi_source_lineage(self, store) -> None:
        sha_a = await seed_source(store, b"source-a")
        sha_b = await seed_source(store, b"source-b")
        derived = b"merged-extract"
        d1 = await store.save_derived(
            derived, source_sha256=sha_a, transform="merge.extract",
            params={}, transformer_version="1.0", tenant_id=T, project_id=P,
        )
        d2 = await store.save_derived(  # 同派生内容、另一来源：两条血缘
            derived, source_sha256=sha_b, transform="merge.extract",
            params={}, transformer_version="1.0", tenant_id=T, project_id=P,
        )
        assert d1 == d2  # 载荷同内容去重
        records = await store.lineage(d1, tenant_id=T, project_id=P)
        assert {r.source_sha256 for r in records} == {sha_a, sha_b}

    async def test_idempotent_registration(self, store) -> None:
        source_sha = await seed_source(store, b"src")
        kwargs = dict(
            source_sha256=source_sha, transform="summarize",
            params={"k": 1}, transformer_version="1.0", tenant_id=T, project_id=P,
        )
        first = await store.save_derived(b"derived-1", **kwargs)
        await store.save_derived(b"derived-1", **kwargs)
        assert len(await store.lineage(first, tenant_id=T, project_id=P)) == 1


class TestVerifyDegradation:
    async def test_source_deleted_marks_unverifiable(self, store, tmp_path) -> None:
        """AC：源被删除 → '来源不可再验证'，不静默可用。"""
        source_sha = await seed_source(store, b"fragile-source")
        derived_sha = await store.save_derived(
            b"summary-of-fragile", source_sha256=source_sha,
            transform="summarize", params={}, transformer_version="1.0",
            tenant_id=T, project_id=P,
        )
        assert (await store.verify_lineage(derived_sha, tenant_id=T, project_id=P)).all_verified

        blob = tmp_path / "s" / "objects" / source_sha[:2] / source_sha
        blob.unlink()  # 模拟源删除（FR-017 删除生命周期属 Stage 3）

        verification = await store.verify_lineage(derived_sha, tenant_id=T, project_id=P)
        assert not verification.all_verified
        assert verification.records[0].status == "source_missing"

    async def test_source_corrupted_detected(self, store, tmp_path) -> None:
        source_sha = await seed_source(store, b"tamper-target")
        derived_sha = await store.save_derived(
            b"summary", source_sha256=source_sha, transform="summarize",
            params={}, transformer_version="1.0", tenant_id=T, project_id=P,
        )
        blob = tmp_path / "s" / "objects" / source_sha[:2] / source_sha
        blob.write_bytes(b"tampered-content")

        verification = await store.verify_lineage(derived_sha, tenant_id=T, project_id=P)
        assert verification.records[0].status == "source_corrupted"

    async def test_unknown_derived_rejected(self, store) -> None:
        with pytest.raises(VastaError) as excinfo:
            await store.verify_lineage("0" * 64, tenant_id=T, project_id=P)
        assert excinfo.value.code == "lineage.not_found"


class TestScope:
    async def test_lineage_scoped(self, store) -> None:
        source_sha = await seed_source(store, b"scoped-src", tenant="t-a")
        derived_sha = await store.save_derived(
            b"scoped-derived", source_sha256=source_sha, transform="t",
            params={}, transformer_version="1", tenant_id="t-a", project_id=P,
        )
        assert await store.lineage(derived_sha, tenant_id="t-a", project_id=P)
        assert await store.lineage(derived_sha, tenant_id="t-b", project_id=P) == []

    async def test_half_scope_rejected(self, store) -> None:
        with pytest.raises(VastaError):
            await store.lineage("0" * 64, tenant_id=T)  # type: ignore[arg-type]


class TestSchemaMigrationV3:
    async def test_v2_database_upgrades(self, tmp_path) -> None:
        import sqlite3

        root = tmp_path / "v2"
        root.mkdir()
        db = sqlite3.connect(root / "store.db")
        db.execute("PRAGMA user_version=2")
        db.execute(
            "CREATE TABLE artifacts (sha256 TEXT PRIMARY KEY, mime TEXT,"
            " size INTEGER NOT NULL, source TEXT, classification TEXT,"
            " retention TEXT, created_at TEXT NOT NULL, tags_json TEXT NOT NULL DEFAULT '{}')"
        )
        db.commit()
        db.close()

        store = SqliteStorage(root)  # v2→v3：新表 CREATE IF NOT EXISTS
        version = store._conn.execute("PRAGMA user_version").fetchone()[0]  # noqa: SLF001
        assert version == 3
        src = await store.save_artifact(b"s", tenant_id=T, project_id=P)
        d = await store.save_derived(
            b"d", source_sha256=src, transform="t", params={},
            transformer_version="1", tenant_id=T, project_id=P,
        )
        assert (await store.verify_lineage(d, tenant_id=T, project_id=P)).all_verified
        store.close()
