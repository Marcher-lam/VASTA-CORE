"""Story 10.8：RBAC/ABAC 角色模型（FR-071 前半，G3）。

能力矩阵/作用域 ABAC/401-403 端点/拒绝留痕/真实身份/冒名拒/
角色分配留痕/F8 release 租户隔离。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vasta_cognition.cognition import Claim, CognitionService
from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.governance.rbac import (
    Principal,
    Role,
    assign_role,
    evaluate_access,
    make_principal_resolver,
    require_role,
)
from vastacore.governance.release import (
    get_release_status,
    promote_release,
    suspend_release,
)
from vastacore.governance.versioning import publish_model_version

RULESET = {"rules": {}, "goal_check": "done"}
MANIFEST = {"name": "grid", "version": "1.0", "scope": "grid",
            "unknowns": ["u"], "coverage": ["right"]}


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


def principal(role: Role, tenant: str = "t-a", project: str = "p-a",
              user: str = "u1") -> Principal:
    return Principal(user=user, role=role, tenant_id=tenant,
                     project_id=project)


class TestPolicyEvaluation:
    def test_capability_matrix(self) -> None:
        """四档角色能力矩阵：viewer 只读 / operator 读写业务 /
        auditor 读含治理 / admin 全通过。"""
        cases = [
            (Role.VIEWER, "runs", "read", True),
            (Role.VIEWER, "runs", "write", False),
            (Role.VIEWER, "governance", "read", False),
            (Role.OPERATOR, "runs", "write", True),
            (Role.OPERATOR, "governance", "approve", False),
            (Role.AUDITOR, "governance", "read", True),
            (Role.AUDITOR, "governance", "write", False),
            (Role.ADMIN, "governance", "approve", True),
            (Role.ADMIN, "ops", "admin", True),
        ]
        for role, res, act, expected in cases:
            d = evaluate_access(principal(role), res, act,
                                tenant_id="t-a", project_id="p-a")
            assert d.allowed is expected, (role, res, act)

    def test_scope_mismatch_rejected(self) -> None:
        """ABAC 作用域：跨租户/跨项目拒（admin 也不跨——作用域先于
        能力判定）。"""
        d = evaluate_access(principal(Role.ADMIN), "runs", "read",
                            tenant_id="t-b", project_id="p-a")
        assert d.allowed is False
        assert "作用域不匹配" in d.reason

    def test_fail_closed_reason(self) -> None:
        d = evaluate_access(principal(Role.VIEWER), "runs", "write",
                            tenant_id="t-a", project_id="p-a")
        assert not d.allowed and "fail-closed" in d.reason


class TestEndpointEnforcement:
    def _protected_app(self, store, resolver, resource, action,
                       method="post"):
        from fastapi import Depends

        app = FastAPI()
        dep = require_role(resource, action, resolver=resolver,
                           store=store, tenant_id="t-a", project_id="p-a")
        if method == "post":
            @app.post("/t", dependencies=[Depends(dep)])
            async def t():
                return {"ok": 1}
        else:
            @app.get("/t", dependencies=[Depends(dep)])
            async def t():
                return {"ok": 1}
        return app

    def test_401_unknown_token(self, store) -> None:
        resolver = make_principal_resolver({})
        with TestClient(self._protected_app(
                store, resolver, "cognition", "read", method="get")) as c:
            assert c.get("/t", headers={
                "Authorization": "Bearer nope"}).status_code == 401
            assert c.get("/t").status_code == 401

    def test_403_with_deny_trace(self, store) -> None:
        """viewer 访问写端点 → 403 + run.access_denied 留痕。"""
        resolver = make_principal_resolver(
            {"tok-x": principal(Role.VIEWER)})
        with TestClient(self._protected_app(
                store, resolver, "cognition", "write")) as c:
            r = c.post("/t", headers={"Authorization": "Bearer tok-x"})
            assert r.status_code == 403
            assert "无 cognition:write 能力" in r.json()["detail"]

        denied = [e for e in store.iter_run_events("access")
                  if e.type == "run.access_denied"]
        assert denied, "拒绝必须留痕"
        assert denied[-1].payload["user"] == "u1"
        assert denied[-1].payload["resource"] == "cognition"

    def test_allowed_passes_identity(self, store) -> None:
        resolver = make_principal_resolver(
            {"tok-op": principal(Role.OPERATOR, user="op-9")})
        with TestClient(self._protected_app(
                store, resolver, "cognition", "write")) as c:
            r = c.post("/t", headers={"Authorization": "Bearer tok-op"})
            assert r.status_code == 200
            assert r.json() == {"ok": 1}


class TestRoleAssignment:
    async def test_assignment_traced(self, store) -> None:
        await assign_role(store, "alice", Role.OPERATOR,
                          assigned_by="admin-root",
                          tenant_id="t-a", project_id="p-a")
        events = [e for e in store.iter_run_events("access")
                  if e.type == "run.role_assigned"]
        assert events[-1].payload == {
            "user": "alice", "role": "operator",
            "assigned_by": "admin-root"}


class TestStudioRbac:
    def _studio(self, store, role: Role):
        from vastacore.ops.studio import mount_studio

        app = FastAPI()
        mount_studio(app, store=store, token="unused",
                     tenant_id="t-a", project_id="p-a",
                     principal_resolver=make_principal_resolver(
                         {"tok-x": principal(role, user="expert@corp")}))
        return app

    def _seed(self, store):
        import asyncio

        async def seed():
            cog = CognitionService(store, tenant_id="t-a",
                                   project_id="p-a")
            await cog.propose(Claim(
                claim_id="c1", memory_type="guide", statement="s",
                scope={"r": "p"}, evidence=["run-x:0"]))

        asyncio.run(seed())

    def test_viewer_read_but_write_403(self, store) -> None:
        self._seed(store)
        with TestClient(self._studio(store, Role.VIEWER)) as c:
            h = {"Authorization": "Bearer tok-x"}
            assert c.get("/studio/api/claims", headers=h).status_code == 200
            r = c.post("/studio/api/claims/c1/review", headers=h,
                       json={"decision": "approve", "reason": "ok"})
            assert r.status_code == 403  # cognition:write 拒

    def test_operator_review_carries_authenticated_identity(
            self, store) -> None:
        """AC：approver 事件携带真实身份——RBAC 主体注入（body 省略）。"""
        self._seed(store)
        with TestClient(self._studio(store, Role.OPERATOR)) as c:
            h = {"Authorization": "Bearer tok-x"}
            r = c.post("/studio/api/claims/c1/review", headers=h,
                       json={"decision": "approve", "reason": "领域确认"})
            assert r.status_code == 200
            assert r.json()["approval_id"].startswith("apr-claim.review-")
        approvals = [e for e in store.iter_run_events("approvals")
                     if e.type == "action.approval_record"]
        assert approvals[-1].payload["approver"] == "expert@corp"

    def test_impersonation_rejected(self, store) -> None:
        """冒名拒：body.approver 与认证主体不一致 → 403。"""
        self._seed(store)
        with TestClient(self._studio(store, Role.OPERATOR)) as c:
            r = c.post("/studio/api/claims/c1/review",
                       headers={"Authorization": "Bearer tok-x"},
                       json={"decision": "approve",
                             "approver": "someone-else"})
            assert r.status_code == 403
            assert "冒名" in r.json()["detail"]


class TestF8ReleaseTenancy:
    async def test_cross_tenant_release_isolated(self, store) -> None:
        """F8 锚定：同 kind+name 跨租户状态机隔离（各自推进互不干扰）。"""
        for tenant, project in (("t-a", "p-a"), ("t-b", "p-b")):
            await publish_model_version(store, "grid", "1.0.0",
                                        ruleset=RULESET, manifest=MANIFEST,
                                        tenant_id=tenant, project_id=project)
        # 租户 A 推到 testing
        await promote_release(store, "model", "grid", "1.0.0",
                              to="testing", tenant_id="t-a",
                              project_id="p-a")
        # 租户 B 视角：仍是 candidate（不串流）
        assert await get_release_status(store, "model", "grid",
                                        tenant_id="t-b",
                                        project_id="p-b") == "candidate"
        assert await get_release_status(store, "model", "grid",
                                        tenant_id="t-a",
                                        project_id="p-a") == "testing"
        # B 挂起 A 的版本 → 幻影（B 视角无状态）→ candidate→suspended 拒
        with pytest.raises(VastaError):
            await suspend_release(store, "model", "grid", "1.0.0",
                                  reason="x", tenant_id="t-b",
                                  project_id="p-b")
