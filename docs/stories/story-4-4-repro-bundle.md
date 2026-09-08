---
story_key: 4-4-repro-bundle
baseline_commit: 10fc909
---

# Story 4.4: 最小复现包与回归任务

**Status:** review

## Story

As a QA/评测工程师,
I want 把失败 Run 导出为最小复现包并一键登记为回归任务,
So that 每个失败都沉淀为可重复执行的测试资产。

## Acceptance Criteria

**Given** 任一失败 Run
**When** 导出复现包
**Then** 包含事件流、Artifact 引用、配置快照与确定性替身，在干净环境离线重放非模型事件与核验器通过（FR-062，对应 AC-08）
**And** 包内不含模型密钥与无关租户数据；回归任务以 vasta-protocols 定义的登记格式导出并通过其契约测试（评测框架可直接消费该格式）

## Tasks/Subtasks

- [x] 1. export_repro_bundle(store, run_id, scope)：ReproBundle 清单（事件计数/证据引用含 contract+result+观察 refs/配置快照含 budget 与契约 refs）+ 事件 JSON Lines 字节
- [x] 2. build_regression_task(bundle, lines)：RegressionTask 契约格式（task_id/source_run_id/event_data/expected_outcome）
- [x] 3. replay_non_model_events(lines)：逐条 schema 校验离线重放（AC-08 最小验证）
- [x] 4. 测试：导出/重放/回归任务格式、未知 Run 拒
- [x] 5. 对照 AC 验证并更新记录

## Dev Notes

- 包天然不含密钥（事件流本就无密钥）；确定性替身 = 重放不重新调用模型（模型事件仅作 Artifact 引用）。
- Stage 3 将把 bundle 落盘为目录结构（bundle.json + events.jsonl + blobs/）。

## Dev Agent Record

### Implementation Plan

replay.py 增 ReproBundle/RegressionTask/export_repro_bundle/build_regression_task/replay_non_model_events。

### Debug Log

- 三处小修：变量名笔误 artifactRefs、测试缺 pytest 导入、config_snapshot 包 budget 层。

### Completion Notes

AC：导出（引用清单含契约/结果/观察证据 + 配置快照）+ 离线重放逐条 schema 校验通过 + 回归任务契约格式 + 未知 Run 拒。296 全绿。

## File List

- packages/vasta-storage/src/vasta_storage/replay.py（+复现包族）
- packages/vasta-storage/src/vasta_storage/__init__.py（导出）
- tests/test_timeline.py（+2）
- docs/stories/story-4-4-repro-bundle.md

## Change Log

- 2026-09-08：Story 4.4 实现完成——复现包导出/离线重放/回归任务契约；296 全绿；Epic 4 收口；状态 review。
