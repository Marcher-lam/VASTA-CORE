---
story_key: 5-3-invalidation
baseline_commit: aad7789
---

# Story 5.3: 失效传播

**Status:** review

## Story

As a 平台工程师,
I want 依赖主张失效时受影响的 Plan 与资产被自动标记,
So that 建立在过时理解上的行动不会继续。

## Acceptance Criteria

**Given** 依赖某 Hypothesis 的活跃 Plan 与该 Hypothesis 被反例推翻
**When** 失效传播执行
**Then** 受影响 Plan/资产被标记失效并通知（FR-024）
**And** 与 Epic 3 联动：偏差注入场景中旧计划 100% 停止（AC-04 的认知侧路径）

## Tasks/Subtasks

- [x] 1. refute() 级联：依赖图传播（直接+间接依赖均 refuted，propagated_from 记录）
- [x] 2. 测试：三级链级联、无关主张不受影响
- [x] 3. 对照 AC 验证

## Dev Notes

- Plan 侧失效在 Story 3.5（execute_contracted 偏差联动）；本故事交付主张图内部传播。

## Dev Agent Record

见 story-5-1（同批交付）。

## File List

- cognition.py refute 级联；tests/test_cognition.py TestInvalidationPropagation

## Change Log

- 2026-09-08：Story 5.3 实现完成；状态 review。
