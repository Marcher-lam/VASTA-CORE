"""Epic 2 评审修复守卫：派生血缘侧。"""

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


async def seed(store: SqliteStorage, *, content: bytes = b"src") -> str:
    return await store.save_artifact(
        content, mime="image/png", source="observation.capture",
        tenant_id=T, project_id=P,
    )


async def derive(store: SqliteStorage, source_sha: str, **overrides) -> str:
    kwargs = dict(
        source_sha256=source_sha,
        transform="summarize",
        params={"k": 1},
        transformer_version="1.0",
        tenant_id=T,
        project_id=P,
    )
    kwargs.update(overrides)
    return await store.save_derived(b"derived-payload", **kwargs)


class TestDerivedSideStatus:
    async def test_derived_missing_marks_records(self, store, tmp_path) -> None:
        """派生 blob 删除 → derived_status=derived_missing，逐记录不虚标 verified。"""
        source_sha = await seed(store)
        derived_sha = await derive(store, source_sha)
        assert (await store.verify_lineage(derived_sha, tenant_id=T, project_id=P)).all_verified

        (tmp_path / "s" / "objects" / derived_sha[:2] / derived_sha).unlink()
        verification = await store.verify_lineage(derived_sha, tenant_id=T, project_id=P)
        assert verification.derived_status == "derived_missing"
        assert verification.derived_retrievable is False
        assert not verification.all_verified
        assert verification.records[0].status == "derived_missing"  # 不虚标

    async def test_derived_corrupted_marks_records(self, store, tmp_path) -> None:
        source_sha = await seed(store)
        derived_sha = await derive(store, source_sha)
        (tmp_path / "s" / "objects" / derived_sha[:2] / derived_sha).write_bytes(b"x")
        verification = await store.verify_lineage(derived_sha, tenant_id=T, project_id=P)
        assert verification.derived_status == "derived_corrupted"
        assert verification.records[0].status == "derived_corrupted"


class TestRegistrationGuards:
    async def test_dangling_source_rejected(self, store) -> None:
        """源不可达 → 拒绝登记悬空血缘（fail-fast）。"""
        with pytest.raises(VastaError) as excinfo:
            await derive(store, "0" * 64)
        assert excinfo.value.code == "lineage.source_unreachable"

    async def test_conflicting_reregistration_rejected(self, store) -> None:
        """同键重登记不同 params/version → 拒绝静默覆盖。"""
        source_sha = await seed(store)
        derived_sha = await derive(store, source_sha)
        with pytest.raises(VastaError) as excinfo:
            await derive(store, source_sha, params={"k": 2})
        assert excinfo.value.code == "lineage.conflict"
        with pytest.raises(VastaError):
            await derive(store, source_sha, transformer_version="2.0")
        # 幂等路径（完全相同）仍通过
        same = await derive(store, source_sha)
        assert same == derived_sha

    async def test_non_json_params_rejected(self, store) -> None:
        source_sha = await seed(store)
        with pytest.raises(VastaError) as excinfo:
            await derive(store, source_sha, params={"t": object()})
        assert excinfo.value.code == "lineage.bad_params"
