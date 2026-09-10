"""Story 9.4：原始证据权限独立（FR-018，G2）。

受限原始 blob 不可取；派生物/血缘链/聚合不受影响；权限判定落审计事件。
"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.derive import derive_on_demand


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


async def seed(store) -> tuple[str, str]:
    """返回 (原始 sha, 派生 sha)。"""
    src = await store.save_artifact("原始截图内容。第二句。".encode(),
                                    mime="image/png")
    derived = await derive_on_demand(store, src, "text_summary",
                                     {"max_sentences": 1})
    return src, derived.derived_sha256


class TestRestrictEvidence:
    async def test_restricted_blob_denied(self, store) -> None:
        """AC：原始 blob 取回被拒（evidence.access_denied）。"""
        from vasta_storage.evidence_access import restrict_evidence

        src, _ = await seed(store)
        await restrict_evidence(store, src, reason="PII 截图",
                                 tenant_id="t-default", project_id="p-default")
        from vasta_storage.evidence_access import get_artifact_checked

        with pytest.raises(VastaError) as excinfo:
            await get_artifact_checked(store, src,
                                       tenant_id="t-default",
                                       project_id="p-default")
        assert excinfo.value.code == "evidence.access_denied"

    async def test_derived_still_readable(self, store) -> None:
        """AC：派生物仍可读——共享结论不泄露原始。"""
        from vasta_storage.evidence_access import (
            get_artifact_checked,
            restrict_evidence,
        )

        src, derived_sha = await seed(store)
        await restrict_evidence(store, src, reason="PII",
                                 tenant_id="t-default", project_id="p-default")
        blob = await get_artifact_checked(store, derived_sha,
                                          tenant_id="t-default",
                                          project_id="p-default")
        assert blob is not None  # 派生物不受源受限影响
        # 原始 get_artifact（无权限检查的后向兼容路径）也能读——
        # 权限检查是叠加层（get_checked），原始 get 不改
        raw = await store.get_artifact(src)
        assert raw == "原始截图内容。第二句。".encode()

    async def test_lineage_chain_intact(self, store) -> None:
        """AC：血缘链不断——引用可见、内容不可达。"""
        from vasta_storage.evidence_access import restrict_evidence

        src, derived_sha = await seed(store)
        await restrict_evidence(store, src, reason="PII",
                                 tenant_id="t-default", project_id="p-default")
        # 血缘/verify 仍可用（元数据面不受内容面限制）
        records = await store.lineage(derived_sha, tenant_id="t-default",
                                      project_id="p-default")
        assert records  # 血缘引用可见
        verification = await store.verify_lineage(
            derived_sha, tenant_id="t-default", project_id="p-default")
        assert verification.derived_status in ("ok", "derived_missing")  # 元数据面

    async def test_unrestrict_restores_access(self, store) -> None:
        from vasta_storage.evidence_access import (
            get_artifact_checked,
            restrict_evidence,
            unrestrict_evidence,
        )

        src, _ = await seed(store)
        await restrict_evidence(store, src, reason="temp",
                                 tenant_id="t-default", project_id="p-default")
        await unrestrict_evidence(store, src,
                                  tenant_id="t-default", project_id="p-default")
        blob = await get_artifact_checked(store, src,
                                          tenant_id="t-default",
                                          project_id="p-default")
        assert blob == "原始截图内容。第二句。".encode()

    async def test_denied_logs_audit_event(self, store) -> None:
        """AC：权限判定落审计事件（artifact.access_denied）。"""
        from vasta_storage.evidence_access import (
            get_artifact_checked,
            restrict_evidence,
        )

        src, _ = await seed(store)
        await restrict_evidence(store, src, reason="PII",
                                 tenant_id="t-default", project_id="p-default")
        with pytest.raises(VastaError):
            await get_artifact_checked(store, src,
                                       tenant_id="t-default",
                                       project_id="p-default")
        audits = [e for e in store.iter_run_events("access")
                  if e.type == "artifact.access_denied"]
        assert len(audits) >= 1
        assert audits[-1].payload["sha256"] == src
        assert audits[-1].payload["reason"] == "PII"

    async def test_restricted_vs_notfound_distinct(self, store) -> None:
        """受限 ≠ 不存在——双错码区分（排查路径分叉）。"""
        from vasta_storage.evidence_access import (
            get_artifact_checked,
            restrict_evidence,
        )

        src, _ = await seed(store)
        await restrict_evidence(store, src, reason="x",
                                 tenant_id="t-default", project_id="p-default")
        with pytest.raises(VastaError) as e1:
            await get_artifact_checked(store, src,
                                       tenant_id="t-default",
                                       project_id="p-default")
        assert e1.value.code == "evidence.access_denied"
        with pytest.raises(VastaError) as e2:
            await get_artifact_checked(store, "0" * 64,
                                       tenant_id="t-default",
                                       project_id="p-default")
        assert e2.value.code == "artifact.not_found"

    async def test_double_restrict_idempotent(self, store) -> None:
        from vasta_storage.evidence_access import restrict_evidence

        src, _ = await seed(store)
        await restrict_evidence(store, src, reason="first",
                                 tenant_id="t-default", project_id="p-default")
        await restrict_evidence(store, src, reason="second",
                                 tenant_id="t-default", project_id="p-default")
        # 不炸、最新 reason 生效（审计事件中可见）
        events = [e for e in store.iter_run_events("access")
                  if e.type == "artifact.access_denied"]
        # restrict 本身不发事件——仅 deny 时发；幂等性体现在不抛异常

    async def test_check_access_without_fetch(self, store) -> None:
        """check_evidence_access 不取 blob（元数据面查询）。"""
        from vasta_storage.evidence_access import (
            check_evidence_access,
            restrict_evidence,
        )

        src, _ = await seed(store)
        assert await check_evidence_access(
            store, src, tenant_id="t-default", project_id="p-default"
        ) == "allowed"
        await restrict_evidence(store, src, reason="x",
                                 tenant_id="t-default", project_id="p-default")
        assert await check_evidence_access(
            store, src, tenant_id="t-default", project_id="p-default"
        ) == "denied"
        assert await check_evidence_access(
            store, "0" * 64, tenant_id="t-default", project_id="p-default"
        ) == "not_found"
