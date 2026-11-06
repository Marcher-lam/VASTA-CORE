"""插件商业分发子面（Story 12.12，FR-084 收口，蓝图 §31 Stage 6）。

发现 + 评分（12.8）之上的**商业分发机制**（工程内子面；公开市场的
开放条件是 PRD 开放问题 8，Stage 5 评估——本模块交付机制不开放市场）：

- ``publish_listing``：发行方为 active 插件版本挂**定价单**
  （free / paid）——listing 不可变（改价 = 发新版本），与 12.5 注册
  条目同语义；``artifact.listed`` 留痕；
- ``purchase``：租户购买付费 listing → **凭据（entitlement）**落
  ``artifact.purchased``；支付捕获可注入（``PaymentGateway``
  协议——默认 InvoiceGateway 只开票不捕获，如实标注；真实 PSP
  注册即接）；
- ``assert_entitled`` 拉取闸（接线于 ``pull_plugin``）：**有付费
  listing 才闸**——free listing 或无 listing（开源自发分发）完全
  不受影响（后向兼容 12.5/12.6 语义）；付费无凭据 fail-closed。

诚实边界：无真实资金流（发票网关不捕获）；凭据与 listing 同
(tenant, project) 作用域（单市场 MVP——跨租户公开市场属开放问题 8）。
"""

from __future__ import annotations

import secrets
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

from ..governance.rbac import Principal
from .registry import _REGISTRY_RUN, _project_registry, _require_registry_write


class ListingPlan(BaseModel):
    """定价单：free（price 必为 0）或 paid（price 必 >0）。"""

    model_config = ConfigDict(extra="forbid")

    mode: str = Field(pattern="^(free|paid)$")
    price_cents: int = Field(default=0, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)

    @model_validator(mode="after")
    def _mode_price_consistent(self) -> ListingPlan:
        if self.mode == "paid" and self.price_cents <= 0:
            raise ValueError("paid listing 的 price_cents 须 >0")
        if self.mode == "free" and self.price_cents != 0:
            raise ValueError("free listing 的 price_cents 必为 0")
        return self


class Listing(BaseModel):
    """定价单条目（(plugin_id, version) 唯一、不可变）。"""

    model_config = ConfigDict(extra="forbid")

    plugin_id: str
    version: str
    plan: ListingPlan
    publisher: str


class Receipt(BaseModel):
    """支付网关回执（真实 PSP 或发票网关）。"""

    model_config = ConfigDict(extra="forbid")

    order_id: str
    captured: bool  # 真实扣款=False 的回执即「仅开票」
    gateway: str


class PaymentGateway(Protocol):
    """支付网关面：订单 → 回执（真实 PSP 注入即接）。"""

    async def charge(self, order: dict[str, Any]) -> Receipt:
        ...  # pragma: no cover


class InvoiceGateway:
    """默认网关：只开票、不捕获资金（工程内无资金流——如实标注）。"""

    async def charge(self, order: dict[str, Any]) -> Receipt:
        return Receipt(order_id=order["order_id"], captured=False,
                       gateway="invoice(no-capture)")


class Entitlement(BaseModel):
    """购买凭据：(plugin_id, version, buyer) 绑定。"""

    model_config = ConfigDict(extra="forbid")

    plugin_id: str
    version: str
    buyer: str
    order_id: str
    price_cents: int
    currency: str
    captured: bool


async def publish_listing(
    store: Any, plugin_id: str, version: str, plan: ListingPlan, *,
    principal: Principal,
) -> Listing:
    """发行方挂定价单：插件版本须在册且 active（不可给幽灵版本定价）。"""
    _require_registry_write(principal)
    entries, _ = _project_registry(
        store, tenant_id=principal.tenant_id,
        project_id=principal.project_id)
    entry = entries.get((plugin_id, version))
    if entry is None or entry.status != "active":
        raise VastaError(
            code="marketplace.plugin_not_active",
            message=(f"插件 {plugin_id!r}@{version} 不在注册表或非 "
                     "active——定价对象以注册表为准"),
        )
    for prior in store.iter_run_events(
            _REGISTRY_RUN, tenant_id=principal.tenant_id,
            project_id=principal.project_id):
        if prior.type == "artifact.listed" \
                and prior.payload.get("plugin_id") == plugin_id \
                and prior.payload.get("version") == version:
            raise VastaError(
                code="marketplace.duplicate_listing",
                message=(f"listing ({plugin_id!r}, {version!r}) 已存在"
                         "——定价单不可变，改价发新版本"),
            )
    listing = Listing(plugin_id=plugin_id, version=version,
                      plan=plan, publisher=principal.user)
    sequencer = EventSequencer(
        store, _REGISTRY_RUN,
        tenant_id=principal.tenant_id, project_id=principal.project_id)
    await sequencer.emit("artifact.listed", {
        "plugin_id": plugin_id, "version": version,
        "plan": plan.model_dump(), "publisher": principal.user,
    })
    return listing


