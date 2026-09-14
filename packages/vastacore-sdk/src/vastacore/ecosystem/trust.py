"""验证发布者、安全扫描与兼容矩阵（Story 12.7，FR-083，G3）。

安装前可判别——三个信任面：

- **verify_publisher**：发布者身份验证标记留痕
  （``artifact.publisher_verified``——身份绑定证据入 payload，
  判别可审计）；
- **security_scan**：扫描门——静态依赖面（depends_on 全部在注册表）
  + airgap 违例（清单 egress 复扫）→ ``artifact.security_scanned``
  留痕（passed/violations）；**不通过即拒公开**（12.8 发现面只列
  扫描通过的插件——``scan_passed`` 投影）；
- **compatibility_matrix / compatible_with**：平台版本 × 插件版本
  兼容矩阵（registry 投影 × 清单 compatibility.platform 约束解析）。
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

from ..governance.byok import airgap_check
from ..governance.rbac import Principal
from .manifest import SignedPlugin
from .registry import _REGISTRY_RUN, _project_registry, _require_registry_write


class PublisherVerification(BaseModel):
    """发布者验证标记（投影）。"""

    model_config = ConfigDict(extra="forbid")

    publisher: str
    verified_by: str
    evidence: dict[str, str] = Field(
        description="身份绑定证据（如 idp_subject/org——BYOK/IdP 语义）")


def _publisher_verifications(
    store: Any, *, tenant_id: str, project_id: str,
) -> dict[str, PublisherVerification]:
    result: dict[str, PublisherVerification] = {}
    for event in store.iter_run_events(
            _REGISTRY_RUN, tenant_id=tenant_id, project_id=project_id):
        if event.type == "artifact.publisher_verified":
            p = event.payload
            result[p["publisher"]] = PublisherVerification(
                publisher=p["publisher"], verified_by=p["verified_by"],
                evidence=p.get("evidence", {}))
    return result


async def verify_publisher(
    store: Any, publisher: str, *, principal: Principal,
    evidence: dict[str, str],
) -> PublisherVerification:
    """发布者身份验证留痕（治理动作——registry write 主体执行）。"""
    if not evidence:
        raise VastaError(
            code="trust.evidence_required",
            message="发布者验证必须携带身份绑定证据（idp/org 等）",
        )
    _require_registry_write(principal)
    sequencer = EventSequencer(
        store, _REGISTRY_RUN,
        tenant_id=principal.tenant_id, project_id=principal.project_id)
    await sequencer.emit("artifact.publisher_verified", {
        "publisher": publisher, "verified_by": principal.user,
        "evidence": evidence,
    })
    return PublisherVerification(publisher=publisher,
                                 verified_by=principal.user,
                                 evidence=evidence)


def is_publisher_verified(
    store: Any, publisher: str, *,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> bool:
    return publisher in _publisher_verifications(
        store, tenant_id=tenant_id, project_id=project_id)


class ScanResult(BaseModel):
    """安全扫描结果（投影）。"""

    model_config = ConfigDict(extra="forbid")

    plugin_id: str
    version: str
    passed: bool
    content_sha256: str = ""
    violations: list[str] = Field(default_factory=list)


def _scans(
    store: Any, *, tenant_id: str, project_id: str,
) -> dict[tuple[str, str], ScanResult]:
    result: dict[tuple[str, str], ScanResult] = {}
    for event in store.iter_run_events(
            _REGISTRY_RUN, tenant_id=tenant_id, project_id=project_id):
        if event.type == "artifact.security_scanned":
            p = event.payload
            result[(p["plugin_id"], p["version"])] = ScanResult(
                plugin_id=p["plugin_id"], version=p["version"],
                passed=p["passed"], violations=p.get("violations", []),
                content_sha256=p.get("content_sha256", ""))
    return result


async def security_scan(
    store: Any, signed: SignedPlugin, *, principal: Principal,
) -> ScanResult:
    """扫描门：静态依赖面 + airgap 违例 → 留痕。

    依赖面：清单 depends_on 的每个插件至少有一个注册版本；airgap
    面：清单 egress 复扫（10.12）。任一违例即 passed=False——12.8
    公开发现面据此拒公开。

    评审修复（SCAN-1，盲审 H3/边界 8-3/8-4）：扫描对象必须在册且
    事件携带 **content_sha256**——扫描结果与被扫内容密码学绑定
    （替扫/陈旧扫描两链封死：scan_passed 比对当前注册条目哈希）。"""
    _require_registry_write(principal)
    manifest = signed.manifest
    entries, _ = _project_registry(
        store, tenant_id=principal.tenant_id,
        project_id=principal.project_id)
    entry = entries.get((manifest.plugin_id, manifest.version))
    if entry is None:
        raise VastaError(
            code="trust.scan_target_not_registered",
            message=(f"插件 {manifest.plugin_id!r}@{manifest.version} "
                     "未注册——扫描对象以注册表为准（不可替扫未入册"
                     "内容）"),
        )
    violations: list[str] = []
    if signed.content_sha256() != entry.content_sha256:
        violations.append("扫描对象与注册条目内容不符（哈希不匹配）")
    for dep in manifest.depends_on:
        if not any(pid == dep for (pid, _v) in entries):
            violations.append(f"依赖插件未注册：{dep}")
    report = airgap_check(
        model_base_urls=tuple(manifest.network["egress"]))
    violations.extend(report.violations)
    result = ScanResult(plugin_id=manifest.plugin_id,
                        version=manifest.version,
                        passed=not violations, violations=violations,
                        content_sha256=entry.content_sha256)
    sequencer = EventSequencer(
        store, _REGISTRY_RUN,
        tenant_id=principal.tenant_id, project_id=principal.project_id)
    await sequencer.emit("artifact.security_scanned", {
        "plugin_id": manifest.plugin_id, "version": manifest.version,
        "passed": result.passed, "violations": violations,
        "content_sha256": entry.content_sha256,
        "scanned_by": principal.user,
    })
    return result


def scan_passed(
    store: Any, plugin_id: str, version: str, *,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> bool:
    """扫描门投影：该版本最近一次扫描通过，**且扫描锚定的
    content_sha256 与当前注册条目一致**（内容漂移即失效——
    fail-closed；未扫描/未注册同样不通过，公开面不列）。"""
    scan = _scans(store, tenant_id=tenant_id,
                  project_id=project_id).get((plugin_id, version))
    if scan is None:
        return False
    entries, _ = _project_registry(
        store, tenant_id=tenant_id, project_id=project_id)
    entry = entries.get((plugin_id, version))
    if entry is None or scan.content_sha256 != entry.content_sha256:
        return False
    return scan.passed


_CONSTRAINT = re.compile(r"^(>=|<=|>|<|==|!=)\s*(\d+(?:\.\d+)*)$")


def satisfies(platform_version: str, constraint: str) -> bool:
    """平台版本是否满足约束（点分数字——右补零对齐比较，评审修复
    VER-1：1.0.0 ≡ 1.0；platform_version 非数字形态抛 VastaError
    而非裸 ValueError）。"""
    from ._versions import compare_versions, parse_version

    m = _CONSTRAINT.match(constraint.strip())
    if m is None:
        raise VastaError(
            code="trust.bad_constraint",
            message=(f"兼容约束 {constraint!r} 不可解析"
                     "（支持 >=/<=/>/</==/!= 点分数字）"),
        )
    op = m.group(1)
    ref = parse_version(m.group(2), field="constraint",
                        code="trust.bad_constraint")
    actual = parse_version(platform_version, field="platform_version")
    cmp = compare_versions(actual, ref)
    return {
        ">=": cmp >= 0, "<=": cmp <= 0, ">": cmp > 0,
        "<": cmp < 0, "==": cmp == 0, "!=": cmp != 0,
    }[op]


def compatibility_matrix(
    store: Any, *, tenant_id: str = "t-default",
    project_id: str = "p-default",
) -> dict[str, dict[str, str]]:
    """兼容矩阵：plugin_id → version → platform 约束（registry 投影
    × 清单 compatibility——已注册版本全量）。"""
    entries, _ = _project_registry(
        store, tenant_id=tenant_id, project_id=project_id)
    manifests = registered_manifests(
        store, tenant_id=tenant_id, project_id=project_id)
    matrix: dict[str, dict[str, str]] = {}
    for (pid, version) in entries:
        manifest = manifests.get((pid, version)) or {}
        matrix.setdefault(pid, {})[version] = \
            (manifest.get("compatibility") or {}).get("platform", "")
    return matrix


def registered_manifests(
    store: Any, *, tenant_id: str, project_id: str,
) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for event in store.iter_run_events(
            _REGISTRY_RUN, tenant_id=tenant_id, project_id=project_id):
        if event.type == "artifact.registered":
            result[(event.payload["plugin_id"],
                    event.payload["version"])] = \
                event.payload.get("manifest") or {}
    return result


def compatible_with(
    store: Any, platform_version: str, *,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> list[tuple[str, str]]:
    """与平台版本兼容的 (plugin_id, version) 清单（active 且约束满足）。"""
    entries, _ = _project_registry(
        store, tenant_id=tenant_id, project_id=project_id)
    manifests = registered_manifests(
        store, tenant_id=tenant_id, project_id=project_id)
    compatible: list[tuple[str, str]] = []
    for (pid, version), entry in entries.items():
        if entry.status != "active":
            continue
        manifest = manifests.get((pid, version)) or {}
        constraint = (manifest.get("compatibility") or {}).get("platform")
        if constraint and satisfies(platform_version, constraint):
            compatible.append((pid, version))
    return sorted(compatible)


__all__ = ["PublisherVerification", "ScanResult",
           "compatibility_matrix", "compatible_with",
           "is_publisher_verified", "registered_manifests", "satisfies",
           "scan_passed", "security_scan", "verify_publisher"]
