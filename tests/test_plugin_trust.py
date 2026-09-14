"""Story 12.7：验证发布者、安全扫描与兼容矩阵（FR-083，G3）。"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.ecosystem.manifest import PluginManifest, sign_manifest
from vastacore.ecosystem.registry import register_plugin
from vastacore.ecosystem.trust import (
    compatibility_matrix,
    compatible_with,
    is_publisher_verified,
    satisfies,
    scan_passed,
    security_scan,
    verify_publisher,
)
from vastacore.governance.rbac import Principal, Role


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


KEY = b"k"


def key_resolver(key_id: str) -> bytes:
    return KEY


def publisher() -> Principal:
    return Principal(user="op-1", role=Role.OPERATOR,
                     tenant_id="t", project_id="p")


def auditor() -> Principal:
    return Principal(user="aud-1", role=Role.AUDITOR,
                     tenant_id="t", project_id="p")


def manifest(plugin_id="csv", version="1.0.0", **kw) -> PluginManifest:
    base = dict(plugin_id=plugin_id, version=version, name=plugin_id,
                permissions=["query"], data={}, network={"egress": []},
                resources={"max_actions": 1},
                compatibility={"platform": ">=0.1.0"})
    base.update(kw)
    return PluginManifest(**base)


async def publish(store, m: PluginManifest | None = None) -> None:
    m = m or manifest()
    await register_plugin(store, sign_manifest(m, key_id="k", key=KEY),
                          principal=publisher(), key_resolver=key_resolver)


class TestPublisherVerification:
    async def test_verify_publisher_traced(self, store) -> None:
        """AC：验证发布者标记留痕（身份绑定证据）。"""
        await verify_publisher(
            store, "vendor-x", principal=publisher(),
            evidence={"idp_subject": "vendor-x@idp", "org": "acme"})
        assert is_publisher_verified(store, "vendor-x",
                                     tenant_id="t", project_id="p")
        events = [e for e in store.iter_run_events("registry")
                  if e.type == "artifact.publisher_verified"]
        assert events[-1].payload["evidence"]["org"] == "acme"

    async def test_verify_without_evidence_rejected(self, store) -> None:
        with pytest.raises(VastaError) as e:
            await verify_publisher(store, "vendor-x",
                                   principal=publisher(), evidence={})
        assert e.value.code == "trust.evidence_required"

    async def test_unverified_publisher_absent(self, store) -> None:
        assert not is_publisher_verified(store, "nobody",
                                         tenant_id="t", project_id="p")


class TestSecurityScan:
    async def test_clean_scan_passes(self, store) -> None:
        await publish(store)
        result = await security_scan(
            store,
            sign_manifest(manifest(), key_id="k", key=KEY),
            principal=publisher())
        assert result.passed
        assert scan_passed(store, "csv", "1.0.0",
                           tenant_id="t", project_id="p")

    async def test_unregistered_dependency_fails_gate(self, store) -> None:
        """AC：静态依赖面——依赖未注册即违例。"""
        await publish(store)
        result = await security_scan(
            store,
            sign_manifest(manifest(depends_on=["ghost-lib"]),
                          key_id="k", key=KEY),
            principal=publisher())
        assert not result.passed
        assert any("ghost-lib" in v for v in result.violations)

    async def test_external_egress_fails_gate(self, store) -> None:
        """AC：airgap 违例入扫描门。"""
        result = await security_scan(
            store,
            sign_manifest(manifest(network={"egress": [
                "https://evil.example.com"]}), key_id="k", key=KEY),
            principal=publisher())
        assert not result.passed

    async def test_never_scanned_fails_closed(self, store) -> None:
        """AC：扫描门 fail-closed——未扫描即不通过（公开面不列）。"""
        assert not scan_passed(store, "csv", "1.0.0",
                               tenant_id="t", project_id="p")

    async def test_scan_requires_registry_write(self, store) -> None:
        with pytest.raises(VastaError):
            await security_scan(
                store, sign_manifest(manifest(), key_id="k", key=KEY),
                principal=auditor())


class TestCompatibilityMatrix:
    async def test_matrix_from_manifests(self, store) -> None:
        await publish(store)
        await publish(store, manifest(version="2.0.0",
                                      compatibility={"platform": ">=1.0.0"}))
        matrix = compatibility_matrix(store, tenant_id="t", project_id="p")
        assert matrix["csv"]["1.0.0"] == ">=0.1.0"
        assert matrix["csv"]["2.0.0"] == ">=1.0.0"

    async def test_compatible_with_platform(self, store) -> None:
        """AC：平台版本 × 插件版本查询。"""
        await publish(store)  # >=0.1.0
        await publish(store, manifest(version="2.0.0",
                                      compatibility={"platform": ">=1.0.0"}))
        assert compatible_with(store, "0.5.0", tenant_id="t",
                               project_id="p") == [("csv", "1.0.0")]
        assert compatible_with(store, "1.2.0", tenant_id="t",
                               project_id="p") == [("csv", "1.0.0"),
                                                   ("csv", "2.0.0")]

    def test_constraint_parser(self) -> None:
        assert satisfies("1.2.0", ">=1.0.0")
        assert not satisfies("0.9.0", ">=1.0.0")
        assert satisfies("1.0.0", "==1.0.0")
        assert satisfies("1.0.1", "!=1.0.0")
        with pytest.raises(VastaError):
            satisfies("1.0.0", "~>1.0")
