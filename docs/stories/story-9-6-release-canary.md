---
story_key: 9-6-release-canary
baseline_commit: 7c408b4
---

# Story 9.6: 资产发布灰度与回滚（G3）

**Status:** review

## Story

As a 资产负责人,
I want 模型/策略/工具/提示资产发布经测试→影子→灰度→提升→回滚,
So that 坏版本影响面可控、可退。

## Acceptance Criteria

**Given** 8.8 版本化 registry
**When** 发布新资产版本
**Then** 状态机 candidate→testing→shadow→canary→active（+rolled_back）；各状态转换落事件；回滚恢复引用至前 active 版本
**And** 影子期新旧版本并行对比产出差异报告；灰度比例可配（FR-065）

## Tasks/Subtasks

- [x] T1: `ReleaseStatus`（candidate/testing/shadow/canary/active/
  rolled_back）+ `promote_release(store, kind, name, version, to)` ——
  线性推进（跳级拒 `release.invalid_transition`），各转换落
  `release.transition` 事件（registry 系统流）
- [x] T2: `rollback_release(store, kind, name)` → active 历史重放找前一
  active，恢复 + 落 `release.rolled_back` 事件；无 active/无前一 active
  均明确拒
- [x] T3: `compare_shadow(store, kind, name, new_v, old_v)` → bundle
  逐字段差异报告（field/old/new）；`set_canary_percent` 1-100 可配
  （越界拒）+ `get_canary_percent`（默认 100）
- [x] T4: 测试 `tests/test_release_canary.py` 9 条（全路径推进/跳级拒/
  转换事件/未发布拒/回滚恢复前一 active/回滚事件/无 active 拒/影子对比/
  灰度比例+越界）；全量 557 passed +2 skipped；ruff 全绿；
  import-linter 2 契约 KEPT

## Dev Notes

- 位置：`packages/vastacore-sdk/src/vastacore/release.py`（组装根）。
- 底座：8.8 versioning registry（同一 "registry" 系统流——release.* 事件族）。
- 状态转换是**资产级**（kind+name），版本是发布物——同一资产可多版本
  并存，但只有一个 active。

## Dev Agent Record

### Debug Log

- `get_release_status` 首版 `await _get_state_sync(...)` 但函数本体是
  同步——coroutine 对象上 .get() 炸。修正为直接调用（同步迭代器形态，
  与 Sequencer 的系统流全量同步策略一致）。
- `_emit` 死代码（fire-and-forget create_task）在重构中遗留——删。

### Completion Notes

- 发布状态机线性推进（跳级拒 candidate→active 不可）——release.transition
  事件全量留痕（from/to），状态重建走事件重放（与 AD-2 投影语义一致）。
- 回滚：active 历史重放找前一 active（回滚后再发布再回滚的正确链）；
  rolled_back 事件含 from/to 版本号；首次 active 无回滚目标明确拒。
- 影子对比：bundle 逐字段 diff 报告（field/old/new 截断100字符）；
  灰度比例存于事件流（release.canary_config），查询走重放（默认 100）。
- G3 审批与发布 2/3（9.7 契约预留段激活待续）。

### File List

- packages/vastacore-sdk/src/vastacore/release.py（新增：ReleaseStatus/
  promote_release/rollback_release/compare_shadow/set_canary_percent/
  get_canary_percent/get_release_status）
- packages/vastacore-sdk/src/vastacore/__init__.py（导出）
- tests/test_release_canary.py（新增：9 条）
- docs/sprint-status.yaml（9-6 状态）

## Change Log

- 2026-09-10: Story 9.6 实现完成（T1–T4 全过，557 passed +2 skipped，ruff/lint 绿）→ review
