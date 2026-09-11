"""Story 10.9：OIDC 身份集成与 SCIM 同步（FR-071 后半，G3）。

JWT 解析/claims 校验/JWKS 轮换/验签注入/角色映射/身份断言留痕/
SCIM 组约定映射与幂等同步；真实 IdP 门控（VASTA_OIDC_ISSUER）。
"""

from __future__ import annotations

import base64
import json
import time

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.governance.identity import (
    SCIM_GROUP_ROLES,
    OIDCTokenVerifier,
    ScimSync,
    development_resolver_warning,
)
from vastacore.governance.rbac import Role

ISSUER = "https://idp.corp"
AUD = "vastacore"
JWKS_URL = f"{ISSUER}/jwks"
KID = "key-1"


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_token(
    payload: dict, *, kid: str = KID, alg: str = "RS256",
    signature: bytes = b"valid-sig",
) -> str:
    header = {"alg": alg, "kid": kid, "typ": "JWT"}
    return (
        f"{b64u(json.dumps(header).encode())}."
        f"{b64u(json.dumps(payload).encode())}."
        f"{b64u(signature)}"
    )


def claims(**kw) -> dict:
    base = {
        "iss": ISSUER, "aud": AUD, "sub": "user-42",
        "exp": int(time.time()) + 3600,
        "realm_access": {"roles": ["vasta-operator"]},
        "vasta_tenant": "t-a", "vasta_project": "p-a",
    }
    base.update(kw)
    return base


class FakeJWKS:
    """可变 JWKS 服务（测试轮换：换 kid 集）。"""

    def __init__(self) -> None:
        self.kids: list[str] = [KID]
        self.fetches = 0

    async def __call__(self, url: str) -> dict:
        self.fetches += 1
        return {"keys": [{"kid": k, "kty": "RSA", "n": "…", "e": "AQAB"}
                         for k in self.kids]}


def always_valid_sig(signing_input: bytes, signature: bytes,
                     jwk: dict) -> bool:
    return signature == b"valid-sig"


def verifier(jwks=None, sig=always_valid_sig, **kw) -> OIDCTokenVerifier:
    return OIDCTokenVerifier(
        issuer=ISSUER, audience=AUD, jwks_url=JWKS_URL,
        fetcher=jwks or FakeJWKS(), verify_signature=sig, **kw)


class TestJwtVerification:
    async def test_happy_path_maps_principal(self) -> None:
        p = await verifier().verify(make_token(claims()))
        assert p.user == "user-42"
        assert p.role is Role.OPERATOR
        assert (p.tenant_id, p.project_id) == ("t-a", "p-a")

    async def test_role_precedence_highest_wins(self) -> None:
        """多组/多角色声明取最高权限（admin+viewer → admin）。"""
        p = await verifier().verify(make_token(claims(
            realm_access={"roles": ["vasta-viewer", "vasta-admin"]})))
        assert p.role is Role.ADMIN

    async def test_no_role_claim_rejected(self) -> None:
        with pytest.raises(VastaError) as excinfo:
            await verifier().verify(make_token(claims(
                realm_access=None)))
        assert excinfo.value.code == "identity.no_role_claim"

    async def test_expired_rejected(self) -> None:
        with pytest.raises(VastaError) as excinfo:
            await verifier().verify(make_token(claims(
                exp=int(time.time()) - 10)))
        assert excinfo.value.code == "identity.token_expired"

    async def test_iss_mismatch_rejected(self) -> None:
        with pytest.raises(VastaError) as excinfo:
            await verifier().verify(make_token(claims(
                iss="https://evil.example")))
        assert excinfo.value.code == "identity.iss_mismatch"

    async def test_aud_mismatch_rejected(self) -> None:
        with pytest.raises(VastaError) as excinfo:
            await verifier().verify(make_token(claims(aud="other-app")))
        assert excinfo.value.code == "identity.aud_mismatch"

    async def test_alg_whitelist(self) -> None:
        with pytest.raises(VastaError) as excinfo:
            await verifier().verify(make_token(claims(), alg="HS256"))
        assert excinfo.value.code == "identity.bad_alg"

    async def test_bad_signature_rejected(self) -> None:
        with pytest.raises(VastaError) as excinfo:
            await verifier().verify(make_token(
                claims(), signature=b"forged"))
        assert excinfo.value.code == "identity.bad_signature"

    async def test_malformed_token_rejected(self) -> None:
        for bad in ("", "a.b", "a.b.c.d", "!!.?.#"):
            with pytest.raises(VastaError):
                await verifier().verify(bad)

    async def test_jwks_rotation_refetches(self) -> None:
        """kid 未命中→强制重拉（IdP 轮换场景）。"""
        jwks = FakeJWKS()
        v = verifier(jwks=jwks)
        await v.verify(make_token(claims()))  # 首次加载
        assert jwks.fetches == 1
        jwks.kids = ["key-2"]  # 轮换：key-1 撤、key-2 上
        new_token = make_token(claims(), kid="key-2")
        p = await v.verify(new_token)  # 未命中→重拉→成功
        assert p.user == "user-42"
        assert jwks.fetches == 2

    async def test_unknown_kid_rejected(self) -> None:
        with pytest.raises(VastaError) as excinfo:
            await verifier().verify(make_token(claims(), kid="ghost"))
        assert excinfo.value.code == "identity.unknown_kid"