def get_listing(
    store: Any, plugin_id: str, *, version: str | None = None,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> Listing | None:
    """读定价单投影（无 → None：未定价即自由分发）。"""
    found: Listing | None = None
    for event in store.iter_run_events(
            _REGISTRY_RUN, tenant_id=tenant_id, project_id=project_id):
        if event.type != "artifact.listed" \
                or event.payload.get("plugin_id") != plugin_id:
            continue
        if version is not None \
                and event.payload.get("version") != version:
            continue
        found = Listing(
            plugin_id=plugin_id,
            version=event.payload["version"],
            plan=ListingPlan.model_validate(event.payload["plan"]),
            publisher=event.payload["publisher"])
        if version is not None:
            return found  # 显式版本即精确命中
    return found


async def purchase(
    store: Any, plugin_id: str, *, version: str,
    principal: Principal,
    gateway: PaymentGateway | None = None,
) -> Entitlement:
    """购买付费 listing → 凭据（同版本重购拒——幂等语义）。"""
    _require_registry_write(principal)
    listing = get_listing(store, plugin_id, version=version,
                          tenant_id=principal.tenant_id,
                          project_id=principal.project_id)
    if listing is None:
        raise VastaError(
            code="marketplace.no_listing",
            message=f"插件 {plugin_id!r}@{version} 无定价单——无需购买",
        )
    if listing.plan.mode != "paid":
        raise VastaError(
            code="marketplace.free_listing",
            message=f"listing ({plugin_id!r}, {version!r}) 是 free——无需购买",
        )
    for prior in store.iter_run_events(
            _REGISTRY_RUN, tenant_id=principal.tenant_id,
            project_id=principal.project_id):
        if prior.type == "artifact.purchased" \
                and prior.payload.get("plugin_id") == plugin_id \
                and prior.payload.get("version") == version \
                and prior.payload.get("buyer") == principal.user:
            raise VastaError(
                code="marketplace.duplicate_purchase",
                message=(f"{principal.user!r} 已持有 ({plugin_id!r}, "
                         f"{version!r}) 凭据——同版本不重购"),
            )
    order = {
        "order_id": f"ord-{secrets.token_hex(8)}",
        "plugin_id": plugin_id, "version": version,
        "buyer": principal.user,
        "price_cents": listing.plan.price_cents,
        "currency": listing.plan.currency,
    }
    receipt = await (gateway or InvoiceGateway()).charge(order)
    entitlement = Entitlement(
        plugin_id=plugin_id, version=version, buyer=principal.user,
        order_id=receipt.order_id, price_cents=listing.plan.price_cents,
        currency=listing.plan.currency, captured=receipt.captured)
    sequencer = EventSequencer(
        store, _REGISTRY_RUN,
        tenant_id=principal.tenant_id, project_id=principal.project_id)
    await sequencer.emit("artifact.purchased", {
        **order, "captured": receipt.captured, "gateway": receipt.gateway,
    })
    return entitlement


def assert_entitled(
    store: Any, plugin_id: str, *, version: str,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> Listing | None:
    """拉取闸（pull_plugin 接线）：有付费 listing 才闸，凭据缺失拒。

    - 无 listing / free listing → 放行（返回 None 或 listing——开源
      自发分发完全不受影响）；
    - paid listing 且 (plugin, version) 有购买事件 → 放行；
    - paid listing 无凭据 → fail-closed（marketplace.entitlement_missing）。
    """
    listing = get_listing(store, plugin_id, version=version,
                          tenant_id=tenant_id, project_id=project_id)
    if listing is None or listing.plan.mode != "paid":
        return listing  # 自由分发不闸
    for event in store.iter_run_events(
            _REGISTRY_RUN, tenant_id=tenant_id, project_id=project_id):
        if event.type == "artifact.purchased" \
                and event.payload.get("plugin_id") == plugin_id \
                and event.payload.get("version") == version:
            return listing  # 凭据在册
    raise VastaError(
        code="marketplace.entitlement_missing",
        message=(f"付费插件 {plugin_id!r}@{version}（"
                 f"{listing.plan.price_cents} {listing.plan.currency}）"
                 "无购买凭据——先 purchase（fail-closed）"),
    )


def entitlements(
    store: Any, *, buyer: str | None = None,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> list[Entitlement]:
    """凭据投影（运维/对账面）。"""
    out: list[Entitlement] = []
    for event in store.iter_run_events(
            _REGISTRY_RUN, tenant_id=tenant_id, project_id=project_id):
        if event.type != "artifact.purchased":
            continue
        if buyer is not None and event.payload.get("buyer") != buyer:
            continue
        out.append(Entitlement(
            plugin_id=event.payload["plugin_id"],
            version=event.payload["version"],
            buyer=event.payload["buyer"],
            order_id=event.payload["order_id"],
            price_cents=event.payload["price_cents"],
            currency=event.payload["currency"],
            captured=event.payload.get("captured", False)))
    return out


__all__ = [
    "Entitlement",
    "InvoiceGateway",
    "Listing",
    "ListingPlan",
    "PaymentGateway",
    "Receipt",
    "assert_entitled",
    "entitlements",
    "get_listing",
    "publish_listing",
    "purchase",
]
