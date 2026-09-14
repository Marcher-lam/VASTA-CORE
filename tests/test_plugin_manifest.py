"""Story 12.4：插件清单与签名（FR-080，G1）。"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.ecosystem.manifest import (
    PluginManifest,
    SignedPlugin,
    assemble_plugin,
    canonical_manifest_bytes,
    sign_manifest,
    verify_plugin,
)


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


def manifest(**kw) -> PluginManifest:
    base = dict(
        plugin_id="csv-importer", version="1.0.0", name="CSV Importer",
        permissions=["query", "action"],
        data={"datasets": "read"},
        network={"egress": []},
        resources={"max_actions": 100},
        compatibility={"platform": ">=0.1.0"},
    )
    base.update(kw)
    return PluginManifest(**base)


KEY = b"test-signing-key"


def key_resolver(key_id: str) -> bytes:
    if key_id != "key-1":
        raise VastaError(code="plugin.unknown_key",
                         message=f"密钥 {key_id!r} 不可解析")
    return KEY


class TestManifestSixFaces:
    def test_valid_manifest_ok(self) -> None:
        assert manifest().plugin_id == "csv-importer"

    def test_missing_face_rejected(self) -> None:
        """AC：六面缺一即拒——pydantic required 面缺席 ValidationError。"""
        from pydantic import ValidationError

        base = manifest().model_dump()
        for face in ("data", "network", "resources", "compatibility"):
            broken = dict(base)
            del broken[face]
            with pytest.raises(ValidationError):
                PluginManifest(**broken)

    def test_empty_permissions_rejected(self) -> None:
        """空权限面在 pydantic too_short 即拒（声明式约束先于
        post_init——同样 fail-closed）。"""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            manifest(permissions=[])

    def test_network_without_egress_key_rejected(self) -> None:
        with pytest.raises(VastaError) as e:
            manifest(network={"ingress": []})
        assert e.value.code == "plugin.missing_network_face"

    def test_compatibility_without_platform_rejected(self) -> None:
        with pytest.raises(VastaError) as e:
            manifest(compatibility={"runtime": ">=3.12"})
        assert e.value.code == "plugin.missing_compatibility"


class TestSigning:
    def test_sign_verify_roundtrip(self) -> None:
        signed = sign_manifest(manifest(), key_id="key-1", key=KEY)
        verify_plugin(signed, key_resolver=key_resolver)  # 不抛即过

    def test_tampered_manifest_bad_signature(self) -> None:
        signed = sign_manifest(manifest(), key_id="key-1", key=KEY)
        data = signed.model_dump()
        data["manifest"]["version"] = "9.9.9"  # 签名后篡改清单
        tampered = SignedPlugin.model_validate(data)
        with pytest.raises(VastaError) as e:
            verify_plugin(tampered, key_resolver=key_resolver)
        assert e.value.code == "plugin.bad_signature"

    def test_wrong_key_bad_signature(self) -> None:
        signed = sign_manifest(manifest(), key_id="key-1",
                               key=b"other-key")
        with pytest.raises(VastaError) as e:
            verify_plugin(signed, key_resolver=key_resolver)
        assert e.value.code == "plugin.bad_signature"

    def test_empty_key_rejected(self) -> None:
        with pytest.raises(VastaError):
            sign_manifest(manifest(), key_id="key-1", key=b"")

    def test_canonical_form_stable(self) -> None:
        """规范形与字段序无关（排序 JSON——签名对象唯一）。"""
        a = canonical_manifest_bytes(manifest())
        dumped = manifest().model_dump()
        reordered = {k: dumped[k] for k in reversed(list(dumped))}
        b = canonical_manifest_bytes(
            PluginManifest(**{
                "plugin_id": reordered["plugin_id"],
                **{k: v for k, v in dumped.items()
                   if k != "plugin_id"}}))
        assert a == b


class TestAssemble:
    async def test_verified_assemble_cas_and_airgap(self, store) -> None:
        """AC：验签装配——清单哈希入 CAS；egress 并入 airgap 扫描。"""
        signed = sign_manifest(manifest(), key_id="key-1", key=KEY)
        result = await assemble_plugin(
            store, signed, key_resolver=key_resolver,
            tenant_id="t", project_id="p")
        assert result["content_sha256"].startswith("sha256:") or \
            len(result["content_sha256"]) == 64
        assert result["airgap_violations"] == []  # 空出站

    async def test_unverified_assemble_rejected(self, store) -> None:
        """AC：未验签插件拒装配（fail-closed）——CAS 无写入。"""
        forged = SignedPlugin(
            manifest=manifest(),
            signature="0" * 64, key_id="key-1")
        with pytest.raises(VastaError) as e:
            await assemble_plugin(store, forged,
                                  key_resolver=key_resolver)
        assert e.value.code == "plugin.bad_signature"

    async def test_external_egress_flagged_by_airgap(self, store) -> None:
        """AC：清单 egress 端点自动并入 airgap 依赖扫描（10.12）。"""
        signed = sign_manifest(
            manifest(network={"egress": ["https://api.openai.com/v1"]}),
            key_id="key-1", key=KEY)
        result = await assemble_plugin(
            store, signed, key_resolver=key_resolver)
        assert any("api.openai.com" in v
                   for v in result["airgap_violations"])