class TestIdentityTrace:
    async def test_resolver_trace_leaves_audit(self, tmp_path) -> None:
        """AC：身份断言审计留痕（run.identity_asserted）。"""

        store = SqliteStorage(tmp_path / "s")
        try:
            resolver = verifier().as_resolver(store=store, trace=True)
            p = await resolver(make_token(claims()))
            assert p is not None
            events = [e for e in store.iter_run_events("access")
                      if e.type == "run.identity_asserted"]
            assert events[-1].payload["user"] == "user-42"
            assert events[-1].payload["iss"] == ISSUER
            assert events[-1].payload["role"] == "operator"
        finally:
            store.close()

    async def test_resolver_swallows_for_401(self) -> None:
        """坏 token → None（401 由依赖工厂统一发）。"""
        resolver = verifier().as_resolver()
        assert await resolver("garbage") is None


class TestScimSync:
    def _sync(self, store, users, groups) -> ScimSync:
        async def fetch(url: str) -> dict:
            if url.endswith("/Users"):
                return {"Resources": users}
            return {"Resources": groups}

        return ScimSync(users_url="https://scim/Users",
                        groups_url="https://scim/Groups", fetcher=fetch)

    async def test_group_convention_mapping(self, tmp_path) -> None:
        """SCIM 组名约定 → 角色映射 + 分配留痕 + 摘要。"""

        store = SqliteStorage(tmp_path / "s")
        try:
            sync = self._sync(
                store,
                users=[{"id": "u1", "userName": "alice@corp"},
                       {"id": "u2", "userName": "bob@corp"}],
                groups=[{"displayName": "vasta-admin",
                         "members": [{"value": "u1"}]},
                        {"displayName": "vasta-viewer",
                         "members": [{"value": "u2"}]}])
            summary = await sync.sync(store, tenant_id="t-a",
                                      project_id="p-a")
            assert summary == {"users_total": 2, "groups_total": 2,
                               "role_mappings": 2,
                               "assignments_written": 2,
                               "revocations_written": 0}
            events = [e for e in store.iter_run_events("access")
                      if e.type == "run.role_assigned"]
            by_user = {e.payload["user"]: e.payload["role"]
                       for e in events}
            assert by_user == {"alice@corp": "admin", "bob@corp": "viewer"}
            synced = [e for e in store.iter_run_events("access")
                      if e.type == "run.scim_synced"]
            assert synced[-1].payload["assignments_written"] == 2
        finally:
            store.close()

    async def test_idempotent_resync(self, tmp_path) -> None:
        """幂等：无变化重同步零分配痕（摘要照落）。"""

        store = SqliteStorage(tmp_path / "s")
        try:
            sync = self._sync(
                store, users=[{"id": "u1", "userName": "a"}],
                groups=[{"displayName": "vasta-operator",
                         "members": [{"value": "u1"}]}])
            await sync.sync(store, tenant_id="t-a", project_id="p-a")
            summary2 = await sync.sync(store, tenant_id="t-a",
                                       project_id="p-a")
            assert summary2["assignments_written"] == 0
            assigns = [e for e in store.iter_run_events("access")
                       if e.type == "run.role_assigned"]
            assert len(assigns) == 1  # 只有一条
        finally:
            store.close()

    async def test_role_change_traces_new_assignment(
            self, tmp_path) -> None:

        store = SqliteStorage(tmp_path / "s")
        try:
            users = [{"id": "u1", "userName": "a"}]
            g1 = [{"displayName": "vasta-viewer",
                   "members": [{"value": "u1"}]}]
            g2 = [{"displayName": "vasta-admin",
                   "members": [{"value": "u1"}]}]
            sync1 = self._sync(store, users, g1)
            await sync1.sync(store, tenant_id="t-a", project_id="p-a")
            sync2 = self._sync(store, users, g2)  # 升组
            s2 = await sync2.sync(store, tenant_id="t-a",
                                  project_id="p-a")
            assert s2["assignments_written"] == 1
            assigns = [e for e in store.iter_run_events("access")
                       if e.type == "run.role_assigned"]
            assert assigns[-1].payload["role"] == "admin"
        finally:
            store.close()

    def test_group_convention_table(self) -> None:
        assert set(SCIM_GROUP_ROLES) == {
            "vasta-admin", "vasta-operator", "vasta-auditor",
            "vasta-viewer"}

    def test_dev_fallback_hint(self) -> None:
        msg = development_resolver_warning()
        assert "VASTA_OIDC_ISSUER" in msg and "开发档" in msg


@pytest.mark.skipif(
    not __import__("os").environ.get("VASTA_OIDC_ISSUER"),
    reason="VASTA_OIDC_ISSUER 未设——真实 IdP 集成测试跳过（门控）",
)
class TestRealIdpIntegration:
    """真实 IdP 联邦（VASTA_OIDC_ISSUER + VASTA_OIDC_TOKEN 门控）。

    环境变量：ISSUER/AUDIENCE/JWKS_URL/TOKEN——生产验签原语由
    VASTA_OIDC_VERIFY_MODULE 指向的模块提供 verify_signature。"""

    def test_real_token_verifies(self) -> None:
        import os

        verifier_ = OIDCTokenVerifier(
            issuer=os.environ["VASTA_OIDC_ISSUER"],
            audience=os.environ.get("VASTA_OIDC_AUDIENCE", "vastacore"),
            jwks_url=os.environ.get(
                "VASTA_OIDC_JWKS_URL",
                f"{os.environ['VASTA_OIDC_ISSUER']}"
                "/.well-known/jwks.json"),
            fetcher=_http_get_json,
            verify_signature=_load_verify(),
        )
        import asyncio

        principal = asyncio.run(
            verifier_.verify(os.environ["VASTA_OIDC_TOKEN"]))
        assert principal.user


def _http_get_json(url: str) -> dict:
    import urllib.request

    with urllib.request.urlopen(url) as resp:  # noqa: S310
        return json.loads(resp.read())


def _load_verify():
    import importlib
    import os

    module = importlib.import_module(
        os.environ.get("VASTA_OIDC_VERIFY_MODULE", ""))
    return module.verify_signature
