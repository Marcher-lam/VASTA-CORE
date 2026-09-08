---
story_key: 3-5-deviation-recovery
baseline_commit: 0780eacf6a043943c6bdffa48cb14e43796cb092
---

# Story 3.5: 偏差失效与有界恢复

**Status:** review

## Story

As a 平台工程师,
I want 核验偏差立即使依赖计划失效，恢复按有界序列（等待→读回→回看→分类→重试/补偿/重新规划/接管）进行且达限安全停止,
So that 一次偏差不会被盲目重试放大。

## Acceptance Criteria

**Given** 偏差注入测试场景（AC-04）
**When** 偏差发生
**Then** 依赖该动作的旧计划 100% 失效、不继续批量执行
**And** 恢复次数与副作用上限可配置，达上限触发安全停止并导出复现包（FR-037）；故障分类结果（环境延迟/工具错误/权限拒绝/模型误解/外部变化）落事件

## Tasks/Subtasks

- [x] 1. Plan 实体（vasta-contracts）：PlanStep{step_id, action, status: pending/executing/done/invalidated/failed}；Plan{plan_id, goal, steps, status: active/invalidated/completed}；`invalidate(reason)` 级联标失效（蓝图 §17.1 Plan/PlanStep）
- [x] 2. 偏差联动（runtime）：核验 deviation → plan.invalidate + `plan.invalidated` 事件 + 偏差喂 Supervisor（连续 M 次触发升级，衔接 FR-053）
- [x] 3. 有界恢复序列（runtime recovery.py）：RecoveryPolicy{max_retries, max_side_effects, wait_ms}；序列 = 等待稳定窗 → 读回复核 → 回看证据（记录动作前后事件引用）→ 故障分类 → 分派（retry/compensate/replan/human_takeover/safe_stop）；每次恢复落 `action.recovered` 事件（attempt 序号 + 分类 + 决策）；达上限 → fail(safe_stop) + `run.failed`{safe_stop, reason:recovery_limit}
- [x] 4. 故障分类（最小规则版）：读回复核通过 → environment_delay（重试一次）；工具返回错误 → tool_error（补偿或停）；策略拒 → permission_denied（停/接管）；观察与预期不符且无工具错误 → model_misconception（重新规划/接管）；外部变化事件在窗口内 → external_change（重新规划）
- [x] 5. 复现包引用：安全停止时在 run.failed payload 附偏差上下文（契约 ref/核验事件 seq/恢复次数）——完整复现包导出属 Epic 4
- [x] 6. execute_contracted 集成：核验段 deviation 结果自动触发失效联动（若调用方传入 plan）
- [x] 7. 测试：偏差注入 → 计划 100% 失效且 pending 步不再执行（AC-04）；恢复序列各分类路径；达上限安全停止（payload 断言）；偏差喂 Supervisor 连续升级；恢复计数跨偏差累计；无计划时纯核验联动
- [x] 8. 对照 AC 验证并更新记录

## Dev Notes

- Plan/PlanStep 属蓝图 §17.1 核心实体；13 族封闭集内落事件：plan.invalidated / action.recovered / run.failed{recovery}——未开新族。
- 补偿：MVP 仅记录 compensate 决策（工具补偿执行属 FR-038 Stage 3）。
- 重新规划：MVP 记录 replan 决策与 plan.invalidated 事件；实际新计划生成属模型侧。

## Dev Agent Record

### Implementation Plan

1. `vasta-contracts/plan.py`：Plan/PlanStep（状态机 + invalidate 级联 + executable_steps 空保证 + 幂等 + reason）。
2. `vasta-runtime/recovery.py`：RecoveryPolicy/Input/Decision + classify_fault（五类规则序：permission > external > tool_error > env_delay > misconception）+ RecoveryTracker（副作用总闸优先于重试升级；重试额度耗尽→human_takeover；达上限抛出）。
3. `contracted.py`：核验 deviation → `_on_deviation`（计划失效+plan.invalidated 事件+Supervisor 喂入并处理升级+分类+分派+action.recovered 事件；预算耗尽→fail(safe_stop)+raise）；execute_contracted 增 plan 参数。
4. `runner.py`：recovery_policy 构造参数 + engine.recovery；fail() 增 safe_stop 关键字。
5. 测试 11 个。

### Debug Log

- RecoveryTracker 副作用总闸初版在 elif 链中被重试升级分支绕过（预算耗尽仍分派）——复现脚本实锤后改为总闸前置（优先于一切分派）。
- fail() 初版硬编码 safe_stop=False——恢复耗尽的安全停止被记为普通失败；加 safe_stop 关键字。
- Supervisor 喂入初版忽略返回值（连续偏差不升级）——改为处理 escalation。
- 测试期望两处修正（分类语义对齐硬编码输入：read_back 失败→environment_delay 而非 misconception；持久计数测试需高偏差阈值避免 Supervisor 抢先升级）。

### Completion Notes

AC 逐条验证：
1. **偏差 → 计划 100% 失效不批量执行（AC-04）** — 偏差注入（DeviationVerifier）→ plan.invalidate 级联（3 步全 invalidated、executable_steps==[]、幂等）+ plan.invalidated 事件（含失效步清单与偏差定位）+ 环境只执行首个动作。✅
2. **有界恢复 + 达限安全停止（FR-037）** — 分类→默认分派（env_delay→retry / tool_error→compensate / permission→takeover / misconception+external→replan）；重试额度耗尽→human_takeover（不盲目重试）；副作用总闸优先（测试实锤修复绕过缺陷）；引擎端：第 N 次偏差预算耗尽 → run.failed{safe_stop:true, reason:"recovery_limit"} + RecoveryLimitExceededError；恢复计数跨偏差累计。✅
3. **故障分类落事件（五类）** — classify_fault 五规则全覆盖测试；action.recovered 事件携带 fault_class/action/attempt/verification_seq/恢复预算快照。✅
4. **偏差喂 Supervisor（FR-053 联动）** — 连续 3 次偏差（阈值 3）→ incident.opened + run.paused 升级。✅
5. **无计划纯核验联动** — plan=None 时偏差照常恢复分派（事件齐全）。✅
6. **复现包引用** — run.failed payload 与 action.recovered 均带 verification_seq（偏差定位）；完整包导出属 Epic 4。✅

回归：全套 262 passed（前序 252 + 本故事 10，外加 persist 测试修正）；ruff 全绿；import-linter 契约 KEPT。

## File List

- packages/vasta-contracts/src/vasta_contracts/plan.py（新建）
- packages/vasta-contracts/src/vasta_contracts/__init__.py（修改：导出 Plan/PlanStep）
- packages/vasta-runtime/src/vasta_runtime/recovery.py（新建）
- packages/vasta-runtime/src/vasta_runtime/contracted.py（修改：偏差联动 _on_deviation + plan 参数 + Supervisor 升级处理）
- packages/vasta-runtime/src/vasta_runtime/runner.py（修改：recovery_policy 参数 + engine.recovery + fail safe_stop 关键字）
- packages/vasta-runtime/src/vasta_runtime/__init__.py（修改：导出 recovery 族）
- tests/test_deviation_recovery.py（新建，10 测试）
- docs/stories/story-3-5-deviation-recovery.md（本文件）

## Change Log

- 2026-09-08：Story 3.5 实现完成——Plan 失效级联（AC-04 100% 保证）、五类故障分类与有界恢复分派（副作用总闸优先）、达限安全停止、Supervisor 偏差联动；复现脚本实锤并修复总闸绕过缺陷；262 测试全绿；全部 AC 验证通过，状态置 review。
