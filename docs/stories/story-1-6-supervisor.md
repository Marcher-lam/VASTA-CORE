---
story_key: 1-6-supervisor
baseline_commit: 6194f95a16cd0271bbc38aaf6a3a4ea5d2bded4b
---

# Story 1.6: Supervisor 循环与预算监控

**Status:** review

## Story

As a 平台工程师,
I want Supervisor 检测重复状态/动作模式与持续偏差并自动暂停升级,
So that 失控循环不继续烧预算。

## Acceptance Criteria

**Given** 构造的循环环境（同一状态-动作模式重复 N 次）
**When** Run 运行至循环出现
**Then** Supervisor 触发暂停、落 `run.paused` + 升级事件且不再消耗动作预算（FR-053）
**And** 检测阈值可配置；持续偏差（连续 M 次核验偏差）同样触发暂停升级（FR-053）；与 Story 1.2 的预算停止协同（预算先到→安全停止；循环/持续偏差先到→暂停升级）

## Tasks/Subtasks

- [x] 1. Supervisor 组件（vasta_runtime.supervisor）：SupervisorConfig（loop_threshold=N 默认 8、deviation_threshold=M 默认 3，可配置）；连续同 (状态签名,动作) 模式计数（模式改变即重置）；连续偏差计数（非偏差即重置）；Escalation 结果对象
- [x] 2. RunEngine 接入：step 在终端守卫后、预算检查前先过循环检测——触发则发 `incident.opened`（升级事件，13 族封闭集）→ 转 paused（run.paused payload 带 escalation）→ 抛 SupervisorEscalationError；被检动作不执行、不耗预算
- [x] 3. note_deviation(deviation)：核验偏差喂给 Supervisor（Epic 3 将接线），连续 M 次触发同路径升级
- [x] 4. 计数器复位语义：resume（人工已审阅）与 reset（新 episode）清零
- [x] 5. 协同测试：循环先到→暂停升级（预算未耗）；预算先到→安全停止（FAILED）；交替动作打断模式计数不升级；阈值可配置生效
- [x] 6. 对照 AC 验证并更新记录

## Dev Notes

- 默认 loop_threshold=8 的取值：避开既有 1.2/1.3 测试的短序列（≤3 步同动作），蓝图未定数值、PRD 只要求可配置。
- 升级事件用 `incident.opened`（13 族封闭集内），payload 带 reason（supervisor_loop/supervisor_deviations）与模式详情。
- SupervisorEscalationError 继承 VastaError（错误信封约定），带 reason 属性。
- 模式键：状态签名（kind+available_actions）+ action.tool + 规范化 args JSON（可哈希）。

## Dev Agent Record

### Implementation Plan

1. `supervisor.py`：SupervisorConfig（ge=1 校验）/EscalationReason/Escalation/SupervisorEscalationError/Supervisor——check_loop（连续模式计数，键含规范化 args）、note_deviation（连续偏差）、reset_loop/reset_all。
2. `runner.py`：supervisor 构造参数；step 在预算检查前插入循环检测，触发走 `_escalate()`（incident.opened → run.paused(escalation payload) → raise）；note_deviation 公开方法（需 STARTED）；resume/reset 均调 supervisor.reset_all。
3. 测试：LoopEnv（状态永不变）驱动——升级时序/预算不耗/阈值配置/交替动作打断/resume 与 reset 清零；连续偏差三态；预算先到协同；组件级单测（无签名 no-op、args 区分模式）。

### Debug Log

- 测试工厂首版含一行 no-op 残留（config 赋值自赋值），实现中即刻清除。
- ruff 2 处自动修复（导入排序）后全绿；既有 86 测试零回归（默认阈值 8 的取值正为此）。

### Completion Notes

AC 逐条验证：
1. **循环触发暂停+升级事件+不耗预算（FR-053）** — `test_loop_escalates_pauses_without_spending_budget`：threshold=3 第 3 步抛 SupervisorEscalationError(LOOP)，状态 paused，`execute_count==2` 且 `actions_used==2`（被检动作未执行未计数）；事件序末两条恰为 `incident.opened`（reason=supervisor_loop）→ `run.paused`（payload.escalation.reason）。✅
2. **阈值可配置** — `test_threshold_configurable`（5 次触发）与组件单测。✅
3. **持续偏差** — `test_consecutive_deviations_escalate`（连续 3 次→同路径升级暂停）；`test_non_deviation_resets_streak`（False 打断连续性不升级）；note_deviation 需 STARTED。✅
4. **协同** — `test_budget_first_safe_stops`：预算耗尽在第 3 步先于循环阈值（8）触发 → run.failed 安全停止（FAILED 而非 paused）；对偶场景即 AC1（循环先到→暂停，预算未耗）。✅
5. **复位语义** — resume 后重新计数不立即再升级；env reset 清零（新 episode 两轮各 2 次均不触发）。✅
6. **模式区分** — 交替动作（同签名不同 tool）连续计数永不超过 1；同 tool 不同 args 也是不同模式（组件单测）。✅

回归：全套 97 passed（前序 86 + 本故事 11）；ruff 全绿；import-linter 双契约 KEPT。

## File List

- packages/vasta-runtime/src/vasta_runtime/supervisor.py（新建）
- packages/vasta-runtime/src/vasta_runtime/runner.py（修改：supervisor 参数、step 循环检测与 _escalate、note_deviation、resume/reset 复位）
- packages/vasta-runtime/src/vasta_runtime/__init__.py（修改：导出 Supervisor 族）
- tests/test_supervisor.py（新建，11 测试）
- docs/stories/story-1-6-supervisor.md（本文件）

## Change Log

- 2026-09-08：Story 1.6 实现完成——Supervisor 循环/持续偏差双检测、incident.opened 升级路径、预算协同两分支、resume/reset 复位语义；97 测试全绿；全部 AC 验证通过，状态置 review。
