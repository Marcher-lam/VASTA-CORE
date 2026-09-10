---
story_key: 9-5-approval-records
baseline_commit: d33ec19
---

# Story 9.5: 批准记录五要素绑定（G3）

**Status:** review

## Story

As a 合规审计员,
I want 每次批准绑定动作、参数、范围、时限与批准者,
So that 「谁在何时批了什么」不可抵赖。

## Acceptance Criteria

**Given** Epic 3 的人工控制（approve_pending/revoke）
**When** 批准发生
**Then** approval 记录含五要素（action/args/scope/expires_at/approver）入事件流；超时批准自动失效（时限）
**And** 与既有 approval 工作流集成零语义冲突；审计可按批准者检索（FR-034）

## Tasks/Subtasks

- [x] T1: `ApprovalRecord`（五要素 pydantic 模型：tool/args/scope/
  expires_at/approver + approval_id/approved_at/revoked）+
  `record_approval(store, tool, args, approver, scope, ttl_s)`——
  落 "approvals" 系统流（action.approval_record 事件，五要素全量 payload）
- [x] T2: `is_approval_valid(record, now)` → 撤销/超时自动失效（供给点
  时钟 AD-5；边界含恰过期时刻）；`revoke_approval` 落撤销事件
  （action.approval_revoked）；未知 approval_id 拒绝
- [x] T3: `search_approvals(store, *, approver)` → 按批准者审计检索
  （search_events payload_equals={"approver": ...}——走既有检索面）
- [x] T4: 测试 `tests/test_approval_records.py` 7 条（五要素/超时失效/
  过期边界/撤销+事件/未知拒/按批准者检索/零冲突——Epic 3 approve_pending
  语义不变验证）；全量 548 passed +2 skipped；ruff 全绿；
  import-linter 2 契约 KEPT

## Dev Notes

- 位置：`packages/vastacore-sdk/src/vastacore/approvals.py`（组装根）。
- 既有 approve_pending（Epic 3）不动——本 Story 是参数级审计层
  （FR-034 明文 Stage 3），与引擎级批准并行不替代。
- 时间走 protocols.ids 供给点（AD-5）。

## Dev Agent Record

### Debug Log

- 零冲突测试首版在 async-with 块外调 events()——session 已关触发
  sdk.session_closed（Story 9.1 修复的正确行为）——把 events() 移入块内。

### Completion Notes

- 参数级审计层（FR-034）落地：五要素（action/args/scope/expires_at/
  approver）→ action.approval_record 事件（"approvals" 系统流，
  Sequencer 统一构造）——与 Epic 3 引擎级 approve_pending 并行不替代。
- 超时自动失效：is_approval_valid 供给点时钟比对（revoked 或过时刻
  即 False）；撤销事件独立留痕可追溯原因。
- 按批准者检索走既有 search_events（payload_equals={"approver":...}）——
  审计面与检索面同一条路。
- G3 审批与发布 1/3（9.6 发布灰度、9.7 契约预留段待续）。

### File List

- packages/vastacore-sdk/src/vastacore/approvals.py（新增：ApprovalRecord/
  record_approval/revoke_approval/is_approval_valid/search_approvals）
- packages/vastacore-sdk/src/vastacore/__init__.py（导出）
- tests/test_approval_records.py（新增：7 条）
- tests/test_evidence_access.py（清理一处 F841 残留）
- docs/sprint-status.yaml（9-5 状态）

## Change Log

- 2026-09-10: Story 9.5 实现完成（T1–T4 全过，548 passed +2 skipped，ruff/lint 绿）→ review
