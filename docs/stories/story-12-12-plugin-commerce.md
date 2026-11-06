---
story_key: 12-12-plugin-commerce
baseline_commit: 9411a09
---

# Story 12.12: 插件商业分发子面（G3，FR-084 收口）

**Status:** done

## Story

As a 插件发行方,
I want 定价单、购买凭据与拉取闸,
So that 付费插件按凭据分发、自由分发不受影响。

## Acceptance Criteria

**Given** active 插件版本（12.5 注册表）与 `publish_listing` 定价单
（free/paid，不可变——改价发新版本）
**When** 租户 `purchase`（支付网关可注入——默认发票网关不捕获，
如实标注）产生凭据
**Then** `pull_plugin` 商业闸：有付费 listing 才闸，凭据缺失
fail-closed（marketplace.entitlement_missing）；free/无 listing 拉取
与 12.5 语义一致
**And** listing/purchase 留痕（artifact.listed / artifact.purchased）；
同版本重购拒（幂等）；公开市场开放条件仍属 PRD 开放问题 8

## Tasks/Subtasks

- [x] T1: `evidence→ecosystem/commerce.py`——`ListingPlan`（free 价必 0 /
      paid 价必 >0，model_validator）；`publish_listing`（对象须在册且
      active、(plugin, version) 不可重定价）；`get_listing` 投影
- [x] T2: `purchase`——`PaymentGateway` Protocol + 默认 `InvoiceGateway`
      （开票不捕获，gateway 标注 invoice(no-capture)；真实 PSP 注入
      即接）；凭据 (plugin, version, buyer) 绑定；同版本重购拒
- [x] T3: `assert_entitled` 拉取闸——**有付费 listing 才闸**（free/
      无 listing 放行，12.5/12.6 后向兼容）；接线 `pull_plugin`
      （惰性导入防环——commerce 模块级引 registry 投影）
- [x] T4: 事件命名走生态域 `artifact` 族先例（registered/rated 同族）
      ——`artifact.listed` / `artifact.purchased`；事件目录快照回写
      （17→19 型，catalog 守卫零漂移）
- [x] T5: `entitlements` 对账投影（buyer 过滤）
- [x] T6: 测试 `tests/test_plugin_commerce.py` 14 条——定价读回/
      不可变/幽灵拒/RBAC 拒/价格一致性；购买凭据/注入网关 captured/
      重购拒/free 与无单拒；闸三态（付费拒/购买后放行/free 与无单
      不变）+ 凭据版本绑定（1.0.0 购买不撬 1.1.0 闸）；发票网关标注。
      全量 1287 passed + 5 skipped；ruff 全绿；import-linter 5 契约 KEPT

## Dev Notes

- 位置：`packages/vastacore-sdk/src/vastacore/ecosystem/commerce.py`
  （ecosystem 子包，复用 governance.rbac Principal 与 registry 投影）。
- 诚实边界三条入 docstring：无真实资金流（发票网关不捕获）；凭据与
  listing 同 (tenant, project) 作用域（单市场 MVP）；跨租户公开市场
  属 PRD 开放问题 8（Stage 5 评估）——本 Story 交付机制不开放市场。
- 事件族：不新增第 14 族——生态域复用 `artifact` 族（12.5/12.8 的
  registered/rated 先例），协议闭集与守卫零改动（目录 +2 型回写）。

## Dev Agent Record

### Debug Log

- 首版事件名 marketplace.* 撞 13 族闭集（EventEnvelope 校验拒）——
  改 artifact.listed/purchased 对齐生态域先例，目录重生成回写。
- 测试两处作用域疏漏（默认 t-default 读不到 t/p 作用域事件、旧事件
  名断言）——flake 遥测如实记录后逐条修复。

### Completion Notes

- FR-084 由「发现+评分已交、商业分发缺」收口为全量：定价-购买-凭据-
  拉取闸闭环；终检 §一 表 FR-084 partial 行闭环。

### Change Log
