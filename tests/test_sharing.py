"""Story 11.6：跨 Agent/项目/组织共享边界（FR-027，G2）。"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.agents.sharing import (
    ShareAcceptance,
    ShareGrant,
    Visibility,
    check_shared_access,
    share_asset,
    unshare_asset,
)
from vastacore.governance.rbac import Principal, Role


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


def grant(visibility=Visibility.PROJECT, **kw) -> ShareGrant:
    base = dict(asset_ref="c1", asset_kind="claim",
                visibility=visibility, publisher_org="org-a",
                publisher_agent="agent-x",
                tenant_id="t-a", project_id="p-a")
    base.update(kw)
    return ShareGrant(**base)


def principal(tenant="t-a", project="p-a") -> Principal:
    return Principal(user="reader", role=Role.AUDITOR,
                     tenant_id=tenant, project_id=project)


class TestShareAsset:
    async def test_project_share_active(self, store) -> None:
        r = await share_asset(store, grant())
        assert r["state"] == "active"
        events = [e for e in store.iter_run_events(
            "sharing", tenant_id="t-a", project_id="p-a")
            if e.type == "claim.shared"]
        assert events[-1].payload["visibility"] == "project"

    async def test_org_share_without_acceptance_pending(
            self, store) -> None:
        """跨组织单边 → pending_bilateral（未授权读取拒）。"""
        r = await share_asset(store, grant(Visibility.ORGANIZATION))
        assert r["state"] == "pending_bilateral"

    async def test_org_share_bilateral_active(self, store) -> None:
        acc = ShareAcceptance(asset_ref="c1", accepting_org="org-b",
                              accepted_by="admin-b")
        r = await share_asset(store, grant(Visibility.ORGANIZATION),
                              acceptance=acc)
        assert r["state"] == "active"
        events = [e for e in store.iter_run_events(
            "sharing", tenant_id="t-a", project_id="p-a")
            if e.type == "claim.shared"]
        assert events[-1].payload["accepting_org"] == "org-b"


class TestAccess:
    def test_private_rejected(self, store) -> None:
        with pytest.raises(VastaError) as e:
            check_shared_access(store, grant(Visibility.PRIVATE),
                                reader=principal(), reader_org="org-a")
        assert e.value.code == "access.denied"

    def test_project_same_scope_ok(self, store) -> None:
        check_shared_access(store, grant(), reader=principal(),
                            reader_org="org-a")

    def test_project_wrong_scope_rejected(self, store) -> None:
        with pytest.raises(VastaError) as e:
            check_shared_access(store, grant(), reader=principal(
                tenant="t-b", project="p-b"), reader_org="org-a")
        assert e.value.code == "access.denied"

    def test_org_same_org_ok(self, store) -> None:
        check_shared_access(store, grant(Visibility.ORGANIZATION),
                            reader=principal(), reader_org="org-a")

    def test_org_other_without_accept_rejected(self, store) -> None:
        with pytest.raises(VastaError) as e:
            check_shared_access(store, grant(Visibility.ORGANIZATION),
                                reader=principal(), reader_org="org-b")
        assert "双边未完成" in str(e.value)

    def test_org_other_with_accept_ok(self, store) -> None:
        check_shared_access(store, grant(Visibility.ORGANIZATION),
                            reader=principal(), reader_org="org-b",
                            accepted_orgs={"org-b"})


class TestUnshare:
    async def test_revoke_traced(self, store) -> None:
        await unshare_asset(store, grant(), revoked_by="admin-a")
        events = [e for e in store.iter_run_events(
            "sharing", tenant_id="t-a", project_id="p-a")
            if e.type == "claim.shared_revoked"]
        assert events[-1].payload["asset_ref"] == "c1"
