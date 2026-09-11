"""Epic 10 G3-G5 评审修复锚定（四层评审 patch 项集中）。"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from datetime import UTC, datetime

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.governance.audit_log import audit_log_integrity_statement
from vastacore.governance.billing import (
    BillingPeriod,
    generate_bill,
    optimization_advice,
)
from vastacore.governance.byok import airgap_check, redact_secrets
from vastacore.governance.data_policy import DataPolicy, verify_residency
from vastacore.governance.identity import OIDCTokenVerifier
from vastacore.governance.quotas import CostLedger
from vastacore.governance.rbac import Principal, require_role
from vastacore.governance.release import (
    get_canary_percent,
    revoke_release,
    set_canary_percent,
)
from vastacore.governance.versioning import publish_model_version

ISSUER = "https://idp.corp"
RULESET = {"rules": {}, "goal_check": "done"}
MANIFEST = {"name": "grid", "version": "1.0", "scope": "grid",
            "unknowns": ["u"], "coverage": ["right"]}


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def oidc_token(role: str = "vasta-admin", sub: str = "user-42") -> str:
    payload = {"iss": ISSUER, "aud": "vastacore", "sub": sub,
               "exp": int(time.time()) + 3600,
               "realm_access": {"roles": [role]},
               "vasta_tenant": "t-a", "vasta_project": "p-a"}
    header = {"alg": "RS256", "kid": "key-1", "typ": "JWT"}
    return (f"{b64u(json.dumps(header).encode())}."
            f"{b64u(json.dumps(payload).encode())}."
            f"{b64u(b'valid-sig')}")


def oidc_resolver(store):
    async def fetch(url):
        return {"keys": [{"kid": "key-1", "kty": "RSA"}]}

    def sig_ok(inp, sig, jwk):
        return sig == b"valid-sig"

    verifier = OIDCTokenVerifier(
        issuer=ISSUER, audience="vastacore",
        jwks_url=f"{ISSUER}/jwks", fetcher=fetch,
        verify_signature=sig_ok)
    return verifier.as_resolver(store=store, trace=True)


class TestOidcRbacIntegration:
    """H-1/F1 锚定：async resolver × require_role 组合（原 500）。"""

    def test_oidc_token_through_require_role(self, store) -> None:
        from fastapi import Depends as _D

        app = FastAPI()

        @app.get("/x", dependencies=[_D(require_role(
            "cognition", "read", resolver=oidc_resolver(store),
            tenant_id="t-a", project_id="p-a"))])
        async def x():
            return {"ok": 1}



        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/x", headers={
                "Authorization": f"Bearer {oidc_token()}"})
            assert r.status_code == 200  # 曾 500（coroutine 未 await）
            assert c.get("/x").status_code == 401
            assert c.get("/x", headers={
                "Authorization": "Bearer bad"}).status_code == 401

    def test_oidc_viewer_write_403(self, store) -> None:
        app = FastAPI()

        @app.post("/w", dependencies=[Depends(require_role(
            "cognition", "write", resolver=oidc_resolver(store),
            tenant_id="t-a", project_id="p-a"))])
        async def w():
            return {}

        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.post("/w", headers={
                "Authorization": f"Bearer {oidc_token('vasta-viewer')}"})
            assert r.status_code == 403

    def test_malformed_token_is_401_not_500(self, store) -> None:
        """M-6/F5：畸形 JWT 结构（数组 payload/int aud）→ 401。"""
        app = FastAPI()

        @app.get("/x", dependencies=[Depends(require_role(
            "cognition", "read", resolver=oidc_resolver(store),
            tenant_id="t-a", project_id="p-a"))])
        async def x():
            return {}

        # payload 是 JSON 数组
        array_tok = (f"{b64u(json.dumps({'alg': 'RS256', 'kid': 'k'}).encode())}."
                     f"{b64u(b'[1,2]')}.{b64u(b'valid-sig')}")
        with TestClient(app, raise_server_exceptions=False) as c:
            assert c.get("/x", headers={
                "Authorization": f"Bearer {array_tok}"}).status_code == 401


class TestRevokeTenancy:
    async def test_revoke_tenant_scoped_irreversible(self, store) -> None:
        """H-2/F3 锚定：非默认租户 revoke——终态不可重复吊销。"""
        await publish_model_version(store, "grid", "1.0.0",
                                    ruleset=RULESET, manifest=MANIFEST,
                                    tenant_id="t-a", project_id="p-a")
        await revoke_release(store, "model", "grid", "1.0.0",
                             reason="bad", approver="sec",
                             tenant_id="t-a", project_id="p-a")
        with pytest.raises(VastaError) as excinfo:
            await revoke_release(store, "model", "grid", "1.0.0",
                                 reason="again", approver="sec",
                                 tenant_id="t-a", project_id="p-a")
        assert excinfo.value.code == "release.invalid_transition"

    async def test_canary_tenant_isolated(self, store) -> None:
        """M-7/F14 锚定：canary 配置按租户隔离。"""
        await set_canary_percent(store, "model", "grid", 25,
                                 tenant_id="t-a", project_id="p-a")
        assert await get_canary_percent(
            store, "model", "grid",
            tenant_id="t-a", project_id="p-a") == 25
        assert await get_canary_percent(
            store, "model", "grid",
            tenant_id="t-b", project_id="p-b") == 100  # 隔离


class TestAuditChain:
    def test_chain_detects_payload_tamper(self, store) -> None:
        """M-4/F4/G2① 锚定：篡改 payload → 摘要变化（曾全信封盲区）。"""
        from vasta_protocols.sequencer import EventSequencer

        async def seed():
            await EventSequencer(store, "access").emit(
                "run.role_assigned",
                {"user": "alice", "role": "viewer",
                 "assigned_by": "root"})
        asyncio.run(seed())
        s1 = audit_log_integrity_statement(store)
        # 篡改 payload（role viewer → admin）
        with store._lock, store._conn:  # noqa: SLF001——测试注入篡改
            row = store._conn.execute(  # noqa: SLF001
                "SELECT seq, data FROM events WHERE run_id='access'"
                " LIMIT 1").fetchone()
            payload = json.loads(row[1])
            payload["payload"]["role"] = "admin"
            store._conn.execute(
                "UPDATE events SET data=? WHERE run_id='access' AND seq=?",
                (json.dumps(payload, ensure_ascii=False), row[0]))
        s2 = audit_log_integrity_statement(store)
        assert s1["chain_sha256_tail"] != s2["chain_sha256_tail"]


class TestBillingFixes:
    async def test_concurrent_bill_versions_unique(self, store) -> None:
        """M-1/F10 锚定：并发生成版本唯一（锁串行）。"""
        await CostLedger.record(store, "run-1", tenant_id="t",
                                project_id="p", model="m",
                                estimated_cost=0.1, basis="usage")
        period = BillingPeriod(
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 2, 1, tzinfo=UTC))
        b1, b2 = await asyncio.gather(
            generate_bill(store, period, tenant_id="t", project_id="p"),
            generate_bill(store, period, tenant_id="t", project_id="p"))
        assert {b1.bill_version, b2.bill_version} == {1, 2}

    def test_inverted_period_rejected(self) -> None:
        with pytest.raises(ValueError):
            BillingPeriod(start=datetime(2026, 2, 1, tzinfo=UTC),
                          end=datetime(2026, 1, 1, tzinfo=UTC))

    async def test_period_boundary_right_open(self, store) -> None:
        """G2② 锚定：恰在 end 时刻的记录不计入（月末衔接不重计）。"""
        ts = datetime(2026, 2, 1, 0, 0, 0, tzinfo=UTC)  # = period end
        await CostLedger.record(store, "r-end", tenant_id="t",
                                project_id="p", model="m",
                                estimated_cost=5.0, basis="usage")
        # 调期（测试工具——回拨 ts）
        with store._lock, store._conn:  # noqa: SLF001
            row = store._conn.execute(  # noqa: SLF001
                "SELECT seq, data FROM events WHERE run_id='billing'"
                " ORDER BY seq DESC LIMIT 1").fetchone()
            payload = json.loads(row[1])
            payload["ts"] = ts.isoformat()
            store._conn.execute(
                "UPDATE events SET data=?, ts=? WHERE run_id='billing'"
                " AND seq=?",
                (json.dumps(payload, ensure_ascii=False),
                 ts.isoformat(), row[0]))
        period = BillingPeriod(
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 2, 1, tzinfo=UTC))
        bill = await generate_bill(store, period, tenant_id="t",
                                   project_id="p")
        assert bill.total == 0  # end 时刻记录不入 1 月账

    async def test_negative_budget_tolerated(self, store) -> None:
        """F19：负预算不裸崩（utilization=None）。"""
        period = BillingPeriod(
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 2, 1, tzinfo=UTC))
        report = await optimization_advice(
            store, period, tenant_id="t", project_id="p",
            budget_total=-1)
        assert report.utilization is None


class TestScimRevocation:
    async def test_removed_member_revoked(self, store) -> None:
        """M-3/F13 锚定：移出全部组 → run.role_revoked（撤权生效）。"""
        from vastacore.governance.identity import ScimSync

        users = [{"id": "u1", "userName": "alice"}]

        # 直接构造两个 sync（fetcher 分开）
        async def fetch_in(url):
            if url.endswith("/Users"):
                return {"Resources": users}
            return {"Resources": [{"displayName": "vasta-admin",
                                   "members": [{"value": "u1"}]}]}

        async def fetch_out(url):
            if url.endswith("/Users"):
                return {"Resources": users}
            return {"Resources": []}  # 无任何组

        s1 = ScimSync(users_url="https://s/Users",
                      groups_url="https://s/Groups", fetcher=fetch_in)
        summary1 = await s1.sync(store, tenant_id="t", project_id="p")
        assert summary1["assignments_written"] == 1
        s2 = ScimSync(users_url="https://s/Users",
                      groups_url="https://s/Groups", fetcher=fetch_out)
        summary2 = await s2.sync(store, tenant_id="t", project_id="p")
        assert summary2["revocations_written"] == 1
        revoked = [e for e in store.iter_run_events("access")
                   if e.type == "run.role_revoked"]
        assert revoked[-1].payload["user"] == "alice"


class TestAirgapAndRedact:
    def test_schemeless_external_host_flagged(self) -> None:
        """F9：无 scheme 的外部主机不再误判本地。"""
        report = airgap_check(
            model_base_urls=("db.prod.corp:5432/v1",),
            s3_endpoints=("s3.example.com:9000",))
        assert report.offline_ready is False
        assert len(report.violations) == 2

    def test_kv_dsn_password_masked(self) -> None:
        """F8：key=value DSN 密码不进报告。"""
        report = airgap_check(pg_dsns=(
            "password=hunter2 host=db.prod.corp dbname=x",))
        joined = " ".join(report.violations)
        assert "hunter2" not in joined
        assert "password=***" in joined

    def test_redact_word_boundary(self) -> None:
        """F16b：token 子串键不误伤（next_page_token 保真）。"""
        safe = redact_secrets({
            "next_page_token": "abc123",  # 分页游标非密钥
            "api_key": "sk-real",
            ("t",): "tuple-key-ok",  # 非 str 键不崩
        })
        assert safe["next_page_token"] == "abc123"
        assert safe["api_key"].startswith("***redacted:")


class TestResidencyMultiMark:
    def test_multiple_marks_all_checked(self, tmp_path) -> None:
        """F15：多重 region 标记全查（首段合规不再放行整体）。"""
        policy = DataPolicy(region="eu-west",
                            retention_rules=[{
                                "classification": "x", "retain_days": 1}])
        v = verify_residency(
            tmp_path / "region-eu-west" / "region-us-east" / "s", policy)
        assert v and any("us-east" in x for x in v)


class TestServiceRbacIntegration:
    """M-2/G2④ 锚定：service 全端点 RBAC 接线。"""

    def test_all_data_endpoints_enforced(self, tmp_path) -> None:
        from tests.test_agent_sdk import STATUS_CONTRACT, SetStatusTool, TodoEnv
        from vastacore.governance.rbac import Role as R
        from vastacore.governance.rbac import make_principal_resolver
        from vastacore.ops.service import create_app

        resolver = make_principal_resolver({
            "tok-view": Principal(user="v", role=R.VIEWER,
                                  tenant_id="t-default",
                                  project_id="p-default")})
        app = create_app(
            env_factory=TodoEnv, tools=[SetStatusTool()],
            contracts={"set_status": STATUS_CONTRACT},
            root=tmp_path, token="shared",
            principal_resolver=resolver)
        with TestClient(app, raise_server_exceptions=False) as c:
            h = {"Authorization": "Bearer tok-view"}
            # viewer 可以创建（runs.write？不——viewer 只有 read）
            assert c.post("/runs", json={"seed": 1},
                          headers=h).status_code == 403
            # 共享 token 在 RBAC 模式下对数据端点全部失效
            for path, method in (
                    ("/runs", "post"), ("/runs/r1/start", "post"),
                    ("/runs/r1/act", "post"), ("/runs/r1/reset", "post"),
                    ("/runs/r1/complete", "post"),
                    ("/runs/r1/summary", "get"),
                    ("/runs/r1/timeline", "get"),
                    ("/evidence/search?q=x", "get"),
                    ("/metrics", "get")):
                r = getattr(c, method)(path, headers={
                    "Authorization": "Bearer shared"})
                assert r.status_code == 401, (path, r.status_code)
