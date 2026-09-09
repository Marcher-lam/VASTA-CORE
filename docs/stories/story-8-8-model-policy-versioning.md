---
story_key: 8-8-model-policy-versioning
baseline_commit: 07d0f76
---

# Story 8.8: 模型与策略版本化（G4）

**Status:** review

## Story

As a 平台使用者,
I want 模型资产带版本链、策略配置有快照,
So that 「回到当时那一刻」覆盖全部四类对象。

## Acceptance Criteria

**Given** 模型 manifest 变更或策略配置变更
**When** 发布新版本
**Then** 旧版本可完整取回（模型资产入 CAS+版本引用链；策略配置快照入事件流）
**And** 历史 Run 的事件引用当时的版本（回放不串版）（FR-061）

## Tasks/Subtasks

- [x] T1: `publish_model_version(store, name, version, *, ruleset | code,
      manifest)`——模型资产打包 JSON 入 CAS + `world_model.published` 事件
      （run="registry"，事件流即版本链——AD-2 投影可重建）；同版本同内容幂等
      （CAS 同址）、同版本异内容拒绝（registry.conflict——版本号不可复用）
- [x] T2: `publish_policy_snapshot(store, name, version, config)`——策略配置
      JSON 入 CAS + `artifact.published` 事件（kind=policy_config）；同冲突
      语义；不可序列化配置构造期拒
- [x] T3: `version_as_of(store, kind, name, *, as_of_seq | as_of_ts | latest)`
      ——重放 registry 事件取当时版本记录 + CAS 取回完整 bundle：
      `rebuild_dsl()` / `rebuild_python()` 重建可执行模型（语义实测 v1 col+1 /
      v2 col+2 不串版）；策略 `config` dict 原样往返；不存在明确报错
- [x] T4: 回放不串版守卫——v1 发布记时点 → v2 发布 → as-of 当时 = v1 bundle
      （CAS 不可变锚定）；读路径零副作用（事件数/工件数不变）
- [x] T5: 测试 `tests/test_versioning.py` 11 条（发布/幂等/冲突/as-of 三点/
      DSL·Python 重建/策略往返/未知与早于首发报错/零副作用/封闭事件族）；
      全量 465 passed +1 skipped；ruff 全绿；import-linter 2 契约 KEPT

## Dev Notes

- 位置：`packages/vastacore-sdk/src/vastacore/versioning.py`（组装根）。
- 事件族约束：模型资产发布属 world_model.*（模型即世界模型资产）；策略配置
  快照是 artifact 注册 → artifact.published。registry 为系统 run（同
  "cognition" 先例）；seq 分配每次发射前全量同步（与桥接一致）。
- DSL bundle 可重建：ruleset JSON + manifest dict 直接构造 DSLWorldModel。

## Dev Agent Record

### Debug Log

- 边界语义确认：as_of 含该时点事件（与 claim_as_of 的 seq 语义一致）——
  「早于首发」用 ts - 1µs 测试而非 seq=0（seq 0 含首发本身）。

### Completion Notes

- 版本链 = registry 事件流（world_model.published / artifact.published），
  bundle = 规范化 JSON 入 CAS（kind+name+version+bundle 参与 canonical
  哈希——同内容同址幂等，内容异则哈希异 → conflict 拒绝版本号复用）。
- 四类回溯对象就此齐备：派生物（血缘/CAS）+ 记忆（claim_as_of 重放）+
  模型/策略（本 Story）——FR-061「回到当时那一刻」全覆盖。
- 重建可执行：DSL ruleset 与受限 Python code 双形态实测取回即用（v1/v2
  语义区分验证不串版）；策略 config dict 逐键往返相等。
- 读路径零副作用锚定；事件族守住封闭集（不发明 registry.*/model.*）。

### File List

- packages/vastacore-sdk/src/vastacore/versioning.py（新增：publish_model_
  version/publish_policy_snapshot/version_as_of/VersionRecord/PublishedRef）
- packages/vastacore-sdk/src/vastacore/__init__.py（导出）
- tests/test_versioning.py（新增：11 条）
- docs/sprint-status.yaml（8-8 状态）

## Change Log

- 2026-09-09: Story 8.8 实现完成（T1–T5 全过，465 passed +1 skipped，ruff/lint 绿）→ review
