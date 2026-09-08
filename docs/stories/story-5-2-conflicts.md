---
story_key: 5-2-conflicts
baseline_commit: aad7789
---

# Story 5.2: 显式冲突

**Status:** review

## Story

As a 领域专家,
I want 同范围内互斥的主张产生显式 Conflict 记录而不是被静默覆盖,
So that 矛盾的理解可见、可裁决。

## Acceptance Criteria

**Given** 同范围两条互斥陈述的 Claim
**When** 第二条提出
**Then** 产生显式 Conflict 记录关联双方，检索双双呈现（FR-023）
**And** 冲突解决（缩范围/推翻一方/合并）产生新事件且可追溯

## Tasks/Subtasks

- [x] 1. ConflictService.detect（scope_key 分组、活跃主张、≥2 即冲突）/ resolve（保留方校验）
- [x] 2. 测试：互斥冲突、异 scope 无冲突、已推翻不参与、解决校验
- [x] 3. 对照 AC 验证

## Dev Notes

- 解决动作的"新事件"由调用方经 CognitionService 落（dispute/refute/narrow）；ConflictService 记录冲突本身。

## Dev Agent Record

见 story-5-1（同批交付）。Conflict detect 按活跃主张 scope 分组；已推翻/退役排除。

## File List

- cognition.py ConflictService；tests/test_cognition.py TestConflict

## Change Log

- 2026-09-08：Story 5.2 实现完成；状态 review。
