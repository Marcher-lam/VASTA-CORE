"""OIDC 身份集成与 SCIM 同步（Story 10.9，FR-071 后半，G3）。

企业 IdP 联邦——10.8 静态 resolver 的生产替换点：

- **OIDCTokenVerifier**：JWT 解析（header.payload.signature——标准库
  base64url）、claims 校验（iss/exp/aud——fail-closed）、JWKS 密钥
  解析与**轮换**（kid 未命中重拉一次）、claims→Principal 映射
  （sub→user / roles claim→Role / vasta_tenant·vasta_project claim→
  作用域）；**验签原语注入**（``verify_signature(signing_input,
  signature, jwk) -> bool``——生产接 cryptography，零新依赖承诺下
  协议面完整可测）；
- **身份断言审计**（AC）：验证成功落 ``run.identity_asserted``
  （sub/iss/role/作用域——access 流可聚合「谁以何身份何时来过」）；
- **ScimSync**：SCIM Users/Groups 拉取（fetcher 注入）→ 组名约定
  （``vasta-admin/operator/auditor/viewer``）→ 角色映射 +
  ``assign_role`` 留痕 + ``run.scim_synced`` 同步摘要（幂等：重复
  同步仅状态变化时留分配痕，摘要每次一条）；
- **门控**：真实 IdP 集成测试走 ``VASTA_OIDC_ISSUER``（先例
  VASTA_PG_DSN——未设 skip）；无 IdP 配置回退 10.8 静态映射
  （开发档——装配面 ``make_principal_resolver``）。
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

from .rbac import Principal, Role, assign_role

_ACCESS_RUN = "access"

#: 组名→角色约定（SCIM Group displayName）。
SCIM_GROUP_ROLES: dict[str, Role] = {
    "vasta-admin": Role.ADMIN,
    "vasta-operator": Role.OPERATOR,
    "vasta-auditor": Role.AUDITOR,
    "vasta-viewer": Role.VIEWER,
}

#: JWKS/SCIM 拉取器（async (url) -> dict——测试注入 fake；生产 httpx）。
Fetcher = Callable[[str], Awaitable[dict[str, Any]]]
#: 验签原语（signing_input: bytes, signature: bytes, jwk: dict → bool）。
SignatureVerifier = Callable[[bytes, bytes, dict[str, Any]], bool]


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class OIDCTokenVerifier:
    """OIDC JWT 验证器（机制面完整；验签原语注入）。

    用法（装配面）::

        verifier = OIDCTokenVerifier(
            issuer="https://idp.corp", audience="vastacore",
            jwks_url="https://idp.corp/.well-known/jwks.json",
            fetcher=httpx_get_json,
            verify_signature=cryptography_verify)
        resolver = verifier.as_resolver(store=store, trace=True)
    """

    def __init__(
        self, *, issuer: str, audience: str, jwks_url: str,
        fetcher: Fetcher,
        verify_signature: SignatureVerifier,
        clock: Callable[[], float] | None = None,
        allowed_algs: tuple[str, ...] = ("RS256", "ES256"),
    ) -> None:
        if not issuer or not audience or not jwks_url:
            raise VastaError(
                code="identity.bad_config",
                message="issuer/audience/jwks_url 均必填（fail-closed）",
            )
        self.issuer = issuer
        self.audience = audience
        self.jwks_url = jwks_url
        self._fetcher = fetcher
        self._verify_signature = verify_signature
        self._clock = clock or time.time
        self.allowed_algs = allowed_algs
        self._jwks: dict[str, dict[str, Any]] = {}
        self._jwks_loaded = False

    # ---- JWKS（kid 索引 + 轮换）----
    async def _load_jwks(self, *, force: bool = False) -> None:
        if self._jwks_loaded and not force:
            return
        doc = await self._fetcher(self.jwks_url)
        keys = doc.get("keys")
        if not isinstance(keys, list):
            raise VastaError(
                code="identity.bad_jwks",
                message="JWKS 无 keys 数组",
            )
        self._jwks = {k["kid"]: k for k in keys if "kid" in k}
        self._jwks_loaded = True

    async def _key_for(self, kid: str) -> dict[str, Any]:
        await self._load_jwks()
        key = self._jwks.get(kid)
        if key is None:
            # 轮换：kid 未命中→强制重拉一次（IdP 轮换后旧缓存失效）
            await self._load_jwks(force=True)
            key = self._jwks.get(kid)
        if key is None:
            raise VastaError(
                code="identity.unknown_kid",
                message=f"JWKS 无 kid {kid!r}（轮换重拉后仍未命中）",
            )
        return key

    # ---- JWT 解析与校验 ----
    def _decode(self, token: str) -> tuple[dict, dict, bytes, bytes]:
        parts = token.split(".")
        if len(parts) != 3:
            raise VastaError(
                code="identity.bad_token",
                message="JWT 须为三段点分形态",
            )
        try:
            header = json.loads(_b64url_decode(parts[0]))
            payload = json.loads(_b64url_decode(parts[1]))
            signature = _b64url_decode(parts[2])
        except (ValueError, json.JSONDecodeError) as exc:
            raise VastaError(
                code="identity.bad_token",
                message=f"JWT 解码失败：{exc}",
            ) from exc
        signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
        return header, payload, signature, signing_input

    def _validate_claims(self, payload: dict[str, Any]) -> None:
        if payload.get("iss") != self.issuer:
            raise VastaError(
                code="identity.iss_mismatch",
                message=f"iss {payload.get('iss')!r} != {self.issuer!r}",
            )
        aud = payload.get("aud")
        if isinstance(aud, str):
            aud = [aud]
        if self.audience not in (aud or []):
            raise VastaError(
                code="identity.aud_mismatch",
                message=f"aud {payload.get('aud')!r} 不含 {self.audience!r}",
            )
        exp = payload.get("exp")
        if not isinstance(exp, (int, float)) or exp < self._clock():
            raise VastaError(
                code="identity.token_expired",
                message=f"exp {exp!r} 已过期或缺失（fail-closed）",
            )

    @staticmethod
    def _role_from_claims(payload: dict[str, Any]) -> Role:
        """claims→角色：realm_access.roles / roles / vasta_role 任一携带
        约定角色名（最高权限优先）。"""
        candidates: list[str] = []
        for path in (("realm_access", "roles"), ("roles",),
                     ("vasta_role",)):
            node: Any = payload
            for key in path:
                node = node.get(key) if isinstance(node, dict) else None
            if isinstance(node, list):
                candidates.extend(str(r) for r in node)
            elif isinstance(node, str):
                candidates.append(node)
        precedence = [Role.ADMIN, Role.OPERATOR, Role.AUDITOR,
                      Role.VIEWER]
        for role in precedence:
            if role.value in candidates or f"vasta-{role.value}" \
                    in candidates:
                return role
        raise VastaError(
            code="identity.no_role_claim",
            message=f"claims 未携带任何约定角色（{candidates}）——拒",
        )

    async def verify(self, token: str) -> Principal:
        """完整验证：解析→算法白名单→JWKS 验签→claims 校验→Principal。"""
        header, payload, signature, signing_input = self._decode(token)
        alg = header.get("alg")
        if alg not in self.allowed_algs:
            raise VastaError(
                code="identity.bad_alg",
                message=f"算法 {alg!r} 不在白名单 {self.allowed_algs}",
            )
        kid = header.get("kid")
        if not kid:
            raise VastaError(
                code="identity.bad_token",
                message="header 缺 kid（JWKS 定位必需）",
            )
        jwk = await self._key_for(kid)
        if not self._verify_signature(signing_input, signature, jwk):
            raise VastaError(
                code="identity.bad_signature",
                message="签名验证失败（fail-closed）",
            )
        self._validate_claims(payload)
        sub = payload.get("sub")
        if not sub:
            raise VastaError(
                code="identity.bad_token",
                message="claims 缺 sub",
            )
        return Principal(
            user=str(sub),
            role=self._role_from_claims(payload),
            tenant_id=str(payload.get("vasta_tenant", "t-default")),
            project_id=str(payload.get("vasta_project", "p-default")),
        )

    def as_resolver(
        self, *, store: Any | None = None, trace: bool = False,
    ) -> Callable[[str], Awaitable[Principal | None]]:
        """适配 10.8 require_role 的 resolver 形态（async 可等待）。

        trace：验证成功落 run.identity_asserted（身份断言审计——AC）。"""

        async def resolve(token: str) -> Principal | None:
            try:
                principal = await self.verify(token)
            except VastaError:
                return None  # 401 由依赖工厂统一
            if trace and store is not None:
                sequencer = EventSequencer(
                    store, _ACCESS_RUN,
                    tenant_id=principal.tenant_id,
                    project_id=principal.project_id)
                await sequencer.emit("run.identity_asserted", {
                    "user": principal.user, "iss": self.issuer,
                    "role": principal.role.value,
                })
            return principal

        return resolve


class ScimSync(BaseModel):
    """SCIM 同步配置（fetcher 注入——生产 httpx，测试 fake）。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    users_url: str
    groups_url: str
    fetcher: Any = Field(description="async (url) -> dict")

    async def sync(
        self, store: Any, *,
        tenant_id: str = "t-default", project_id: str = "p-default",
        assigned_by: str = "scim-sync",
    ) -> dict[str, Any]:
        """拉取 Users/Groups → 组名约定映射 → 角色分配留痕 + 摘要。

        幂等：分配事件仅在用户角色**与上次同步不同**时落（重放
        access 流取用户→角色最新值）。"""
        users_doc = await self.fetcher(self.users_url)
        groups_doc = await self.fetcher(self.groups_url)
        users = {str(u["id"]): str(u.get("userName") or u["id"])
                 for u in users_doc.get("Resources", [])
                 if isinstance(u, dict) and "id" in u}
        groups = groups_doc.get("Resources", [])

        # 现状（重放 access 流——用户→最新角色）
        current: dict[str, str] = {}
        for event in store.iter_run_events(
                _ACCESS_RUN, tenant_id=tenant_id, project_id=project_id):
            if event.type == "run.role_assigned":
                current[event.payload["user"]] = event.payload["role"]

        # 组→成员角色（约定名；一用户多组取最高权限）
        precedence = [Role.ADMIN, Role.OPERATOR, Role.AUDITOR,
                      Role.VIEWER]
        user_roles: dict[str, Role] = {}
        for group in groups:
            if not isinstance(group, dict):
                continue
            role = SCIM_GROUP_ROLES.get(str(group.get("displayName", "")))
            if role is None:
                continue
            for member in group.get("members", []):
                uid = users.get(str(member.get("value", "")))
                if uid is None:
                    continue
                existing = user_roles.get(uid)
                if existing is None or precedence.index(role) < \
                        precedence.index(existing):
                    user_roles[uid] = role

        assigned = 0
        for user, role in sorted(user_roles.items()):
            if current.get(user) == role.value:
                continue  # 幂等：无变化不留痕
            await assign_role(store, user, role, assigned_by=assigned_by,
                              tenant_id=tenant_id, project_id=project_id)
            assigned += 1

        summary = {
            "users_total": len(users),
            "groups_total": len(groups),
            "role_mappings": len(user_roles),
            "assignments_written": assigned,
        }
        sequencer = EventSequencer(
            store, _ACCESS_RUN,
            tenant_id=tenant_id, project_id=project_id)
        await sequencer.emit("run.scim_synced", summary)
        return summary


def development_resolver_warning() -> str:
    """无 IdP 配置时的开发档回退提示（装配面日志面用）。"""
    return ("OIDC 未配置——回退静态 token 映射（开发档，非生产边界；"
            "配置 VASTA_OIDC_ISSUER 启用 IdP 联邦）")


__all__ = ["OIDCTokenVerifier", "SCIM_GROUP_ROLES", "ScimSync",
           "development_resolver_warning"]
