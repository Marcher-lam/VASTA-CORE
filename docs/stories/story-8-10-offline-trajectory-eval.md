---
story_key: 8-10-offline-trajectory-eval
baseline_commit: 4536464
---

# Story 8.10: 历史轨迹离线评估（G4）

**Status:** review

## Story

As a 平台负责人,
I want 对导入的历史轨迹离线评估新策略/核验器/模型,
So that 不重跑生产就能预判切换影响。

## Acceptance Criteria

**Given** Story 8.2 导入的轨迹与新核验器/策略配置
**When** 离线评估
**Then** 产出旧结果 vs 新结果对比报告（偏差清单含事件定位）
**And** 评估本身零副作用（只读回放，不产生新动作）（FR-066）

## Tasks/Subtasks

- [x] T1: `offline_evaluate(store, run_id, *, verifiers, expected_changes_provider)`
      ——只读重放：逐 action（contracted 取 args / executed 取 result_ref→CAS /
      后续观察取 after）重建核验证据，跑新核验器取新判定
- [x] T2: 旧结果提取——原流中该动作后的 verification.* 事件（引擎产生；
      事件后缀词表归一为 VerificationOutcome：passed→pass/errored→system_error）；
      导入轨迹无核验历史 → none-recorded 如实标注（不伪造旧 pass）
- [x] T3: `OfflineEvalReport`——逐动作新旧对照（`changed` 冲突标记）+ 偏差
      清单（seq 事件定位 + tool + 新旧判定 + 证据摘要含核验器偏差详情）+
      汇总（actions_evaluated/changed/unchanged）；冲突语义：none-recorded+
      新 pass 不算冲突（切换无影响）、新 deviation 一律冲突（会拦历史动作）
- [x] T4: 零副作用守卫——评估前后事件数/工件数不变（测试锚定，重复评估两遍）
- [x] T5: 测试 `tests/test_offline_eval.py` 5 条（导入轨迹×严核验器→偏差
      定位 / 匹配核验器→unchanged / 引擎 run 新旧对照双向 / 零副作用 /
      未知 run 拒）；全量 475 passed +1 skipped；ruff 全绿；import-linter
      2 契约 KEPT

## Dev Notes

- 位置：`packages/vastacore-sdk/src/vastacore/offline_eval.py`（组装根）。
- 证据重建与引擎核验同构：after_observation（后续观察 payload.detail）+
  result（executed.result_ref → CAS blob → dict）+ expected_changes
  （provider 供给，缺省无预期则核验器自判）。
- 导入轨迹的旧判定=none-recorded（历史记录无核验事件）——不伪造旧 pass。

## Dev Agent Record

### Debug Log

- 词表坑：事件后缀（passed/errored）与 VerificationOutcome（pass/system_error）
  不同词——归一映射表显式声明，否则新旧对照恒假冲突。
- 偏差详情首版只在核验器返回值里、未入报告——补进 ActionComparison.detail
  （证据摘要含核验器期望值，排障直达）。

### Completion Notes

- 与 8.2 配对闭环：导入的轨迹立即成为离线评估输入（不重跑生产预判切换影响）。
- 冲突语义明确三类：旧 pass × 新 deviation（切换会拦）→ changed；
  导入 none-recorded × 新 deviation（新核验器会拦历史动作）→ changed；
  none-recorded × 新 pass（切换无影响）→ unchanged。
- 引擎 run 双向实测：同期望核验器 unchanged、错期望核验器 changed（旧 pass
  被推翻定位到 seq）。
- G4（回溯与离线评估）四 Story 就此全部闭合。

### File List

- packages/vastacore-sdk/src/vastacore/offline_eval.py（新增：offline_evaluate/
  OfflineEvalReport/ActionComparison）
- packages/vastacore-sdk/src/vastacore/__init__.py（导出）
- tests/test_offline_eval.py（新增：5 条）
- docs/sprint-status.yaml（8-10 状态）

## Change Log

- 2026-09-10: Story 8.10 实现完成（T1–T5 全过，475 passed +1 skipped，ruff/lint 绿）→ review
