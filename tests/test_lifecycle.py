"""Story 9.3：数据生命周期与删除证明（FR-017，G2）。

删除有证明；法保留/依赖阻删；热温冷分层配置。
"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vasta_storage.lifecycle import (
    LifecyclePolicy,
    place_legal_hold,
    release_legal_hold,
    request_deletion,
)


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


async def put(store, payload: bytes, **kw) -> str:
    return await store.save_artifact(payload, mime="text/plain", **kw)


class TestTierPolicy:
    async def test_classify_by_age(self, store) -> None:
        """AC：热/温/冷分层可配置——按 created_at 天数分类。"""
        from vasta_storage.lifecycle import classify_artifacts

        sha = await put(store, b"old-data")
        # 手动把 created_at 调到 60 天前
        with store._lock, store._conn:  # noqa: SLF001
            store._conn.execute(  # noqa: SLF001
                "UPDATE artifacts SET created_at = datetime('now', '-60 days')"
                " WHERE sha256 = ?", (sha,)
            )
        fresh = await put(store, b"fresh")
        policy = LifecyclePolicy(hot_days=7, warm_days=30)
        report = classify_artifacts(store, policy, tenant_id="t-default",
                                    project_id="p-default")
        by_sha = {r["sha"]: r["tier"] for r in report}
        assert by_sha[sha] == "cold"  # 60 天 > 30 → 冷
        assert by_sha[fresh] == "hot"  # 刚写 → 热

    async def test_tier_thresholds_configurable(self) -> None:
        p = LifecyclePolicy(hot_days=1, warm_days=5)
        assert (p.hot_days, p.warm_days) == (1, 5)


class TestLegalHold:
    async def test_hold_blocks_deletion_with_reason(self, store) -> None:
        """AC：法保留期间删除被拒且返回原因。"""
        sha = await put(store, b"under-hold")
        await place_legal_hold(store, sha, jurisdiction="GDPR",
                               note="litigation 2026-CV-123",
                               tenant_id="t-default", project_id="p-default")
        result = await request_deletion(store, sha, reason="user request",
                                        tenant_id="t-default",
                                        project_id="p-default")
        assert result.status == "blocked"
        assert any("legal.hold_active" in b.code for b in result.blockers)
        # blob 仍在
        assert await store.get_artifact(sha) == b"under-hold"

    async def test_release_then_delete_allowed(self, store) -> None:
        sha = await put(store, b"was-held")
        await place_legal_hold(store, sha, jurisdiction="GDPR", note="x",
                               tenant_id="t-default", project_id="p-default")
        await release_legal_hold(store, sha, tenant_id="t-default",
                                 project_id="p-default")
        result = await request_deletion(store, sha, reason="cleanup",
                                        tenant_id="t-default",
                                        project_id="p-default")
        assert result.status == "deleted"


class TestDeletion:
    async def test_delete_proves_event_without_content(self, store) -> None:
        """AC：执行后留不含内容的证明事件（deletion.proved）。"""
        sha = await put(store, b"to-delete")
        result = await request_deletion(store, sha, reason="retention expiry",
                                        tenant_id="t-default",
                                        project_id="p-default")
        assert result.status == "deleted"
        # 证明事件在 lifecycle 流
        proofs = [e for e in store.iter_run_events("lifecycle")
                  if e.type == "artifact.deletion_proved"]
        assert len(proofs) >= 1
        proof = proofs[-1]
        assert proof.payload["sha256"] == sha
        assert proof.payload["reason"] == "retention expiry"
        # 证明不含原始内容（FR-017 后果）——无任何内容键
        assert "content" not in proof.payload
        assert "payload_bytes" not in proof.payload
        assert "content_preview" not in proof.payload
        assert b"to-delete" not in proof.model_dump_json().encode("utf-8")

    async def test_deleted_artifact_not_found(self, store) -> None:
        """删除后 get 404。"""
        sha = await put(store, b"gone")
        await request_deletion(store, sha, reason="x",
                               tenant_id="t-default", project_id="p-default")
        with pytest.raises(VastaError) as excinfo:
            await store.get_artifact(sha)
        assert excinfo.value.code == "artifact.not_found"

    async def test_idempotent_second_delete(self, store) -> None:
        """已删 sha 再请求 → 成功但不重复发事件。"""
        sha = await put(store, b"idem")
        r1 = await request_deletion(store, sha, reason="x",
                                    tenant_id="t-default",
                                    project_id="p-default")
        assert r1.status == "deleted"
        r2 = await request_deletion(store, sha, reason="x",
                                    tenant_id="t-default",
                                    project_id="p-default")
        assert r2.status == "deleted"  # 幂等
        proofs = [e for e in store.iter_run_events("lifecycle")
                  if e.type == "artifact.deletion_proved"
                  and e.payload.get("sha256") == sha]
        assert len(proofs) == 1  # 不重复

    async def test_derived_dependency_blocks(self, store) -> None:
        """源工件有派生物 → 删除被阻（lifecycle.derived_dependency）。"""
        src = await put(store, b"source")
        await store.save_derived(
            b"derived", source_sha256=src, transform="crop",
            params={}, transformer_version="v1",
            tenant_id="t-default", project_id="p-default",
        )
        result = await request_deletion(store, src, reason="x",
                                        tenant_id="t-default",
                                        project_id="p-default")
        assert result.status == "blocked"
        assert any("derived_dependency" in b.code for b in result.blockers)

    async def test_entity_reference_blocks(self, store) -> None:
        """AC：活跃认知依赖——工件被实体索引引用 → 删除被阻。"""
        sha = await put(store, b"referenced", entities={"order_id": "A102"},
                        tenant_id="t-default", project_id="p-default")
        result = await request_deletion(store, sha, reason="x",
                                        tenant_id="t-default",
                                        project_id="p-default")
        assert result.status == "blocked"
        assert any("entity_reference" in b.code for b in result.blockers)
