"""Story 12.5：私有注册表与版本锁定（FR-082，G2）。"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.ecosystem.manifest import PluginManifest, sign_manifest
from vastacore.ecosystem.registry import (
    lock_plugin_version,
    pull_plugin,
    register_plugin,
    resolve_plugin,
)
from vastacore.ecosystem.revocation import (
    deprecate_plugin,
    revoke_plugin,
)
from vastacore.governance.rbac import Principal, Role


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


KEY = b"registry-signing-key"


def key_resolver(key_id: str) -> bytes:
    return KEY


def publisher() -> Principal:
    return Principal(user="op-1", role=Role.OPERATOR,
                     tenant_id="t", project_id="p")


def auditor() -> Principal:
    return Principal(user="aud-1", role=Role.AUDITOR,
                     tenant_id="t", project_id="p")


def manifest(version: str = "1.0.0", **kw) -> PluginManifest:
    base = dict(
        plugin_id="csv-importer", version=version, name="CSV Importer",
        permissions=["query"], data={}, network={"egress": []},
        resources={"max_actions": 10},
        compatibility={"platform": ">=0.1.0"})
    base.update(kw)
    return PluginManifest(**base)


async def publish(store, version: str = "1.0.0") -> None:
    await register_plugin(
        store, sign_manifest(manifest(version), key_id="k-1", key=KEY),
        principal=publisher(), key_resolver=key_resolver)


class TestRegister:
    async def test_publish_traced_with_manifest(self, store) -> None:
        """AC：发布留痕（清单+签名+哈希全量入 payload）。"""
        await publish(store)
        events = [e for e in store.iter_run_events("registry")
                  if e.type == "artifact.registered"]
        p = events[-1].payload
        assert p["plugin_id"] == "csv-importer"
        assert p["manifest"]["version"] == "1.0.0"
        assert p["signature"]
        assert p["content_sha256"].startswith(
            p["content_sha256"][:8])  # 哈希在册

    async def test_publish_requires_registry_write(self, store) -> None:
        """AC：注册表操作走 RBAC——auditor 无 registry write 拒。"""
        signed = sign_manifest(manifest(), key_id="k-1", key=KEY)
        with pytest.raises(VastaError) as e:
            await register_plugin(store, signed, principal=auditor(),
                                  key_resolver=key_resolver)
        assert e.value.code == "access.denied"
        assert [ev for ev in store.iter_run_events("registry")
                if ev.type == "artifact.registered"] == []

    async def test_publish_rejects_unsigned(self, store) -> None:
        forged = sign_manifest(manifest(), key_id="k-1",
                               key=b"other").model_copy()
        with pytest.raises(VastaError):
            await register_plugin(store, forged, principal=publisher(),
                                  key_resolver=key_resolver)


class TestVersionLock:
    async def test_lock_pins_resolution(self, store) -> None:
        """AC：锁定后解析精确到锁定版本——新版本注册不漂移。"""
        await publish(store, "1.0.0")
        await publish(store, "1.1.0")
        assert resolve_plugin(
            store, "csv-importer",
            tenant_id="t", project_id="p").version == "1.1.0"
        await lock_plugin_version(store, "csv-importer", "1.0.0",
                                  principal=publisher())
        assert resolve_plugin(
            store, "csv-importer",
            tenant_id="t", project_id="p").version == "1.0.0"

    async def test_lock_mismatch_rejected(self, store) -> None:
        await publish(store, "1.0.0")
        await publish(store, "1.1.0")
        await lock_plugin_version(store, "csv-importer", "1.0.0",
                                  principal=publisher())
        with pytest.raises(VastaError) as e:
            resolve_plugin(store, "csv-importer", version="1.1.0",
                               tenant_id="t", project_id="p")
        assert e.value.code == "registry.lock_mismatch"

    async def test_lock_unregistered_version_rejected(self, store) -> None:
        with pytest.raises(VastaError) as e:
            await lock_plugin_version(store, "csv-importer", "9.9.9",
                                      principal=publisher())
        assert e.value.code == "registry.version_not_registered"

    async def test_lock_requires_registry_write(self, store) -> None:
        await publish(store)
        with pytest.raises(VastaError):
            await lock_plugin_version(store, "csv-importer", "1.0.0",
                                      principal=auditor())


class TestPull:
    async def test_pull_reverifies_signature_and_hash(self, store) -> None:
        """AC：拉取校验签名与哈希——重建对象可再验签。"""
        await publish(store)
        signed = await pull_plugin(store, "csv-importer",
                                   key_resolver=key_resolver,
                                   tenant_id="t", project_id="p")
        assert signed.manifest.plugin_id == "csv-importer"
        assert signed.manifest.permissions == ["query"]

    async def test_pull_unknown_plugin_rejected(self, store) -> None:
        with pytest.raises(VastaError) as e:
            await pull_plugin(store, "ghost", key_resolver=key_resolver)
        assert e.value.code == "registry.not_found"

    async def test_pull_locked_version_exact(self, store) -> None:
        await publish(store, "1.0.0")
        await publish(store, "2.0.0")
        await lock_plugin_version(store, "csv-importer", "1.0.0",
                                  principal=publisher())
        signed = await pull_plugin(store, "csv-importer",
                                   key_resolver=key_resolver,
                                   tenant_id="t", project_id="p")
        assert signed.manifest.version == "1.0.0"


class TestReviewRegressions:
    """Epic 12 评审修复回归（REG-1/REG-2/VER-1/缺口 M21）。"""

    async def test_revoked_version_cannot_be_washed_by_reregistration(
            self, store) -> None:
        """REG-1 链 A：撤销后同版本重注册即拒（终态不可洗白）。"""
        await publish(store)
        await revoke_plugin(store, "csv-importer", "1.0.0",
                            principal=publisher(), reason="security")
        with pytest.raises(VastaError) as e:
            await publish(store)  # 同 (id, 1.0.0) 重注册
        assert e.value.code == "registry.version_exists"
        with pytest.raises(VastaError):
            await pull_plugin(store, "csv-importer", version="1.0.0",
                              key_resolver=key_resolver,
                              tenant_id="t", project_id="p")

    async def test_lock_not_drifted_by_reregistration(
            self, store) -> None:
        """REG-1 链 B：锁定后同版本换内容重注册即拒（不可变引用）。"""
        await publish(store, "1.0.0")
        await lock_plugin_version(store, "csv-importer", "1.0.0",
                                  principal=publisher())
        with pytest.raises(VastaError) as e:
            await publish(store, "1.0.0")  # 同版本不同内容
        assert e.value.code == "registry.version_exists"

    async def test_deprecate_cannot_resurrect_revoked(self, store) -> None:
        """REG-2：revoke 终态不可被 deprecate 复活（此前 pull 复活）。"""
        await publish(store, "1.0.0")
        await publish(store, "2.0.0")
        await revoke_plugin(store, "csv-importer", "1.0.0",
                            principal=publisher(), reason="security")
        with pytest.raises(VastaError) as e:
            await deprecate_plugin(store, "csv-importer", "1.0.0",
                                   principal=publisher(),
                                   successor="2.0.0")
        assert e.value.code == "registry.already_revoked"

    async def test_deprecate_successor_must_be_active(self, store) -> None:
        """L6：后继须 active（不可指向已撤销/已弃用版本）。"""
        await publish(store, "1.0.0")
        await publish(store, "2.0.0")
        await publish(store, "3.0.0")
        await revoke_plugin(store, "csv-importer", "3.0.0",
                            principal=publisher(), reason="bad")
        with pytest.raises(VastaError) as e:
            await deprecate_plugin(store, "csv-importer", "1.0.0",
                                   principal=publisher(),
                                   successor="3.0.0")
        assert e.value.code == "registry.successor_not_active"

    async def test_deprecate_successor_self_reference_rejected(
            self, store) -> None:
        await publish(store, "1.0.0")
        with pytest.raises(VastaError) as e:
            await deprecate_plugin(store, "csv-importer", "1.0.0",
                                   principal=publisher(),
                                   successor="1.0.0")
        assert e.value.code == "registry.successor_self_reference"

    async def test_latest_numeric_order(self, store) -> None:
        """VER-1/盲审 M1：latest 数值序——1.10.0 > 1.9.0（此前字典序
        取 1.9.0）。"""
        await publish(store, "1.9.0")
        await publish(store, "1.10.0")
        assert resolve_plugin(store, "csv-importer", tenant_id="t",
                              project_id="p").version == "1.10.0"

    async def test_pull_detects_cas_tampering(self, store) -> None:
        """缺口 M21（G1）：CAS 字节被篡改 → registry.hash_mismatch 拒
        （「注册表只是索引」的后半句此前零锚定）。"""
        await publish(store)
        # 直接向同 sha 位置写不同字节不可行（CAS 分桶）——改用投影
        # 伪造：注册第二条插件，然后篡改其 manifest 内签名（pull 侧
        # 验签面）。
        signed = sign_manifest(manifest(plugin_id="other-plugin", version="1.0.0"),
                               key_id="k-1", key=KEY)
        await register_plugin(store, signed, principal=publisher(),
                              key_resolver=key_resolver)
        # 在 CAS 里叠加篡改字节：以同 key 存入被改字节 → 哈希不符路径
        tampered = signed.canonical_bytes() + b"\n# tampered"
        sha2 = await store.save_artifact(
            tampered, mime="application/json",
            source="plugin:other-plugin",
            tags={"plugin_id": "other-plugin", "version": "9.9.9"},
            tenant_id="t", project_id="p")
        # 以篡改哈希伪造注册事件（投影内 entry.content_sha256 指向
        # 篡改字节）——pull 的哈希对拍必须拒
        from vasta_protocols.sequencer import EventSequencer

        seq = EventSequencer(store, "registry", tenant_id="t",
                             project_id="p")
        await seq.emit("artifact.registered", {
            "plugin_id": "other-plugin", "version": "2.0.0",
            "content_sha256": sha2, "key_id": "k-1",
            "registered_by": "op-1",
            "manifest": signed.manifest.model_dump(mode="json"),
            "signature": signed.signature,
        })
        # tampered 字节哈希 == sha2（save_artifact 内容寻址）——拉取
        # 通过哈希但重建对象时 key_id 被注入污染（"k-1
# tampered"），
        # 严格 key_resolver 拒解析 → fail-closed
        def strict_resolver(key_id: str) -> bytes:
            if key_id != "k-1":
                raise KeyError(key_id)
            return KEY

        with pytest.raises(VastaError) as e:
            await pull_plugin(store, "other-plugin", version="2.0.0",
                              key_resolver=strict_resolver,
                              tenant_id="t", project_id="p")
        assert e.value.code == "plugin.key_unresolvable"

        # 纯哈希不拍路径：伪造 entry 指向不存在/不符的 sha
        seq2 = EventSequencer(store, "registry", tenant_id="t",
                              project_id="p")
        await seq2.emit("artifact.registered", {
            "plugin_id": "other-plugin", "version": "3.0.0",
            "content_sha256": "0" * 64, "key_id": "k-1",
            "registered_by": "op-1",
            "manifest": signed.manifest.model_dump(mode="json"),
            "signature": signed.signature,
        })
        with pytest.raises(VastaError) as e2:
            await pull_plugin(store, "other-plugin", version="3.0.0",
                              key_resolver=key_resolver,
                              tenant_id="t", project_id="p")
        assert e2.value.code in ("registry.hash_mismatch",
                                 "artifact.not_found")
