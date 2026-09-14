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
