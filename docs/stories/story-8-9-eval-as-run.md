---
story_key: 8-9-eval-as-run
baseline_commit: 29be169
---

# Story 8.9: 评测即 Run——替身模型批量回放（G4）

**Status:** review

## Story

As a 平台负责人,
I want VastaLab 任务集经 RunEngine（替身模型）批量运行并产生完整事件流回放,
So that 评测任务与真实 Run 同构，验收 AC-01 从 PARTIAL 翻 FULL。

## Acceptance Criteria

**Given** ≥40 个 VastaLab 任务与 FakeModel 契约替身
**When** 批量运行
**Then** 每任务产出完整事件流（timeline 全覆盖、因果链可溯）且复现包可离线重放
**And** 触发验收矩阵 AC-01 与相关 WAIVER 复评（不等真实适配器——Assumption Audit P1 修正）

## Tasks/Subtasks

- [x] T1: `VastaLabEnv`——任务即环境（reset=决策观察含位置与 goal；execute 应用
      task._step 真实转移——teleport/wind 生效；到 goal 发终局观察，引擎自然
      拒再行动）；`SolvePolicyStandIn`——确定性替身（预解 solve() 路径，
      ModelCapabilities 契约形态）
- [x] T2: `run_tasks_as_runs(tasks, *, root, seed)`——批量：每任务一个
      RunEngine Run（run_id=vlrun-{task_id}），完整生命周期 + 每步模型交换经
      record_model_exchange 落 Artifact+预算（AD-5）；`BatchRunSummary`
      （逐任务 run_id/success/steps/events + runs/success_rate/total_events）
- [x] T3: 完整性守卫——50 任务批量全成功、逐 run timeline covers_all_events
      + run.created…run.completed 闭包 + observation.terminal；复现包抽样 5
      任务离线重放数=事件数；同 seed 双库逐任务归一化流逐字节一致；
      模型交换 artifact 数 ≥ 总步数
- [x] T4: 验收矩阵复评触发——AC-01 PARTIAL→FULL（复评记录二入档），
      P0 3/8→6/8（75.0%），「评测即 Run」结构性缺口（原 9 分风险项）关闭；
      Epic 4-7 评审 defer #1 落地
- [x] T5: 测试 `tests/test_eval_as_run.py` 5 条；全量 470 passed +1 skipped；
      ruff 全绿；import-linter 2 契约 KEPT

## Dev Notes

- 位置：`packages/vastacore-sdk/src/vastacore/batch.py`（组装根）。
- 模型交换不发明事件（AD-5：Artifact+预算即可）；事件流完整性以 run.*
  与 observation.* 为准——与 quickstart 同构。
- 替身策略确定性：solve() 预解路径；wind/teleport 规则在 env 内真实生效
  （同 8.5 后的 solve 可证达）。

## Dev Agent Record

### Debug Log

- 一次 GREEN 通过（无实锤坑）；VastaLabEnv 直接复用 task._step 保证隐藏
  规则语义与任务集/评测框架三方一致（不重写转移逻辑）。

### Completion Notes

- 评测与 Run 同构达成：50 任务（20 主 + 20 噪声 + 10 偏差，≥40）批量运行
  全部成功，每任务完整事件流（生命周期闭包 + 逐步观察 + 终局）与复现包
  离线重放能力——AC-01 的「生成完整回放」不再只靠 quickstart 单环境形态。
- 替身模型决策逐步留痕：record_model_exchange 每步入 CAS（source=
  model.exchange）+ 预算计数——接真实适配器时零结构变更（换 policy 即可）。
- 验收矩阵复评二：AC-01 FULL、P0 75.0%；剩余 P0 缺口 2 项（AC-07 置信
  区间 / AC-08 verifier 重执行——均 WAIVER 候选）。

### File List

- packages/vastacore-sdk/src/vastacore/batch.py（新增：run_tasks_as_runs/
  VastaLabEnv/SolvePolicyStandIn/BatchRunSummary/TaskRunResult）
- packages/vastacore-sdk/src/vastacore/__init__.py（导出）
- tests/test_eval_as_run.py（新增：5 条）
- test-artifacts/traceability-matrix.md（复评记录二：AC-01 FULL）
- docs/sprint-status.yaml（8-9 状态）

## Change Log

- 2026-09-09: Story 8.9 实现完成（T1–T5 全过，470 passed +1 skipped，ruff/lint 绿；AC-01 翻 FULL）→ review
