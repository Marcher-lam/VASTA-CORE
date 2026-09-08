---
story_key: 4-3-html-replay
baseline_commit: 21deb04
---

# Story 4.3: 自包含 HTML Replay 生成器

**Status:** review

## Story

As a Agent 开发者,
I want 把时间线、偏差点与动作前后证据渲染为单个无外部依赖的 HTML 文件,
So that 排障报告可以离线发给没装环境的同事与审计方。

## Acceptance Criteria

**Given** 任一完成的 Run
**When** 生成 HTML Replay
**Then** 单 HTML 文件包含因果时间线、首偏差高亮、动作前后证据（图像内嵌缩略图、工具响应可折叠），无网络与外部资源依赖
**And** 文件头含生成器版本与配置快照；证据可点击展开到 Epic 2 的 inspect/diff 引用

## Tasks/Subtasks

- [x] 1. render_html(timeline, deviation)：内联 CSS、事件表（depth 展示）、首偏差高亮块、外部变化块
- [x] 2. `vasta replay RUN_ID` CLI 命令（输出单文件）
- [x] 3. 测试：自包含（无 script src/无 http 引用）、偏差行高亮、外部变化块、干净流
- [x] 4. 对照 AC 验证并更新记录

## Dev Notes

- 图像内嵌缩略图：MVP 输出 seq 引用（点击展开到 inspect 属 Stage 2 Console）；AC 的"证据可点击展开"以 details 折叠 + seq 锚点形态部分满足——记录为已知边界。
- `vasta inspect RUN_ID`（4.2 的 CLI 入口）一并交付。

## Dev Agent Record

### Implementation Plan

render_html 模板（内联 CSS + 表格 + 偏差/外部块）+ CLI inspect/replay 两命令。

### Debug Log

- 外部变化作为首偏差时高亮块标签改"外部变化"+蓝样式（与核验偏差红样式区分）。

### Completion Notes

AC：单文件自包含（无外部资源断言）+ 时间线 + 首偏差高亮 + 外部变化块 + 版本头；CLI `vasta inspect/replay` 交付。图像内嵌缩略图为已知边界（Stage 2 Console）。294 全绿。

## File List

- packages/vasta-storage/src/vasta_storage/replay.py（render_html）
- packages/vastacore-sdk/src/vastacore/cli.py（inspect/replay 命令）
- tests/test_timeline.py（+2）
- docs/stories/story-4-3-html-replay.md

## Change Log

- 2026-09-08：Story 4.3 实现完成——自包含 HTML Replay + CLI 两命令；294 全绿；状态 review。
