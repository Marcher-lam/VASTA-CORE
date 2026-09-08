---
story_key: 4-2-first-deviation
baseline_commit: 5cd7ee8
---

# Story 4.2: 首个偏差定位

**Status:** review

## Story

As a Agent 开发者（陈默，UJ-1）,
I want 一键跳到 Run 的首个偏差并同屏看到该动作前后证据,
So that 排障从小时级翻日志变成分钟级看证据。

## Acceptance Criteria

**Given** 含注入偏差（核验 deviation/预期不符/外部变化）的 Run
**When** 执行首偏差定位
**Then** 定位到时间上第一个偏差事件，展示其前后原始观察、当时生效的契约与计划
**And** 外部变化类偏差被单独分类提示（区分"改 Agent"与"环境变了"两类响应）

## Tasks/Subtasks

- [x] 1. first_deviation(events)：偏差信号集（verification.deviated/errored、policy_denied、action.failed、approval_requested、incident.opened、run.failed、外部变化）
- [x] 2. DeviationHit：seq/type/category（external_change|verification|policy|execution|supervisor）/summary/前后观察 seq/最近契约 ref/上下文窗口
- [x] 3. 测试：偏差运行定位 verification、干净运行定位 external_change、分类区分、契约跳转引用
- [x] 4. 对照 AC 验证并更新记录

## Dev Notes

- 定位为纯函数；CLI `vasta inspect`（Story 4.3 一并接）。
- env 路径默认核验偏差语义：测试用恒过核验器构造干净流。

## Dev Agent Record

### Implementation Plan

replay.py 增 first_deviation + DeviationHit + _category_of + _nearest_contract_ref；偏差信号七类事件 + 外部变化（payload.external_source）。

### Debug Log

- 干净流测试初版失败——env 路径默认 ReadBack 对空观察细节必偏差（已知语义）；seeded_run 改用恒过核验器构造干净流，偏差版显式注入 DeviationVerifier。

### Completion Notes

AC：定位首偏差（verification.deviated）+ 前后观察 seq + 最近契约 ref（可跳转）+ 上下文窗口；外部变化单列分类（webhook 注入定位 external_change）；干净流与偏差流分类分叉验证。292 全绿。

## File List

- packages/vasta-storage/src/vasta_storage/replay.py（first_deviation/DeviationHit）
- packages/vasta-storage/src/vasta_storage/__init__.py（导出）
- tests/test_timeline.py（+3 测试）
- docs/stories/story-4-2-first-deviation.md

## Change Log

- 2026-09-08：Story 4.2 实现完成——首偏差定位（七类信号+外部变化分类+契约跳转+上下文窗口）；292 全绿；状态 review。
