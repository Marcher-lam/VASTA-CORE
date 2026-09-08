---
story_key: 1-3-observation-collection
baseline_commit: 6781a2e6d2ad57cdf3cbc88d880670bc56e1e589
---

# Story 1.3: 五类 Observation 采集

**Status:** review

## Story

As a Agent 开发者,
I want 环境交互产生的决策/过渡/终局/重置/外部五类 Observation 被正确分类并落库,
So that 核验与回放不会把动画帧或终局画面误判为可行动状态。

## Acceptance Criteria

**Given** 一个返回"决策帧→动画过渡帧→终局帧"序列的环境适配器
**When** Run 执行动作并采集观察
**Then** 五类 Observation 以 `observation.decision/transition/terminal/reset/external` 事件类型落库（FR-005，13 族封闭集）
**And** 终局与过渡帧不被标记为可行动状态（下游核验器测试可断言）

## Tasks/Subtasks

- [x] 1. ObservationCollector（vasta_runtime.observation）：分类记录、每类计数、episode_ended 跟踪、last_actionable 只在决策帧更新（结构上排除非决策帧成为可行动状态）
- [x] 2. 事件 payload 携带 kind/available_actions/artifact_refs/actionable 标志（下游核验器可直接断言）
- [x] 3. RunEngine 接入 collector：终局后再 step 拒绝（蓝图 §33.1 性质"终局后不行动"）；新增 reset(seed)（发 observation.reset + observation.decision 并清除 episode_ended）与 ingest_external(detail)（发 observation.external）
- [x] 4. 测试：决策→过渡→终局序列分类与 episode_ended；终局后 step 拒绝；reset 恢复行动；external 采集不改变可行动状态；五类事件类型全覆盖断言；非决策帧永不 actionable 的性质测试（hypothesis 遍历 kind 组合）
- [x] 5. 回归：Story 1.1/1.2 测试保持绿
- [x] 6. 对照 AC 验证并更新记录

## Dev Notes

- 引擎现有 `_record_observation`（Story 1.2 的极简采集器）重构为经 collector；观察签名（checkpoint 比对）行为不变。
- reset/external 的事件也走因果链（parent=上一事件）。
- episode_ended 只由 observation.terminal 置位、由 reset 清除——外部事件（observation.external）不算终局。
- 包归属 vasta-runtime；不引入新依赖。

## Dev Agent Record

### Implementation Plan

1. `observation.py`：ObservationCollector——record() 返回带 actionable 标志的 payload；decision 更新 last_actionable、terminal 置 episode_ended、reset 清除；ensure_actable() 供引擎终局守卫；TerminalObservationError。
2. `runner.py` 接入：构造建 collector；_record_observation 统一走 collector（payload 一致化）；step 先过终局守卫（VastaError code=run.terminal）再预算；新增 reset(seed)（reset 标记经 collector 记录，兼顾清除终局态与计数）与 ingest_external(detail)。
3. 测试：TerminalEnv（决策→过渡→终局序列）+ 五类全覆盖场景 + hypothesis 两条性质（非决策永不 actionable；actionable 跟随最近决策帧）。

### Debug Log

- 首轮 2 处测试失败：reset 标记事件最初直接 _emit 裸 payload（缺 kind/actionable 键，下游断言 KeyError）→ 改为经 collector 的 Observation(kind="reset") 统一记录；另一处为测试自身事件窗口断言数错（[-3:] 应为 [-4:]），修正断言。
- ruff 两处（未用导入、行超长）修复后全绿。

### Completion Notes

AC 逐条验证：
1. **五类事件落库（FR-005）** — `test_all_five_kinds_covered_in_one_scenario`：单场景 reset/decision/external/transition/terminal 五类事件类型全部出现，collector.counts 五键齐备。✅
2. **决策→过渡→终局序列分类** — `test_decision_transition_terminal_classified` 事件序精确断言 [reset, decision, transition, terminal]，episode_ended=True。✅
3. **终局与过渡帧不可行动** — payload actionable 标志四类断言（仅 decision=True）；hypothesis 性质测试：任意非决策 kind 的 payload actionable=False 且不覆盖 last_actionable、actionable 始终跟随最近决策帧；`test_cannot_act_after_terminal` 终局后 step 抛 VastaError(run.terminal) 且不产生新事件。✅
4. **reset 恢复 / external 不算终局** — reset 清除终局态后可继续 step；ingest_external 后 episode_ended=False 且可继续行动。✅

回归：全套 59 passed（1.1 的 38 + 1.2 的 12 + 本故事 9）；ruff 全绿；import-linter 双契约 KEPT。未做：Artifact 载荷与观察事件的真实关联（Story 1.4 CAS 落地后接入 artifact_refs 实值）。

## File List

- packages/vasta-runtime/src/vasta_runtime/observation.py（新建）
- packages/vasta-runtime/src/vasta_runtime/runner.py（修改：collector 接入、终局守卫、reset/ingest_external）
- packages/vasta-runtime/src/vasta_runtime/__init__.py（修改：导出 ObservationCollector/TerminalObservationError）
- tests/test_observation_collection.py（新建，9 测试）
- docs/stories/story-1-3-observation-collection.md（本文件）

## Change Log

- 2026-09-08：Story 1.3 实现完成——ObservationCollector 分类保证、引擎终局守卫与 reset/external 采集、五类事件全覆盖与 hypothesis 性质测试；59 测试全绿；全部 AC 验证通过，状态置 review。
