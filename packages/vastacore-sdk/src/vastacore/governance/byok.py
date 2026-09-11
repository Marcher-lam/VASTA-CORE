"""BYOK 与 air-gapped 形态（Story 10.12，FR-074，G4）。

客户自管密钥与离线部署——敏感环境可用：

- **SecretRef**（BYOK）：密钥**引用**（provider + key_id + 版本）——
  凭证不落库；``resolve(fetcher)`` 运行期解析（KMS/文件/env 注入
  fetcher——AD-4：运行期持有，配置面只有引用）；
- **redact_secrets**：配置落库前脱敏——扫描常见凭证键（api_key/
  token/secret/password/credential）与 ``api://``/``sk-`` 前缀值，
  替换为 ``***byok:<指纹8>``（指纹可比对不可还原）；
- **配置留痕**：``run.secret_ref_configured``（引用三元组，**不含
  密钥本体**——断言守卫）；
- **air-gapped 检查**（airgap_check）：静态扫描配置/存储/适配器面
  的外网依赖——S3 endpoint 非 file://、PG DSN 非 localhost、模型
  base_url 非 localhost/file、http_fetcher 存在 → 违规清单；
  ``offline_capability``：纯本地降级链清单（本地模型适配器 +
  SQLite + 文件 blob——router 降级到本地适配器即离线形态可用）；
- **离线冒烟**：全本地配置 → airgap_check 通过 + 降级链路由到本地
  适配器成功（测试锚定）。
"""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.sequencer import EventSequencer

_ACCESS_RUN = "access"

#: 凭证键黑名单（配置面命中即脱敏）。
_SECRET_KEYS = ("api_key", "apikey", "token", "secret", "password",
                "credential", "credentials", "private_key", "client_secret")

#: 凭证值前缀（启发式——命中即脱敏）。
_SECRET_VALUE_PREFIXES = ("sk-", "api://", "Bearer ")


class SecretRef(BaseModel):
    """密钥引用（BYOK——引用不落本体）。"""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(description="kms|file|env|vault")
    key_id: str = Field(min_length=1)
    version: str = "latest"

    def fingerprint(self) -> str:
        """引用指纹（脱敏标注用——可比对不可还原）。"""
        raw = f"{self.provider}:{self.key_id}:{self.version}"
        return hashlib.sha256(raw.encode()).hexdigest()[:8]

    async def resolve(
        self, fetcher: Any,
    ) -> str:
        """运行期解析（fetcher: async (SecretRef) -> str——生产接
        KMS/Secrets Manager；AD-4：解析产物只在运行期持有）。"""
        value = await fetcher(self)
        if not isinstance(value, str) or not value:
            raise ValueError(f"SecretRef {self.key_id!r} 解析为空")
        return value


def redact_secrets(config: dict[str, Any]) -> dict[str, Any]:
    """配置脱敏（深拷贝不改原——凭证键/值形态替换为指纹标注）。"""
    def redact(value: Any, key_hint: str = "") -> Any:
        if isinstance(value, dict):
            return {k: redact(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [redact(v, key_hint) for v in value]
        if isinstance(value, str):
            key_lower = key_hint.lower()
            if any(marker in key_lower for marker in _SECRET_KEYS):
                return f"***redacted:{_fp(value)}"
            if value.startswith(_SECRET_VALUE_PREFIXES):
                return f"***redacted:{_fp(value)}"
        return value

    return redact(config)


def _fp(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:8]


async def configure_secret_ref(
    store: Any, ref: SecretRef, *, purpose: str,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> None:
    """密钥引用配置留痕（run.secret_ref_configured——**不含本体**：
    落痕前 redact_secrets 断言守卫）。"""
    payload = {"provider": ref.provider, "key_id": ref.key_id,
               "version": ref.version, "purpose": purpose}
    safe = redact_secrets(dict(payload))
    # key_id 本身可能就是敏感命名——指纹面留痕（可比对）
    safe["key_id"] = f"fp:{ref.fingerprint()}"
    sequencer = EventSequencer(
        store, _ACCESS_RUN, tenant_id=tenant_id, project_id=project_id)
    await sequencer.emit("run.secret_ref_configured", safe)


class AirgapReport(BaseModel):
    """air-gapped 检查报告。"""

    model_config = ConfigDict(extra="forbid")

    offline_ready: bool
    violations: list[str] = Field(default_factory=list)
    local_capability: list[str] = Field(default_factory=list)


#: 本地降级链（offline_capability 清单——router 降级到这些即可用）。
LOCAL_CAPABILITY: tuple[str, ...] = (
    "model:local-stub-adapter（替身模型——评测/回放路径全本地）",
    "storage:sqlite（本地档存储）",
    "blob:filesystem（objects/ 目录 CAS）",
    "sandbox:subprocess（受限子进程——无容器依赖）",
)


def _is_local_host(host: str) -> bool:
    return host in ("localhost", "127.0.0.1", "::1", "")


def airgap_check(
    *, s3_endpoints: tuple[str, ...] = (),
    pg_dsns: tuple[str, ...] = (),
    model_base_urls: tuple[str, ...] = (),
    external_http: bool = False,
) -> AirgapReport:
    """外网依赖扫描（静态配置面——违规即清单；file:// 与 localhost
    白名单）。"""
    violations: list[str] = []
    for endpoint in s3_endpoints:
        if not (endpoint.startswith("file://") or _is_local_host(
                _host_of(endpoint))):
            violations.append(f"S3 endpoint 非本地：{endpoint}")
    for dsn in pg_dsns:
        if not _is_local_host(_host_of_pg(dsn)):
            violations.append(f"PG DSN 非本地主机：{_mask_pg(dsn)}")
    for url in model_base_urls:
        if not _is_local_host(_host_of(url)):
            violations.append(f"模型 base_url 非本地：{url}")
    if external_http:
        violations.append("配置了外部 HTTP fetcher（外网依赖）")
    return AirgapReport(
        offline_ready=not violations, violations=violations,
        local_capability=list(LOCAL_CAPABILITY))


def _host_of(url: str) -> str:
    from urllib.parse import urlparse

    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""


def _host_of_pg(dsn: str) -> str:
    if "://" in dsn:
        return _host_of(dsn)
    if "@" in dsn:  # key=value 形态取 host=…；user@host 形态取尾段
        for part in dsn.split():
            if part.startswith("host="):
                return part[5:]
        return dsn.rsplit("@", 1)[-1].split(":")[0].split("/")[0]
    for part in dsn.split():
        if part.startswith("host="):
            return part[5:]
    return ""


def _mask_pg(dsn: str) -> str:
    return dsn.split("@")[-1] if "@" in dsn else dsn


__all__ = ["AirgapReport", "LOCAL_CAPABILITY", "SecretRef",
           "airgap_check", "configure_secret_ref", "redact_secrets"]
