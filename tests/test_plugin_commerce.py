"""Story 12.12：插件商业分发子面（FR-084 收口）。

定价单（不可变）→ 购买凭据（可注入支付网关）→ 拉取闸接线
（pull_plugin：有付费 listing 才闸，自由分发不受影响）。
"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.ecosystem.commerce import (
    InvoiceGateway,
    ListingPlan,
    assert_entitled,
    entitlements,
    get_listing,
    publish_listing,
    purchase,
)
from vastacore.ecosystem.manifest import PluginManifest, sign_manifest
from vastacore.ecosystem.registry import pull_plugin, register_plugin
from vastacore.governance.rbac import Principal, Role


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


KEY = b"registry-signing-key"


def key_resolver(key_id: str) -> bytes:
    return KEY


def principal(user: str = "op-1") -> Principal:
    return Principal(user=user, role=Role.OPERATOR,
                     tenant_id="t", project_id="p")


def auditor() -> Principal:
    return Principal(user="aud-1", role=Role.AUDITOR,
                     tenant_id="t", project_id="p")


def manifest(version: str = "1.0.0") -> PluginManifest:
    return PluginManifest(
        plugin_id="csv-importer", version=version, name="CSV Importer",
        permissions=["query"], data={}, network={"egress": []},
        resources={"max_actions": 10},
        compatibility={"platform": ">=0.1.0"})


async def publish(store, version: str = "1.0.0") -> None:
    await register_plugin(
        store, sign_manifest(manifest(version), key_id="k-1", key=KEY),
        principal=principal("publisher-1"), key_resolver=key_resolver)


class TestListing:
    async def test_publish_and_read_listing(self, store) -> None:
        await publish(store)
        listing = await publish_listing(
            store, "csv-importer", "1.0.0",
            ListingPlan(mode="paid", price_cents=1900),
            principal=principal("publisher-1"))
        assert listing.plan.price_cents == 1900
        assert get_listing(store, "csv-importer", version="1.0.0",
                           tenant_id="t", project_id="p") == listing
        types = [e.type for e in store.iter_run_events("registry")]
        assert types.count("artifact.listed") == 1

    async def test_listing_immutable_no_duplicate(self, store) -> None:
        await publish(store)
        await publish_listing(store, "csv-importer", "1.0.0",
                              ListingPlan(mode="free"),
                              principal=principal("publisher-1"))
        with pytest.raises(VastaError) as excinfo:
            await publish_listing(
                store, "csv-importer", "1.0.0",
                ListingPlan(mode="paid", price_cents=100),
                principal=principal("publisher-1"))
        assert excinfo.value.code == "marketplace.duplicate_listing"

    async def test_listing_requires_active_plugin(self, store) -> None:
        with pytest.raises(VastaError) as excinfo:
            await publish_listing(
                store, "ghost", "1.0.0", ListingPlan(mode="free"),
                principal=principal("publisher-1"))
        assert excinfo.value.code == "marketplace.plugin_not_active"

    async def test_plan_mode_price_consistency(self) -> None:
        with pytest.raises(ValueError):
            ListingPlan(mode="paid", price_cents=0)
        with pytest.raises(ValueError):
            ListingPlan(mode="free", price_cents=1)

    async def test_listing_requires_registry_write(self, store) -> None:
        await publish(store)
        with pytest.raises(VastaError):
            await publish_listing(store, "csv-importer", "1.0.0",
                                  ListingPlan(mode="free"),
                                  principal=auditor())


class TestPurchase:
    async def test_purchase_paid_listing_creates_entitlement(self, store
                                                             ) -> None:
        await publish(store)
        await publish_listing(store, "csv-importer", "1.0.0",
                              ListingPlan(mode="paid", price_cents=1900),
                              principal=principal("publisher-1"))
        ent = await purchase(store, "csv-importer", version="1.0.0",
                             principal=principal("buyer-1"))
        assert ent.price_cents == 1900
        assert ent.captured is False  # 默认发票网关：开票不捕获
        assert ent.order_id.startswith("ord-")
        # 闸放行 + 凭据投影（同 t/p 作用域读）
        assert assert_entitled(store, "csv-importer", version="1.0.0",
                               tenant_id="t", project_id="p")
        mine = entitlements(store, buyer="buyer-1",
                            tenant_id="t", project_id="p")
        assert len(mine) == 1 and mine[0].plugin_id == "csv-importer"

    async def test_injected_gateway_capture_flag(self, store) -> None:
        class CapturingGateway:
            async def charge(self, order):
                from vastacore.ecosystem.commerce import Receipt

                return Receipt(order_id=order["order_id"], captured=True,
                               gateway="fake-psp")

        await publish(store)
        await publish_listing(store, "csv-importer", "1.0.0",
                              ListingPlan(mode="paid", price_cents=500),
                              principal=principal("publisher-1"))
        ent = await purchase(store, "csv-importer", version="1.0.0",
                             principal=principal("buyer-1"),
                             gateway=CapturingGateway())
        assert ent.captured is True
        all_ents = entitlements(store, tenant_id="t", project_id="p")
        assert ent.order_id in {e.order_id for e in all_ents}

    async def test_duplicate_purchase_rejected(self, store) -> None:
        await publish(store)
        await publish_listing(store, "csv-importer", "1.0.0",
                              ListingPlan(mode="paid", price_cents=100),
                              principal=principal("publisher-1"))
        buyer = principal("buyer-1")
        await purchase(store, "csv-importer", version="1.0.0", principal=buyer)
        with pytest.raises(VastaError) as excinfo:
            await purchase(store, "csv-importer", version="1.0.0",
                           principal=buyer)
        assert excinfo.value.code == "marketplace.duplicate_purchase"

    async def test_purchase_free_or_unlisted_rejected(self, store) -> None:
        await publish(store)
        with pytest.raises(VastaError) as e1:
            await purchase(store, "csv-importer", version="1.0.0",
                           principal=principal("buyer-1"))
        assert e1.value.code == "marketplace.no_listing"
        await publish_listing(store, "csv-importer", "1.0.0",
                              ListingPlan(mode="free"),
                              principal=principal("publisher-1"))
        with pytest.raises(VastaError) as e2:
            await purchase(store, "csv-importer", version="1.0.0",
                           principal=principal("buyer-1"))
        assert e2.value.code == "marketplace.free_listing"


class TestPullGate:
    async def test_paid_without_entitlement_blocks_pull(self, store) -> None:
        """AC：付费插件无凭据 → pull_plugin fail-closed。"""
        await publish(store)
        await publish_listing(store, "csv-importer", "1.0.0",
                              ListingPlan(mode="paid", price_cents=1900),
                              principal=principal("publisher-1"))
        with pytest.raises(VastaError) as excinfo:
            await pull_plugin(store, "csv-importer", key_resolver=key_resolver,
                              tenant_id="t", project_id="p")
        assert excinfo.value.code == "marketplace.entitlement_missing"
        # 未付费期间不产生任何拉取产物——注册表条目仍在（可再购）

    async def test_purchase_unblocks_pull(self, store) -> None:
        await publish(store)
        await publish_listing(store, "csv-importer", "1.0.0",
                              ListingPlan(mode="paid", price_cents=1900),
                              principal=principal("publisher-1"))
        await purchase(store, "csv-importer", version="1.0.0",
                       principal=principal("buyer-1"))
        signed = await pull_plugin(store, "csv-importer",
                                   key_resolver=key_resolver,
                                   tenant_id="t", project_id="p")
        assert signed.manifest.plugin_id == "csv-importer"

    async def test_free_and_unlisted_pull_unchanged(self, store) -> None:
        """后向兼容：无 listing 与 free listing 的拉取与 12.5 语义一致。"""
        await publish(store)
        # 无 listing
        signed = await pull_plugin(store, "csv-importer",
                                   key_resolver=key_resolver,
                                   tenant_id="t", project_id="p")
        assert signed.manifest.version == "1.0.0"
        # free listing
        await publish_listing(store, "csv-importer", "1.0.0",
                              ListingPlan(mode="free"),
                              principal=principal("publisher-1"))
        signed2 = await pull_plugin(store, "csv-importer",
                                    key_resolver=key_resolver,
                                    tenant_id="t", project_id="p")
        assert signed2.manifest.plugin_id == "csv-importer"

    async def test_entitlement_version_scoped(self, store) -> None:
        """凭据绑定版本：买了 1.0.0，1.1.0 的付费 listing 仍被闸。"""
        await publish(store, "1.0.0")
        await publish(store, "1.1.0")
        pub = principal("publisher-1")
        await publish_listing(store, "csv-importer", "1.0.0",
                              ListingPlan(mode="paid", price_cents=900),
                              principal=pub)
        await publish_listing(store, "csv-importer", "1.1.0",
                              ListingPlan(mode="paid", price_cents=1900),
                              principal=pub)
        await purchase(store, "csv-importer", version="1.0.0",
                       principal=principal("buyer-1"))
        assert await pull_plugin(store, "csv-importer", version="1.0.0",
                                 key_resolver=key_resolver,
                                 tenant_id="t", project_id="p")
        with pytest.raises(VastaError) as excinfo:
            await pull_plugin(store, "csv-importer", version="1.1.0",
                              key_resolver=key_resolver,
                              tenant_id="t", project_id="p")
        assert excinfo.value.code == "marketplace.entitlement_missing"


class TestInvoiceGatewayLabel:
    async def test_default_gateway_is_labeled_no_capture(self) -> None:
        receipt = await InvoiceGateway().charge({"order_id": "ord-x"})
        assert receipt.captured is False
        assert receipt.gateway == "invoice(no-capture)"
