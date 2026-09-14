"""插件清单与签名（Story 12.4，FR-080，G1）。

生态的第一道治理面——插件声明自己且清单签名可验：

- **PluginManifest 六面**（FR-080 字面）：权限（permissions——
  工具/动作类别）、数据（data——数据集→访问模式）、网络
  （network.egress——出站端点清单）、资源（resources——预算
  键值）、兼容（compatibility.platform——平台版本约束）全量
  显式——**缺面/空权限拒**（fail-closed）；签名在外层
  （SignedPlugin——签名覆盖清单规范形）；
- **签名参考实现**：HMAC-SHA256（key 注入——同 BYOK 模式；
  生产可换 ed25519，接口不变）；
- **assemble_plugin**：未验签插件拒装配（fail-closed）；清单
  规范形（manifest+签名）哈希入 CAS（save_artifact）；清单
  egress 端点自动并入 airgap 依赖扫描（10.12 联动）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError

#: 签名算法标识（参考实现 HMAC-SHA256——生产可换非对称，接口不变）。
SIGNATURE_ALGORITHM = "hmac-sha256"

#: 签名密钥解析器：key_id → bytes（BYOK 注入——密钥不落库不进清单）。
KeyResolver = Callable[[str], bytes]

#: 兼容面 platform 约束形态（与 trust._CONSTRAINT 同口径——构造期拒
#: 不可解析/空约束，评审修复 L4：discover 与 compatible_with 两面口径）。
_CONSTRAINT_FORM = re.compile(r"^(>=|<=|>|<|==|!=)\s*\d+(?:\.\d+)*$")


class PluginManifest(BaseModel):
    """插件清单（六面显式——FR-080）。"""

    model_config = ConfigDict(extra="forbid")

    plugin_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    permissions: list[str] = Field(
        min_length=1, description="权限面：工具/动作类别白名单（空拒）")
    data: dict[str, str] = Field(
        description="数据面：数据集 → 访问模式（read/write——空即声明无数据访问")
    network: dict[str, list[str]] = Field(
        description="网络面：egress 出站端点清单（空清单即声明无出站）")
    resources: dict[str, float] = Field(
        description="资源面：预算键值（max_actions/max_model_calls/…）")
    compatibility: dict[str, str] = Field(
        description="兼容面：platform → 版本约束（如 >=0.1.0）")
    depends_on: list[str] = Field(
        default_factory=list,
        description="依赖插件 id 清单（12.6 撤销闭包检查用）")

    def model_post_init(self, __context: Any) -> None:
        if any(not perm for perm in self.permissions):
            raise VastaError(
                code="plugin.empty_permissions",
                message="权限项不可为空串（须显式命名可调用面）",
            )
        if "platform" not in self.compatibility:
            raise VastaError(
                code="plugin.missing_compatibility",
                message="兼容面缺 platform 约束（缺面拒——FR-080）",
            )
        if not _CONSTRAINT_FORM.match(
                self.compatibility["platform"].strip()):
            raise VastaError(
                code="plugin.bad_platform_constraint",
                message=(f"兼容面 platform 约束 "
                         f"{self.compatibility['platform']!r} 不可解析"
                         "（须 >=/<=/>/</==/!= 点分数字——构造期拒，"
                         "读侧不再两面口径相反）"),
            )
        if "egress" not in self.network:
            raise VastaError(
                code="plugin.missing_network_face",
                message="网络面缺 egress 键（缺面拒——空清单是合法的"
                        "「声明无出站」）",
            )
        if not self.resources:
            raise VastaError(
                code="plugin.missing_resources",
                message="资源面不可为空（至少一项预算约束）",
            )


def canonical_manifest_bytes(manifest: PluginManifest) -> bytes:
    """清单规范形（排序 JSON——签名与哈希的唯一对象）。"""
    return json.dumps(manifest.model_dump(mode="json"), sort_keys=True,
                      ensure_ascii=False).encode()


def sign_manifest(
    manifest: PluginManifest, *, key_id: str, key: bytes,
) -> SignedPlugin:
    """发布方签名：HMAC-SHA256(清单规范形, key)。"""
    if not key:
        raise VastaError(
            code="plugin.empty_signing_key",
            message="签名密钥不可为空（BYOK 注入面）",
        )
    signature = hmac.new(key, canonical_manifest_bytes(manifest),
                         hashlib.sha256).hexdigest()
    return SignedPlugin(manifest=manifest, signature=signature,
                        key_id=key_id)


class SignedPlugin(BaseModel):
    """已签名插件（清单 + 签名 + 密钥标识）。"""

    model_config = ConfigDict(extra="forbid")

    manifest: PluginManifest
    signature: str = Field(min_length=64)
    key_id: str = Field(min_length=1)
    algorithm: str = Field(default=SIGNATURE_ALGORITHM)

    def canonical_bytes(self) -> bytes:
        """装配/入 CAS 的对象：清单规范形 + 签名/密钥尾行（拉取侧
        据此重建可验签对象）。"""
        return (canonical_manifest_bytes(self.manifest)
                + b"\n# signature:" + self.signature.encode()
                + b"\n# key-id:" + self.key_id.encode())

    def content_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def verify_plugin(
    signed: SignedPlugin, *, key_resolver: KeyResolver,
) -> None:
    """验签（fail-closed）：签名不匹配/算法不符/密钥不可解析即拒。"""
    if signed.algorithm != SIGNATURE_ALGORITHM:
        raise VastaError(
            code="plugin.unknown_algorithm",
            message=(f"签名算法 {signed.algorithm!r} 不受支持"
                     f"（当前 {SIGNATURE_ALGORITHM!r}）"),
        )
    try:
        key = key_resolver(signed.key_id)
    except VastaError:
        raise
    except Exception as exc:
        raise VastaError(
            code="plugin.key_unresolvable",
            message=(f"签名密钥 {signed.key_id!r} 不可解析"
                     f"（{type(exc).__name__}: {exc}）——fail-closed"),
        ) from exc
    expected = hmac.new(
        key, canonical_manifest_bytes(signed.manifest),
        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signed.signature):
        raise VastaError(
            code="plugin.bad_signature",
            message=(f"插件 {signed.manifest.plugin_id!r} 清单签名"
                     "不匹配——未验签插件不装配（fail-closed）"),
        )


async def assemble_plugin(
    store: Any, signed: SignedPlugin, *, key_resolver: KeyResolver,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> dict[str, Any]:
    """装配插件：验签 → 清单入 CAS → airgap 依赖扫描。

    返回 {content_sha256, airgap_violations}——egress 端点自动并入
    airgap 依赖清单（10.12 联动；violations 非空时由装配方决定
    拒或豁免留痕）。"""
    from ..governance.byok import airgap_check

    verify_plugin(signed, key_resolver=key_resolver)
    report = airgap_check(
        model_base_urls=tuple(signed.manifest.network["egress"]),
        strict_local=True)  # item-29：插件出站面不吃 localhost 白名单
    sha = await store.save_artifact(
        signed.canonical_bytes(), mime="application/json",
        source=f"plugin:{signed.manifest.plugin_id}",
        tags={"plugin_id": signed.manifest.plugin_id,
              "version": signed.manifest.version},
        tenant_id=tenant_id, project_id=project_id)
    return {"content_sha256": sha,
            "airgap_violations": list(report.violations)}


__all__ = ["PluginManifest", "SignedPlugin", "assemble_plugin",
           "canonical_manifest_bytes", "sign_manifest", "verify_plugin"]
