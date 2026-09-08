---
story_key: 1-2-run-lifecycle-budget
baseline_commit: a912467a833d48bdda703bd9bf22d066604d5dc2
---

# Story 1.2: Run 生命周期与预算

**Status:** review

## Story

As a Agent 平台工程师,
I want Run 的启动/暂停/恢复/取消/完成/失败状态机与三档预算（动作数/模型调用/时长）,
So that 任何失控 Run 都会安全停止而不是无限消耗。

## Acceptance Criteria

**Given** 已装配的 Local Runtime 与假环境适配器
**When** 启动 Run 并逐步执行动作
**Then** 每次状态转移产生对应 `run.*` 事件（含因果父项），暂停后恢复时先重新观察环境再与检查点比对（FR-004）
**And** 任一预算超限触发安全停止并落安全停止事件（复现包导出能力由 Epic 3/4 提供）；检查点含最后已提交动作、活跃计划、剩余预算

## Tasks/Subtasks

- [x] 1. RunState 状态机（created→started⇄paused→completed/failed/cancelled）+ 非法转移拒绝（vasta_runtime.state）
- [x] 2. 三档预算 Budget/BudgetTracker（动作数/模型调用/墙钟秒；墙钟属安全强制用真实时钟、可注入便于测试——AD-15）
- [x] 3. Checkpoint 模型（最后已提交动作、活跃计划占位、剩余预算快照、最后观察签名）
- [x] 4. RunEngine：构造发 run.created；start/step/pause/resume/cancel/complete/fail/safe_stop；每次转移发 run.* 事件且 parent=上一事件（因果链）；step 预算先检、超限→安全停止（failed + run.failed payload.safe_stop）后重抛
- [x] 5. resume 语义：先 env.observe() 再与暂停检查点比对，环境变化记入 run.resumed payload（不静默）
- [x] 6. 测试：状态机全转移 + 非法转移拒绝；动作/墙钟两档超限安全停止；暂停-恢复-环境变化检出；检查点字段断言；事件链 parent 完整性（复用 tests/fakes.py）
- [x] 7. 对照 AC 验证并更新记录

## Dev Notes

- 包归属：vasta-runtime（AD-1：依赖 protocols；禁止 import adapters/sdk——import-linter 契约 2）。
- 事件类型（13 族封闭集）：run.created/started/paused/resumed/completed/failed/cancelled；观察事件 observation.<kind> 由 step 内的极简采集器发出（完整五类保证属 Story 1.3，将扩充测试）。
- AD-15：预算墙钟是安全强制 → 默认真实时钟，参数可注入（测试与 AD-5 RunContext 在 Story 1.5 正式化）。
- 检查点 active_plans 为占位列表（计划实体属 Epic 3/6）。
- 安全停止落 run.failed（payload: safe_stop=true, reason=budget kind）；复现包导出属 Epic 3/4，不在本故事。

## Dev Agent Record

### Implementation Plan

1. `state.py`：RunState 枚举 + 允许转移表 + assert_transition（终态封闭）。
2. `budget.py`：Budget（三档可空上限）/BudgetTracker（预检语义：计数档 used>=max 无余量即拒、墙钟档 used>max；时钟可注入）/BudgetSnapshot/BudgetExceededError。
3. `checkpoint.py`：Checkpoint + ObservationSignature（kind + available_actions 的最小比对形态）。
4. `runner.py`：RunEngine——异步工厂 `create()` 发 run.created；全部生命周期方法 async；_emit 经 StorageAdapter.append_event（AD-10 await）；step 预算先检（超限动作不执行）；安全停止统一落 run.failed(payload.safe_stop) 后重抛；resume 先 observe 再比对检查点签名，env_changed 显式入 payload。
5. 测试：FakeClock（墙钟注入）+ MutableEnv（动作集可变，环境变化检测）复用 FakeStorageAdapter。

### Debug Log

- 首轮 10 处失败，两类根因：
  1. StorageAdapter.append_event 为异步端口，同步构造器内调用产生未等待协程 → 重构为异步工厂 `await RunEngine.create(...)`，全链路 await（AD-10）。
  2. 预算比较语义错误（used>max 才拒，导致第 max+1 个动作先执行再停止）→ 改为预检语义 used>=max 无余量即拒；同时把预检路径也纳入安全停止包装（原先只包了后检）。
- resume() 初版含一处占位表达式，实现内即刻发现并改为返回 run.resumed 事件信封。
- ruff 3 处自动修复（导入排序等）后全绿。

### Completion Notes

AC 逐条验证：
1. **状态转移事件 + 因果父项** — `test_full_lifecycle_transitions_emit_events` 断言事件序 [run.created/started/paused/resumed/completed]；`test_every_event_has_parent_chain` 断言 seq 连续且每个事件 parent=前一事件 event_id，首事件无父。✅
2. **resume 先观察再比对（FR-004）** — `test_resume_reobserves_and_detects_env_change`：暂停期间改环境动作集 → resume 返回 env_changed=True 且 run.resumed payload 记录 env_changed 与观察到的动作；未变化场景 env_changed=False。✅
3. **预算超限安全停止** — 动作档（max=2：第三次 step 抛 BudgetExceededError、状态 FAILED、末事件 run.failed payload.safe_stop=True/reason=actions、且 env.execute_count==2 证明超限动作未执行）；墙钟档（注入 FakeClock 前进 11s > 10s：同样安全停止）；模型调用档（第 2 次登记被拒并安全停止）。✅
4. **检查点字段** — `test_checkpoint_contains_required_fields`：state/last_event_seq/last_action（含 args）/active_plans/剩余预算快照/最后观察签名全部断言。✅
5. **非法转移拒绝** — created→paused、started→started、终态再转移均抛 InvalidTransitionError 且不产生事件。✅

回归：全套 50 passed（含 Story 1.1 的 38）；ruff 全绿；import-linter 双契约 KEPT。超出范围未做：复现包导出（Epic 3/4）、活跃计划实体（Epic 3/6）、RunContext 完整确定性（Story 1.5）。

## File List

- packages/vasta-runtime/pyproject.toml（修改：+pydantic 依赖）
- packages/vasta-runtime/src/vasta_runtime/__init__.py（重写：公共 API 再导出）
- packages/vasta-runtime/src/vasta_runtime/state.py（新建）
- packages/vasta-runtime/src/vasta_runtime/budget.py（新建）
- packages/vasta-runtime/src/vasta_runtime/checkpoint.py（新建）
- packages/vasta-runtime/src/vasta_runtime/runner.py（新建）
- tests/test_run_engine.py（新建，12 测试）
- docs/stories/story-1-2-run-lifecycle-budget.md（本文件）

## Change Log

- 2026-09-08：Story 1.2 实现完成——RunEngine 状态机/三档预算（预检语义）/检查点/因果事件链/安全停止/resume 环境变化检测；50 测试全绿；全部 AC 验证通过，状态置 review。
