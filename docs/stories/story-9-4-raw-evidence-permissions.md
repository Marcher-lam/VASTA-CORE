---
story_key: 9-4-raw-evidence-permissions
baseline_commit: 66edb18
---

# Story 9.4: 原始证据权限独立（G2）

**Status:** review

## Story

As a 数据管理者,
I want 原始证据的访问权限独立于派生物与聚合指标,
So that 共享分析结论不等于泄露原始截图/响应。

## Acceptance Criteria

**Given** 派生物（血缘可达）与原始 Artifact
**When** 原始证据设为受限作用域
**Then** 派生物/聚合指标仍可读；原始 blob 取回被拒（作用域检查）；血缘链不因权限断链（引用可见、内容不可达）
**And** 权限判定落审计事件（FR-018）

## Tasks/Subtasks

- [x] T1: `restricted_artifacts` 表（sha/reason/restricted_at）+
      `restrict_evidence(store, sha, reason)` / `unrestrict_evidence`
      ——幂等（重复 restrict 更新 reason 不炸）
- [x] T2: `get_artifact_checked(store, sha, ...)` ——受限 sha 抛
      `evidence.access_denied`（与 `artifact.not_found` 明确区分——
      排查路径分叉）；非受限走原 get_artifact 路径（后向兼容叠加层）
- [x] T3: `check_evidence_access(store, sha)` → allowed/denied/not_found
      （不取 blob——元数据面查询）；拒绝落审计事件
      （`artifact.access_denied`——"access" 系统流，含 sha/reason/
      requested_by）
- [x] T4: 测试 `tests/test_evidence_access.py` 8 条（受限拒/派生可读
      +原 get 不改/血缘链不断/unrestrict 恢复/审计事件/双错码区分/
      重复 restrict 幂等/check 不取 blob）；全量 541 passed +2 skipped；
      ruff 全绿；import-linter 2 契约 KEPT

## Dev Notes

- 位置：`packages/vasta-storage/src/vasta_storage/evidence_access.py`。
- 原始 get_artifact 不改（后向兼容）——权限检查是叠加层（get_checked）。
- 血缘/检索面不检查受限（元数据面 vs 内容面的权限分界——FR-018 语义）。

## Dev Agent Record

### Debug Log

- 单句源的 text_summary 产出 = 原文 → 同 sha → 派生物"也被限"假阳性——
  改双句源使摘要真正不同（derive 的 sha 不同于源——测试前提正确性）。
- bytes 字面量不能含非 ASCII（Python 语法限制）——中文 bytes 用
  `"中文".encode("utf-8")` 形态。

### Completion Notes

- 权限分层：原始 get_artifact（后向兼容，不限）/ get_artifact_checked
  （权限叠加层）/ check_evidence_access（元数据面检查，不取 blob）——
  三入口语义明确，血缘/检索面完全不受限（FR-018「权限独立于派生物」）。
- 受限 ≠ 不存在（双错码区分）：evidence.access_denied vs
  artifact.not_found——排查路径分叉，审计/告警语义不同。
- 审计事件 artifact.access_denied 落 "access" 系统流（Sequencer），
  含 sha/reason/requested_by。
- G2 数据治理两 Story（9.3 删除证明 + 9.4 权限独立）全部闭合。

### File List

- packages/vasta-storage/src/vasta_storage/evidence_access.py（新增：
  restrict_evidence/unrestrict_evidence/get_artifact_checked/
  check_evidence_access）
- packages/vasta-storage/src/vasta_storage/__init__.py（导出）
- tests/test_evidence_access.py（新增：8 条）
- docs/sprint-status.yaml（9-4 状态）

## Change Log

- 2026-09-10: Story 9.4 实现完成（T1–T4 全过，541 passed +2 skipped，ruff/lint 绿）→ review
