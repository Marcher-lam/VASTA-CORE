---
story_key: 4-1-timeline-projection
baseline_commit: 85f32fbc1e65947aa35ab59ff8e5db5767650dd1
---

# Story 4.1: 因果时间线投影

**Status:** review

## Story

As a Agent 开发者,
I want 从事件流投影出按因果（而非纯时间）组织的完整时间线（CLI 表格 + JSON 输出）,
So that 理解一次 Run 的真实决策路径。

## Acceptance Criteria

**Given** 任一完成的 Run
**When** 生成时间线投影
**Then** 覆盖该 Run 全部事件类型且每个事件的因果父项可向上追溯（FR-060，对应 AC-01 完整回放）
**And** 投影可从事件历史随时删除重建（AD-11）

## Tasks/Subtasks

- [x] 1. `vasta-storage/replay.py`：timeline(events) 纯函数——因果树展开（根=无父事件；depth 按因果链深度）；family 着色分组；JSON 可序列化 TimelineEntry{seq,type,family,depth,parent_seq,ts,payload 摘要}
- [x] 2. 文本表格渲染（CLI 用）：depth 缩进 + 类型 + 摘要一行
- [x] 3. 外部变化类偏差单列标记（observation.external source≠tool）
- [x] 4. 测试：全事件覆盖、因果父链逐条可溯、depth 正确（链深=事件深度）、投影纯函数（同输入同输出）、重建幂等
- [x] 5. 对照 AC 验证并更新记录

## Dev Notes

- 投影是纯函数（无存储状态）——满足 AD-11"可删除重建"。
- payload 摘要截断防巨型输出（事件全量仍在库）。

## Dev Agent Record

### Implementation Plan

`vasta-storage/replay.py`：timeline 纯函数（因果 depth 递归+缓存、family 分组、payload 摘要截断、外部变化标记）+ Timeline/TimelineEntry 模型 + render_text 表格。

### Debug Log

（完成后填写）

### Completion Notes

AC：全覆盖（covers_all_events 真）+ 因果父链逐条可溯（每条 parent 深度=depth-1）+ 纯函数同输入同输出（AD-11 重建幂等实测）+ 外部变化单列标记 + 文本表格渲染。回归 289 全绿。

## File List

- packages/vasta-storage/src/vasta_storage/replay.py（新建）
- packages/vasta-storage/src/vasta_storage/__init__.py（导出）
- packages/vasta-runtime/src/vasta_runtime/runner.py（external_source 入 payload）
- tests/test_timeline.py（4 测试）
- docs/stories/story-4-1-timeline-projection.md

## Change Log

- 2026-09-08：Story 4.1 实现完成——因果时间线投影（纯函数）+ 文本渲染 + 外部变化标记；289 全绿；状态 review。
