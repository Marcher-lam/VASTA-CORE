"""Story 12.6：撤销与弃用生命周期（FR-082，G2）。"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.ecosystem.manifest import PluginManifest, sign_manifest
from vastacore.ecosystem.registry import (
    pull_plugin,
    register_plugin,
    resolve_plugin,
)
from vastacore.ecosystem.revocation import (
    dependent_closure,
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


async def publish(store, plugin_id: str, version: str = "1.0.0",
                  depends_on: list[str] | None = None) -> None:
    await register_plugin(
        store,
        sign_manifest(
            PluginManifest(
                plugin_id=plugin_id, version=version, name=plugin_id,
                permissions=["query"], data={}, network={"egress": []},
                resources={"max_actions": 10},
                compatibility={"platform": ">=0.1.0"},
                depends_on=depends_on or []),
            key_id="k-1", key=KEY),
        principal=publisher(), key_resolver=key_resolver)


class TestRevoke:
    async def test_revoke_immediate_and_pull_rejected(self, store) -> None:
        """AC：撤销立即生效——pull 拒（新装配拒）。"""
        await publish(store, "lib-a")
        closure = await revoke_plugin(
            store, "lib-a", "1.0.0", principal=publisher(),
            reason="supply-chain compromise")
        assert closure == []
        # 显式版本拉取 → 撤销状态检出拒（latest 解析路径为
        # not_found——同样拒）
        with pytest.raises(VastaError) as e:
            await pull_plugin(store, "lib-a", version="1.0.0",
                              key_resolver=key_resolver,
                              tenant_id="t", project_id="p")
        assert e.value.code == "registry.not_active"
        with pytest.raises(VastaError) as latest:
            await pull_plugin(store, "lib-a", key_resolver=key_resolver,
                              tenant_id="t", project_id="p")
        assert latest.value.code == "registry.not_found"

    async def test_revoke_lists_dependent_closure(self, store) -> None:
        """AC：撤销前列出下游依赖（传递闭包——B 不静默破坏）。"""
        await publish(store, "lib-a")
        await publish(store, "tool-b", depends_on=["lib-a"])
        await publish(store, "app-c", depends_on=["tool-b"])
        closure = await revoke_plugin(
            store, "lib-a", "1.0.0", principal=publisher(),
            reason="security")
        assert closure == ["app-c", "tool-b"]  # 传递闭包
        events = [ev for ev in store.iter_run_events("registry")
                  if ev.type == "artifact.revoked"]
        assert events[-1].payload["dependent_plugins"] == closure
        assert events[-1].payload[
            "running_instances_disposition_required"] is True

    async def test_revoke_without_reason_rejected(self, store) -> None:
        await publish(store, "lib-a")
        with pytest.raises(VastaError) as e:
            await revoke_plugin(store, "lib-a", "1.0.0",
                                principal=publisher(), reason="")
        assert e.value.code == "registry.revocation_reason_required"

    async def test_revoke_twice_rejected(self, store) -> None:
        await publish(store, "lib-a")
        await revoke_plugin(store, "lib-a", "1.0.0",
                            principal=publisher(), reason="x")
        with pytest.raises(VastaError) as e:
            await revoke_plugin(store, "lib-a", "1.0.0",
                                principal=publisher(), reason="y")
        assert e.value.code == "registry.already_revoked"

    async def test_revoke_requires_registry_write(self, store) -> None:
        await publish(store, "lib-a")
        with pytest.raises(VastaError):
            await revoke_plugin(store, "lib-a", "1.0.0",
                                principal=auditor(), reason="x")


class TestDeprecate:
    async def test_deprecate_with_successor_latest_migrates(
            self, store) -> None:
        """AC：弃用带后继指引——latest 解析跳过弃用版本。"""
        await publish(store, "lib-a", "1.0.0")
        await publish(store, "lib-a", "2.0.0")
        await deprecate_plugin(store, "lib-a", "1.0.0",
                               principal=publisher(), successor="2.0.0")
        entry = resolve_plugin(store, "lib-a", tenant_id="t",
                               project_id="p")
        assert entry.version == "2.0.0"  # latest 跳过弃用
        assert entry.successor is None  # 弃用标记在 1.0.0 上

    async def test_deprecated_version_grace_pull(self, store) -> None:
        """AC：弃用宽限生效——显式版本仍可拉取（预告迁移）。"""
        await publish(store, "lib-a", "1.0.0")
        await publish(store, "lib-a", "2.0.0")
        await deprecate_plugin(store, "lib-a", "1.0.0",
                               principal=publisher(), successor="2.0.0")
        signed = await pull_plugin(store, "lib-a", version="1.0.0",
                                   key_resolver=key_resolver,
                                   tenant_id="t", project_id="p")
        assert signed.manifest.version == "1.0.0"

    async def test_deprecate_unregistered_successor_rejected(
            self, store) -> None:
        await publish(store, "lib-a", "1.0.0")
        with pytest.raises(VastaError) as e:
            await deprecate_plugin(store, "lib-a", "1.0.0",
                                   principal=publisher(),
                                   successor="9.9.9")
        assert e.value.code == "registry.successor_not_active"

    async def test_deprecate_requires_registry_write(self, store) -> None:
        await publish(store, "lib-a", "1.0.0")
        await publish(store, "lib-a", "2.0.0")
        with pytest.raises(VastaError):
            await deprecate_plugin(store, "lib-a", "1.0.0",
                                   principal=auditor(),
                                   successor="2.0.0")


class TestClosureQuery:
    async def test_closure_direct_and_transitive(self, store) -> None:
        await publish(store, "base")
        await publish(store, "mid", depends_on=["base"])
        await publish(store, "top", depends_on=["mid"])
        await publish(store, "unrelated")
        closure = dependent_closure(store, "base", tenant_id="t",
                                    project_id="p")
        assert closure == ["mid", "top"]
        assert dependent_closure(store, "unrelated", tenant_id="t",
                                 project_id="p") == []
