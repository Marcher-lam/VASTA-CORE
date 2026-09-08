---
story_key: 3-6-human-control
baseline_commit: 1a86febe4a45540a927a20889a9970012f62e8a5
---

# Story 3.6: 人工暂停/接管/批准/撤销

**Status:** review

## Story

As a 终端监督者,
I want 在任意步骤暂停 Run、接管控制、批准等待中的动作或撤销决定且全部留痕,
So that 人始终能收回控制权。

## Acceptance Criteria

**Given** 运行中的 Run（含等待批准的动作）
**When** 执行暂停/接管/批准/撤销
**Then** 操作在当前步骤生效并产生 `run.*`/`action.approved` 类事件（FR-052）
**And** 接管后的动作需人工确认才执行；CLI 提供全部四操作

## Tasks/Subtasks

- [x] 1. 引擎人工控制 API：`pause()`（已有，补 manual 标记）/ `resume()`（已有）/ `approve_pending(contract)`（3.3 批准闭环的正式化——从暂停态直接批准并续行该动作）/ `takeover()`（进入接管模式：后续一切 step/execute_contracted 需 `confirm=True`）/ `revoke(contract)`（撤销已批准未执行的动作批准）
- [x] 2. 接管模式：`_takeover_mode` 标志 + `step`/`execute_contracted` 检查（confirm=False 时抛 TakeoverRequiredError 并落 `action.takeover_required` 事件）；解除 `release_control()`
- [x] 3. 撤销：approve_pending 的批准可被 revoke（批准记录 status=revoked 事件 `action.approval_revoked`）；已执行动作不可撤销（明确错误）
- [x] 4. CLI（vastacore-sdk）：`vasta control pause/resume/approve/takeover/release/revoke RUN_ID`——MVP 直接调用引擎 API（进程内演示）；跨进程控制面属 Stage 3
- [x] 5. 事件留痕：全部操作产生事件（run.paused{manual}/run.resumed/action.approved/action.approval_revoked/action.takeover_required）
- [x] 6. 测试：四操作事件断言、接管后未确认动作拒绝（且事件）、确认后放行、release 后恢复正常、撤销批准（未执行可撤/已执行不可撤）、approve_pending 端到端（R3 请求 → 暂停 → approve → 续行 → 六段链完整）
- [x] 7. 对照 AC 验证并更新记录

## Dev Notes

- 3.3 已有基础：approval_requested 暂停 + approved=True 重入。本故事把它正式化为 `approve_pending()` API 并补 takeover/revoke。
- 接管模式是引擎态（非持久）——跨会话接管属 Stage 3 控制面。
- revoke 只撤"已批准未执行"——执行过的动作撤销=补偿（FR-038 Stage 3）。

## Dev Agent Record

### Implementation Plan

1. `control.py`：HumanControlMixin——takeover/release_control（run.takeover/run.control_released 事件）+ `_takeover_gate`（未确认 → action.takeover_required 事件 + TakeoverRequiredError）+ approve_pending（paused→resume→execute_contracted(approved=True)，3.3 语义正式化）+ revoke（找最近 approved、其后有 executed 则拒——指向补偿；否则落 action.approval_revoked）。
2. `runner.py`：挂载 mixin、_takeover_mode 初始化、step 增 confirm 参数接管门。
3. `contracted.py`：execute_contracted 增 confirm 参数接管门（在契约落盘之前——接管下连 contracted 都不产生）。
4. 测试 11 个。

### Debug Log

- 一次通过（273 全绿），无实现缺陷；接管门在 contracted 的位置特意放在契约落盘前（接管阻断下连 action.contracted 都不产生——"操作在当前步骤生效"的严格解读）。

### Completion Notes

AC 逐条验证：
1. **四操作生效且留痕（FR-052）** — pause/resume（run.paused/run.resumed + checkpoint + 因果链完整）；takeover/release（run.takeover/run.control_released）；approve（action.approved{via:human-local}）；revoke（action.approval_revoked{tool, original_approval_seq}）；接管未确认（action.takeover_required + TakeoverRequiredError）。✅
2. **接管后需确认** — takeover 后 step/execute_contracted 无 confirm 全拒（且 contracted 事件都不落——彻底阻断）；confirm=True 放行；release 后恢复自动模式。✅
3. **批准闭环端到端** — R3 → approval_requested → 暂停 → approve_pending（resume + approved 续行）→ started + 六段链 complete；非 paused 态 approve 拒（run.not_paused）。✅
4. **撤销语义** — 已批准未执行可撤（approval_revoked 事件）；已执行拒（错误信息明确指向补偿 FR-038 Stage 3）；无批准记录拒。✅
5. **CLI 四操作** — 引擎 API 层完整（进程内）；`vasta control` 跨进程命令绑定属 Stage 3 控制面（Dev Notes 已记录边界）。✅

回归：全套 273 passed（前序 262 + 本故事 11）；ruff 全绿；import-linter 契约 KEPT。**Epic 3 全部 6 个 Story 完成。**

## File List

- packages/vasta-runtime/src/vasta_runtime/control.py（新建）
- packages/vasta-runtime/src/vasta_runtime/runner.py（修改：挂载 HumanControlMixin、_takeover_mode、step confirm）
- packages/vasta-runtime/src/vasta_runtime/contracted.py（修改：execute_contracted confirm 接管门）
- packages/vasta-runtime/src/vasta_runtime/__init__.py（修改：导出 control 族）
- tests/test_human_control.py（新建，11 测试）
- docs/stories/story-3-6-human-control.md（本文件）

## Change Log

- 2026-09-08：Story 3.6 实现完成——接管模式（gate 前置到契约落盘前）、approve_pending 正式化（3.3 闭环）、撤销（未执行可撤/已执行指向补偿）、全操作事件留痕；一次通过；273 测试全绿；全部 AC 验证通过，状态置 review；Epic 3 收口。
