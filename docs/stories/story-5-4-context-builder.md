---
story_key: 5-4-context-builder
baseline_commit: aad7789
---

# Story 5.4: Context Builder 预算内装配

**Status:** review

## Story

As a Agent 开发者,
I want Context Builder 按目标、相关性、风险与预算装配上下文且选择依据可追溯,
So that 模型每次调用拿到的是可解释、不超预算的上下文。

## Acceptance Criteria

**Given** 目标、记忆库与 token/条目预算
**When** 装配上下文
**Then** 输出含每项入选依据（相关性/风险/来源），超预算按优先级裁剪并留裁剪记录（FR-025）
**And** 不发生静默截断（被裁剪项显式列出）

## Tasks/Subtasks

- [x] 1. ContextBuilder.assemble（类型优先级+相关性+置信度排序；预算截断；pruned 显式）
- [x] 2. 测试：优先级序、预算裁剪可追溯、被推翻不入、policy 可读
- [x] 3. 对照 AC 验证

## Dev Notes

- token 级预算在模型接入（Stage 2）后细化；MVP 条目预算。

## Dev Agent Record

见 story-5-1（同批交付）。优先级排序符号错误由测试抓住修正。

## File List

- cognition.py ContextBuilder；tests/test_cognition.py TestContextBuilder

## Change Log

- 2026-09-08：Story 5.4 实现完成——Epic 5 收口；状态 review。
