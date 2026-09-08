---
story_key: 5-1-claim-lifecycle
baseline_commit: aad7789
---

# Story 5.1: 四类记忆与 Claim 全生命周期

**Status:** review

## Story

As a Agent 开发者,
I want Working/Hypothesis/Guide/Counterexample 四类记忆以 Claim（范围/证据/反例/依赖/置信度/版本/状态）建模,
So that Agent 的每条理解都可治理。

## Acceptance Criteria

**Given** Run 中产生的候选认知
**When** 创建与演进 Claim
**Then** 全生命周期状态（proposed/supported/accepted/disputed/refuted/retired）转移均落 `claim.*` 事件（FR-020/021/022）
**And** 缺证据链路的 Claim 无法进入 accepted；被推翻的 Claim 不删除、保留影响链；Policy 类记忆对 Agent 只读

## Tasks/Subtasks

- [x] 1. Claim 模型（九类 memory_type 枚举 + MVP 四类常量）+ CognitionService（事件投影，AD-2 重建验证）
- [x] 2. 生命周期 API：propose/support/accept/dispute/refute/retire；accept 无证据拒
- [x] 3. 测试：生命周期转移、无证据拒、推翻不删除、投影重建
- [x] 4. 对照 AC 验证

## Dev Notes

- 与 5.2/5.3/5.4 同文件交付（cognition.py 单模块四服务）。
- Policy 只读由 memory_type 语义保证（写入路径属控制面，Stage 3）。

## Dev Agent Record

### Implementation Plan

cognition.py：Claim + CognitionService（事件层 _emit/_apply/_rebuild + 公开 API）+ ConflictService + ContextBuilder。

### Debug Log

- depends_on 初版不入 propose 载荷（失效传播级联失灵）→ 补入；ContextBuilder 优先级排序符号反（working 排前）→ 修正。

### Completion Notes

AC：六态全转移落事件、无证据 accept 拒（claim.no_evidence）、推翻不删除（状态+反例保留）、投影重建（新实例恢复 accepted）。308 全绿。

## File List

- packages/vasta-cognition/src/vasta_cognition/cognition.py
- packages/vasta-cognition/src/vasta_cognition/__init__.py
- packages/vasta-cognition/pyproject.toml（+pydantic）
- tests/test_cognition.py
- docs/stories/story-5-1-claim-lifecycle.md

## Change Log

- 2026-09-08：Story 5.1 实现完成（与 5.2/5.3/5.4 同批）；308 全绿；状态 review。
