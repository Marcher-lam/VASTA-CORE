"""Story 12.7：验证发布者、安全扫描与兼容矩阵（FR-083，G3）。"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.ecosystem.manifest import PluginManifest, sign_manifest
from vastacore.ecosystem.registry import register_plugin
from vastacore.ecosystem.revocation import dependent_closure
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


async def publish_scanned(store, m: PluginManifest | None = None) -> None:
    """注册 + 扫描通过（公开面/编组面共用前置）。"""
    m = m or manifest()
    signed = sign_manifest(m, key_id="k", key=KEY)
    await register_plugin(store, signed, principal=publisher(),
                          key_resolver=key_resolver)
    await security_scan(store, signed, principal=publisher())


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
        dep_manifest = sign_manifest(
            manifest(version="2.0.0", depends_on=["ghost-lib"]),
            key_id="k", key=KEY)
        await register_plugin(store, dep_manifest, principal=publisher(),
                              key_resolver=key_resolver)
        result = await security_scan(store, dep_manifest,
                                     principal=publisher())
        assert not result.passed
        assert any("ghost-lib" in v for v in result.violations)

    async def test_reregistration_rejected(self, store) -> None:
        """REG-1：同 (pid, version) 重注册即拒（不可变条目）。"""
        await publish(store)
        with pytest.raises(VastaError) as e:
            await register_plugin(
                store, sign_manifest(manifest(), key_id="k", key=KEY),
                principal=publisher(), key_resolver=key_resolver)
        assert e.value.code == "registry.version_exists"

    async def test_scan_unregistered_target_rejected(self, store) -> None:
        """SCAN-1：扫描对象必须在册（不可替扫未入册内容）。"""
        with pytest.raises(VastaError) as e:
            await security_scan(
                store, sign_manifest(manifest(), key_id="k", key=KEY),
                principal=publisher())
        assert e.value.code == "trust.scan_target_not_registered"

    async def test_scan_binds_content_hash(self, store) -> None:
        """SCAN-1 链 A：同 (pid,version) 的另一份字节送扫——内容
        不符即违例，scan_passed 拒。"""
        await publish(store)
        different = sign_manifest(manifest(network={"egress": [
            "https://evil.example.com"]}), key_id="k", key=KEY)
        result = await security_scan(store, different,
                                     principal=publisher())
        assert not result.passed
        assert any("内容不符" in v for v in result.violations)
        assert not scan_passed(store, "csv", "1.0.0",
                               tenant_id="t", project_id="p")

    async def test_external_egress_fails_gate(self, store) -> None:
        """AC：airgap 违例入扫描门（扫描对象须在册——SCAN-1 绑定）。"""
        evil = sign_manifest(manifest(network={"egress": [
            "https://evil.example.com"]}), key_id="k", key=KEY)
        await register_plugin(store, evil, principal=publisher(),
                              key_resolver=key_resolver)
        result = await security_scan(store, evil, principal=publisher())
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


# ==================== Epic 12 评审修复回归 ====================

class TestScanContentBinding:
    """SCAN-1（盲审 H3 链 B）：扫描结果锚定内容哈希。"""

    async def test_stale_scan_not_honored_after_content_change(
            self, store) -> None:
        """链 B 封死：干净注册+扫描通过 → 同版本换内容重注册（现被
        REG-1 拒）——即使绕过，scan_passed 亦比哈希失效。"""
        await publish_scanned(store)  # 1.0.0 干净注册+扫描
        assert scan_passed(store, "csv", "1.0.0",
                           tenant_id="t", project_id="p")
        # 同版本重注册被 REG-1 拒——扫描门的内容绑定由此双保险
        with pytest.raises(VastaError) as e:
            await publish_scanned(store)
        assert e.value.code == "registry.version_exists"
        # 投影层直接锚定：伪造一条 content_sha256 不符的扫描事件
        from vasta_protocols.sequencer import EventSequencer

        seq = EventSequencer(store, "registry", tenant_id="t",
                             project_id="p")
        await seq.emit("artifact.security_scanned", {
            "plugin_id": "csv", "version": "1.0.0", "passed": True,
            "violations": [], "content_sha256": "0" * 64,
            "scanned_by": "op-1"})
        assert not scan_passed(store, "csv", "1.0.0",
                               tenant_id="t", project_id="p")

    async def test_unregistered_target_not_scannable(self, store) -> None:
        """8-3：未注册插件不可扫描（扫描对象以注册表为准）。"""
        with pytest.raises(VastaError) as e:
            await security_scan(
                store, sign_manifest(manifest(), key_id="k", key=KEY),
                principal=publisher())
        assert e.value.code == "trust.scan_target_not_registered"


class TestClosureTermination:
    """缺口 M23：依赖闭包环终止防线。"""

    async def test_cycle_closure_terminates(self, store) -> None:
        """环依赖（a↔b）闭包计算终止且含环成员（`- closure` 是环
        终止防线——突变体在此死循环）。"""
        await publish(store, manifest(plugin_id="a", depends_on=["b"]))
        await publish(store, manifest(plugin_id="b", depends_on=["a"]))
        closure = dependent_closure(store, "a", tenant_id="t",
                                    project_id="p")
        assert closure == ["a", "b"]


class TestAirgapFaces:
    """item-29：分面白名单——插件出站面 localhost 也计违例。"""

    def test_default_face_allows_localhost(self) -> None:
        from vastacore.governance.byok import airgap_check

        report = airgap_check(
            model_base_urls=("http://localhost:8080/v1",))
        assert report.violations == []  # 模型面：本地服务合法

    def test_strict_face_flags_localhost(self) -> None:
        from vastacore.governance.byok import airgap_check

        report = airgap_check(
            model_base_urls=("http://localhost:8080/proxy",),
            strict_local=True)
        assert any("localhost:8080" in v for v in report.violations)

    def test_strict_face_still_allows_file(self) -> None:
        from vastacore.governance.byok import airgap_check

        report = airgap_check(model_base_urls=("file:///data",),
                              strict_local=True)
        assert report.violations == []

    async def test_scan_uses_strict_face(self, store) -> None:
        """security_scan 走 strict 面——localhost 代理插件扫描不过。"""
        proxy = sign_manifest(manifest(network={"egress": [
            "http://localhost:8080/proxy"]}), key_id="k", key=KEY)
        await register_plugin(store, proxy, principal=publisher(),
                              key_resolver=key_resolver)
        result = await security_scan(store, proxy, principal=publisher())
        assert not result.passed
        assert any("localhost:8080" in v for v in result.violations)
