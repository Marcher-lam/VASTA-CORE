---
story_key: 9-7-transaction-batches
baseline_commit: 91cce3d
---

# Story 9.7: 契约预留段激活——dry-run/幂等/补偿/事务批次（G3）

**Status:** review

## Story

As a 工具开发者,
I want ActionContract 预留的幂等键与补偿字段真正激活，支持事务批次,
So that 多步写操作要么全成、要么按逆序补偿。

## Acceptance Criteria:

**Given** 契约预留字段（idempotency_key/compensation）与网关幂等缓存
**When** 声明事务批次（步骤列表 + 整体补偿计划）
**Then** 任一步失败按逆序执行已成功步的 compensate（各留痕）；批次整体一个事务事件（action.batch_settled/aborted）
**And** dry-run 门对批次整体先行；幂等键跨批次稳定（AD-11）（FR-038）

## Tasks/Subtasks

- [x] T1: `TransactionBatch`（步骤列表 + batch_id）+ `execute_batch(session,
      batch)`——顺序执行，失败时**逆序**补偿已成功步（各步 compensate
      留痕）；整体落 `action.batch_settled` / `action.batch_aborted`
- [x] T2: dry-run 整体门——全部步骤先过 dry_run（任一拒则整批
      `dry_run_rejected` 不执行）；幂等键 `batch_id:step_N:args_hash`
      前缀稳定（AD-11 `_step_idempotency_key`）
- [x] T3: 步骤成败判定——`session.act()` 不抛异常≠成功：恢复可能掩盖
      偏差。事务语义：本步产生的事件窗口内出现 `verification.deviated`
      或引擎离开 `started` → 步骤失败。act 本身异常亦触发补偿。
- [x] T4: 测试 `tests/test_transaction_batch.py` 5 条（全成→settled/
      中步失败→逆序补偿→aborted/dry-run 空批次拒/每步事件留痕/幂等键
      稳定前缀）；全量 562 passed +2 skipped；ruff 全绿；
      import-linter 2 契约 KEPT

## Dev Notes

- 位置：`packages/vastacore-sdk/src/vastacore/transactions.py`（组装根）。
- 底座：Epic 3 网关的 dry_run 门 + 幂等缓存 + ToolAdapter.compensate；
  本 Story 激活契约预留字段并组合为事务层——不修改网关/引擎本体。
- 事件族：action.batch_*（13 族封闭集内——事务是动作组合）。

## Dev Agent Record

### Debug Log

- **契约期望值假阳性**：原测试契约 `prediction.changes=["id=step"]` →
  核验器在错误消息里找到 "step" 子串 → 偏差被误判通过 → 整批 settled。
  修正：期望值与错误消息无交集（"done=True"）。
- **act 不抛 ≠ 成功**：六段链的恢复机制会掩盖工具失败——验证偏差后
  重试可能成功恢复，引擎保持 started、act 正常返回。事务语义需要
  **独立于恢复的成败判定**：事件窗口内 `verification.deviated` 即失败。
- 事件族坑（同 9.3）：`transaction.*` 不在 13 族封闭集 → `action.batch_*`。
- `session._gateway` 存在于 AgentSession 而非 RunEngine（首次写错访问
  路径——AttributeError 暴露）。

### Completion Notes

- 事务层组合：TransactionBatch → 顺序 act → 事件窗口偏差检测 → 逆序
  compensate → 整体事件。底座完全复用 Epic 3 设施（网关 dry_run 门 /
  幂等缓存 / ToolAdapter.compensate），零修改。
- 步骤成败判定是本 Story 的核心语义贡献：恢复 ≠ 成功——事务要求
  契约级偏差即触发补偿，即使恢复已「兜住」执行（蓝图 §12 事务语义）。
- dry-run 整体门：全部步骤先行检查（`supports_dry_run` 且 `allowed`），
  任一拒则整批 dry_run_rejected——副作用零发生。
- 幂等键 `batch_id:step_N:args_hash` 前缀稳定：同批次同步骤重放
  命中网关缓存不重复执行（AD-11）。
- G3 审批与发布全部闭合（9.5 批准五要素 / 9.6 发布灰度 / 9.7 事务批次）。

### File List

- packages/vastacore-sdk/src/vastacore/transactions.py（新增：
  TransactionBatch/BatchStep/BatchResult/execute_batch/
  _step_idempotency_key）
- packages/vastacore-sdk/src/vastacore/__init__.py（导出）
- tests/test_transaction_batch.py（新增：5 条）
- docs/sprint-status.yaml（9-7 状态）

## Change Log

- 2026-09-10: Story 9.7 实现完成（T1–T4 全过，562 passed +2 skipped，ruff/lint 绿）→ review
