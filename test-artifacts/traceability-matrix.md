---
stepsCompleted: ['step-01-load-context', 'step-02-discover-tests', 'step-03-map-criteria', 'step-04-analyze-gaps', 'step-05-gate-decision']
lastStep: 'step-05-gate-decision'
lastSaved: '2026-09-09'
workflowType: 'testarch-trace'
inputDocuments:
  - 'plan.md §32.1（AC-01~08 定义）'
  - 'docs/prds/prd-VastaCore-2026-09-08/prd.md（34 ★FR + SM-2）'
  - 'docs/epics.md（Epic 1–7 Story AC）'
  - 'docs/reviews/（四份 code-review 报告）'
  - 'tests/（380 collected / 379 passed + 1 skipped @ 3217cc2）'
coverageBasis: 'acceptance_criteria'
oracleConfidence: 'high'
oracleResolutionMode: 'formal_requirements'
oracleSources:
  - 'plan.md#L1773-1780'
  - 'docs/prds/prd-VastaCore-2026-09-08/prd.md'
  - 'docs/epics.md'
externalPointerStatus: 'not_used'
---

# Traceability Matrix & Gate Decision — VastaCore MVP（Stage 1）

**Target:** MVP 验收（AC-01~08 + 34 条 ★FR，Epic 1–7）
**Date:** 2026-09-09
**Evaluator:** TEA Agent（BMad）
**Coverage Oracle:** acceptance_criteria（形式化需求）
**Oracle Confidence:** high（FR/AC 全局稳定编号；PRD/蓝图/Story 三层一致）
**Oracle Sources:** `plan.md §32.1`、`docs/prds/.../prd.md`、`docs/epics.md`
**测试基线:** 388 collected → 387 passed + 1 skipped（Windows sandbox resource 限额跳过）；初评 @ `3217cc2`（380/379），复评含缺口补齐 +8 测试

> 本工作流只审计覆盖与门禁，不生成测试。缺口补齐走 `/bmad-testarch-automate` 或实现 Story。
> 覆盖状态取值：FULL / PARTIAL / NONE / UNIT-ONLY / INTEGRATION-ONLY。门禁百分比只计 FULL。

---

## PHASE 1: REQUIREMENTS TRACEABILITY

### Coverage Summary

| Priority | Total Criteria | FULL Coverage | Coverage % | Status |
| -------- | -------------- | ------------- | ---------- | ------ |
| P0（AC-01~08，MVP 出门条件） | 8 | 6 | 75.0% | ❌ FAIL（复评二 +1，仍 <100%） |
| P1（34 ★FR，Must） | 34 | 31 | 91.2% | ✅ PASS（维持） |
| P2 | 0 | 0 | N/A | N/A |
| P3 | 0 | 0 | N/A | N/A |
| **Total** | **42** | **37** | **88.1%** | ⚠️ 总量过下限；门禁由 P0 决定 |

**图例:** ✅ PASS（达标）/ ⚠️ WARN（低于目标非致命）/ ❌ FAIL（低于下限，阻断）

**P0 全部 8 条均为蓝图 §32.1「技术 MVP 验收」判据 + SM-2 出门条件；无一条 NONE——所有 PARTIAL 均为「机制已实现已测、AC 全量词/子维度未验」型。**

### Detailed Mapping — AC-01~08（P0）

#### AC-01: 至少 40 个 VastaLab/GUI 任务可运行并生成完整回放 — **FULL** ✅（复评二翻绿）

- **Tests:**
  - `EV-01` — `tests/test_evaluation.py` `TestVastaLabTasks::test_task_generation_meets_ac01_quota`【I】：默认生成 50 任务（20 主 + 20 噪声 + 10 偏差）≥40 配额
  - `EV-02` — `TestVastaLabTasks::test_ground_truth_solver` / `test_hidden_rules_present` / `test_deviation_and_noise_variants`【I】：任务可确定性运行（solve/run_agent）
  - `TL-01` — `tests/test_timeline.py` `TestTimelineProjection::test_full_coverage_and_causal_trace`【I】：时间线覆盖 Run 全部事件（AC-01 完整回放，PRD FR-060 后果条款）
  - `QS-01` — `tests/test_quickstart_e2e.py` `TestQuickstartE2E::test_full_run_with_evidence_and_causal_chain` / `test_same_run_id_and_seed_byte_identical`【E】：单环境任务全量回放 + 字节级复现
- **判定:** 复评二翻绿——Story 8.9「评测即 Run」落地：`run_tasks_as_runs` 以 `VastaLabEnv`（任务即环境，隐藏规则真实生效）+ `SolvePolicyStandIn`（确定性替身，不等真实适配器——Assumption Audit P1 修正）批量运行 50 任务（≥40），每任务完整 RunEngine 生命周期事件流（timeline 全覆盖、终局观察、复现包可离线重放、同 seed 双库逐字节一致）。GUI 形态维持 Stage 2 [ASSUMPTION] 披露（蓝图 §31）。

#### AC-02: 100% 状态改变型动作具备动作前后、契约、策略和核验链 — **FULL** ✅

- **Tests:**
  - `AC-02` 主证 — `tests/test_action_contracts.py` `TestSixSegmentChain::test_happy_path_six_segments_complete` / `test_contract_persisted_before_reference` / `test_causal_chain_intact`【I】：六段链完整 + 先落盘后引用（AD-3）+ 因果链
  - `AC-02` 审计 — `TestRejectOnIncomplete::test_rejected_chain_counts_as_rejected_in_audit` + `tests/test_epic3_review_guards.py::TestAuditSemantics`【I】：NFR-001 审计器（含 failed/pending 合法终态）
  - `AC-02` 网关路径 — `tests/test_tool_gateway.py::TestEngineGatewayPath::test_gateway_path_six_segments_and_evidence`【I】
  - `AC-02` 缺段拒绝 — `TestMissingSegments::test_each_segment_missing`（10 组参数化）【U】
- **判定:** 引擎两条执行路径（env/网关）+ 拒绝路径 + 审计闭环全部覆盖。100% 语义由「写动作唯一通道 + 清单强制分类」（AD-4）结构保证，审计器断言链完整率。

#### AC-03: 任意派生物可回链并校验原始 Artifact — **FULL** ✅

- **Tests:**
  - `DL-01` — `tests/test_derived_lineage.py` `TestSaveAndLineage::test_register_and_link_back_full_green` / `test_multi_source_lineage` / `test_idempotent_registration`【I】
  - `DL-02` — `TestVerifyDegradation` 三态（source 删除/损坏检测）+ `tests/test_lineage_guards.py` derived 侧三态【I】
  - `ES-01` — `tests/test_evidence_search.py::TestNoDeadLinks::test_all_refs_retrievable_and_hash_verified` / `test_dead_blob_raises`【I】：全部引用可取回且哈希校验
  - `IM-01` — `tests/test_image_tools.py` `test_crop_persist_derived_registers_lineage` / `test_diff_persist_derived`【I】：图像派生真实血缘打通

#### AC-04: 偏差注入测试中旧计划 100% 失效，不继续批量执行 — **FULL** ✅

- **Tests:**
  - `DR-01` — `tests/test_deviation_recovery.py` `TestPlanInvalidation::test_deviation_invalidates_plan_completely`（100% 失效主证）/ `test_invalidate_cascades_and_is_idempotent`【I】
  - `DR-02` — `TestBoundedRecovery::test_side_effect_limit_safe_stop` / `test_engine_recovery_limit_safe_stops`【I】：不继续批量执行（副作用总闸 + 恢复预算）
  - `EV-03` — `tests/test_evaluation.py::test_deviation_and_noise_variants`【U】：任务集含偏差注入变体

#### AC-05: 至少 10 个确定性任务的激活模型通过声明范围内全部历史回放 — **FULL** ✅（复评翻绿）

- **Tests:**
  - `ML-01` — `tests/test_model_lab.py` `TestValidationPipeline::test_replay_all_pass_with_approval_activatable` / `test_replay_mismatch_detected`【I】：回放全过 + 人工批准才可激活（含零重叠空转守卫 `test_replay_zero_overlap_fails`）
  - `ML-02` — `TestValidationPipeline::test_without_approval_not_activatable`【I】：激活门槛四要素
- **判定:** 机制与批量实验均 FULL。复评补 `TestAcceptanceGaps::test_batch_activation_over_ten_tasks`：单一受限 Python 模型镜像 VastaLabTask 转移语义（teleport/wind），15 个任务（≥10）各自以确定性求解器生成历史，全部回放通过 + 确定性性质测试 + 人工批准 → activatable。

#### AC-06: 网络、密钥、宿主文件和资源越权测试全部失败并有审计 — **FULL** ✅（复评翻绿）

- **Tests:**
  - `SB-01` 网络 — `tests/test_model_lab.py::TestSandbox::test_sandbox_no_network`【I】：socket 连接失败
  - `SB-02` 资源 — `test_sandbox_memory_error`（内存限额 MemoryError）+ `test_sandbox_timeout_real_clock`【I】
  - `SB-03` 宿主文件 — `test_from_import_whitelist_enforced` / `test_reflection_builtins_rejected` / `test_local_exec_builtins_restricted`（open 拒绝 + exec 无全量 builtins）【U/I】
  - `SB-04` 静态拒绝 — `test_sandbox_run_rejects_forbidden_code`【I】
- **判定:** 四维 + 审计全部 FULL。复评补三件：`SandboxExecutor.run` 静态拒绝越权代码时经 emitter 落 `incident.opened`（实现 + `test_forbidden_code_emits_incident_audit`）；`test_sandbox_env_drops_parent_credentials`（白名单式最小环境，父进程凭证不透传）；`test_env_access_paths_statically_rejected`（os/from-import/sys/__import__/file 五条环境读取通道全拒）。

#### AC-07: 自动产出六组消融、成本、置信区间和失败分类 — **PARTIAL** ⚠️

- **Tests:**
  - `AB-01` 六组 — `tests/test_evaluation.py::TestAblation::test_six_groups_all_reported` + `test_group_flags_monotone_capabilities`【U】
  - `AB-02` 成本 — `test_overhead_separately_measured`（NFR-005 平台开销单列）【U】
  - `AB-03` 失败分类 — `test_failure_breakdown_categorized`（四桶）【U】
  - `AB-04` 多种子 — `test_multi_seed_aggregation_with_stddev`【U】：成功率标准差（非置信区间）
- **判定:** 六组/成本/失败分类/切片 FULL（复评补 `run_ablation_slices`）；**仅置信区间未实现未测**（Epic 4-7 评审 defer #2，需真实任务方差定样本量）。
- **缺口:** CI 单项——WAIVER 至 Stage 2 候选。

#### AC-08: 失败复现包可在干净环境离线重放非模型事件和 verifier — **PARTIAL** ⚠️

- **Tests:**
  - `RB-01` — `tests/test_timeline.py` `TestReproBundle::test_export_and_offline_replay`（bundle 导出 + 逐条 schema 校验级重放，无 store 依赖）+ `test_unknown_run_rejected`【I】
  - `RB-02` — `TestReviewGuards::test_replay_skips_model_exchange_refs`【U】：非模型事件过滤（重放不重新调用模型）
  - `RB-03` — `test_regression_task_contract_in_protocols`【U】：回归任务契约（AD-1）
  - `RB-04` — 复现包配置快照含 budget/seed/policy/契约引用（FR-063 还原要件）
- **判定:** 非模型事件离线重放 FULL（字节级输入、零存储依赖、模型交换跳过）；**verifier 未随包重执行**——`replay_non_model_events` 仅做信封校验级重放，核验器重执行不在断言内。
- **缺口:** 复现包重放时对所载核验器结果的重放断言（或 Story 4.4 已按「最小验证」降级——需用户裁决 WAIVER）。

### Detailed Mapping — 34 ★FR（P1，紧凑表）

| FR | 一句话 | 覆盖 | 关键测试（级别） |
|----|--------|------|------------------|
| FR-001 | 版本化五协议 | FULL ✅ | `test_contract_suites.py` 信封/日志/Fake×5 契约（U）；`test_workspace.py::test_protocols_surface`（U） |
| FR-004 | Run 生命周期+检查点+预算 | FULL ✅ | `test_run_engine.py` TestStateMachine/TestCausalChain/TestBudgetSafeStop/TestPauseResume（I）；`test_review_fixes.py` 暂停计费/升级检查点（I） |
| FR-005 | 五类 Observation | FULL ✅ | `test_observation_collection.py` TestFiveKindCollection/TestTerminalGuard/TestActionableInvariant（I） |
| FR-010 | 原始观察/工具响应全存 | FULL ✅ | `test_runcontext_determinism.py::TestModelExchangeArtifact`（I）；`test_tool_gateway.py::test_gateway_path_six_segments_and_evidence`（I） |
| FR-011 | Artifact 七字段元数据 | FULL ✅ | `test_sqlite_storage.py::test_artifact_roundtrip_verified_by_hash`（含 retention="90d" 回读断言，L55-62）（I）；TestShardedCas 去重（I） |
| FR-012 | 派生回链 | FULL ✅ | `test_derived_lineage.py` 全族（I） |
| FR-013 | 六维检索 | PARTIAL ⚠️ | `test_evidence_search.py` 时间/事件/动作(payload_equals)/区域(scope)（I）；artifact tags/source/classification + refs join（I）。**业务实体维度无实体索引/别名**（通用 payload 等值可覆盖其字段） |
| FR-014 | 图像 inspect/crop/pixel/diff | FULL ✅ | `test_image_tools.py` 17 条（I）：溯源/越界/面积上限/血缘 |
| FR-020 | 九类认知（MVP 四类） | FULL ✅ | `test_cognition.py` 全族（I）；九类 Literal 封闭 + `MVP_MEMORY_TYPES` 四类（PRD 认可切分） |
| FR-021 | Claim 七字段 | FULL ✅ | `test_cognition.py::TestReviewGuards::test_version_increments_on_transitions`（评审后补版本）+ lifecycle（I） |
| FR-022 | 七种主张操作 | PARTIAL ⚠️ | 创建/支持/接受/争议/推翻/退役 + 存在性/终态守卫（I）。**修订(revise)/晋升(promote)为近似语义（support/accept）、缩小范围(narrow)无实现** |
| FR-023 | 显式 Conflict | FULL ✅ | `TestConflict` + 幂等/事件化守卫（评审后）（I） |
| FR-024 | 依赖失效标记 Plan 与资产 | PARTIAL ⚠️ | 级联 refuted（穿透/环护）+ world_model.suspended 桥接（I）。**claim 失效不标记受影响 Plan**（计划失效仅由偏差路径驱动，FR-037） |
| FR-025 | ContextBuilder 四维 | FULL ✅ | `TestContextBuilder` + relevance/risk 守卫（评审后）（I） |
| FR-030 | 写动作契约前置 | FULL ✅ | `test_action_contracts.py` TestRejectOnIncomplete（I） |
| FR-031 | 契约六要素 | FULL ✅ | TestMissingSegments 10 参数化 + `test_action_contracts.py::test_required_segments_constant_matches`（U） |
| FR-032 | 工具清单声明 | FULL ✅ | `test_tool_gateway.py::test_manifest_incomplete_rejected_at_construction` + TestRegistrationAndClassification（I） |
| FR-033 | 策略四态 | FULL ✅ | `test_policy_engine.py` 13 条：默认映射/R3 批准/降级/fail-closed（I） |
| FR-035 | 自动观察+组合核验 | FULL ✅ | `test_combined_verification.py` TestPipeline/TestEngineEndToEnd（I） |
| FR-036 | 核验四态 | FULL ✅ | Schema/ReadBack/Invariant 三核验器含 5 类 inconclusive 守卫（I） |
| FR-037 | 偏差→失效+有界恢复 | FULL ✅ | `test_deviation_recovery.py` TestPlanInvalidation/TestFaultClassification/TestBoundedRecovery（I） |
| FR-040 | Meta 决策留痕 | FULL ✅ | `test_rules` + `test_meta_decision_emits_event` + STOP 可达（评审后）（I） |
| FR-041 | DSL+受限 Python | FULL ✅ | `test_model_lab.py` TestModelInterface + sandbox 接线（评审后）（I） |
| FR-043 | 模型清单声明 | FULL ✅ | `test_manifest_declares_unknown` + 必填守卫（评审后）（U/I） |
| FR-044 | 验证流水线 | FULL ✅ | TestValidationPipeline 3 条 + 零重叠守卫（I） |
| FR-046 | 沙箱四约束 | FULL ✅ | TestSandbox 4 条 + 静态/超时事件/最小环境守卫（评审后）（I） |
| FR-047 | 规划五约束 | FULL ✅ | TestPlanner 5 条：depth/nodes/time/**cost（评审后生效）**（U） |
| FR-048 | 现实逐步核验 | FULL ✅ | `test_stepwise_real_verification_hook` + FR-037 引擎集成（I） |
| FR-052 | 人工控制四操作 | FULL ✅ | `test_human_control.py` 11 条 + `test_epic3_review_guards.py` 批准安全（I） |
| FR-053 | Supervisor 三检 | FULL ✅ | `test_supervisor.py` 11 条：循环/连续偏差/预算协调（I） |
| FR-060 | 完整因果时间线 | FULL ✅ | `test_timeline.py` 覆盖/纯度/外部变化/render（I）+ HTML 转义守卫 |
| FR-062 | 复现包+回归任务 | FULL ✅ | TestReproBundle + 契约上移守卫（I）（verifier 重执行同 AC-08 备注） |
| FR-063 | 评测配置七要素固化 | FULL ✅ | `test_config_complete_and_reproducible` + 跨进程种子稳定（评审后）（U） |
| FR-064 | 消融五要素 | FULL ✅（复评翻绿） | 六组/多种子/成本/失败分类 + **切片**（`run_ablation(task_ids=)` 子集 + `run_ablation_slices` 维度切分，`TestAblationSlicing` 4 条：按隐藏规则/按变体/子集校验/逐族净增益） |

---

## PHASE 2: GAP ANALYSIS（9 个缺口，全部实码核实）

| # | 缺口 | 类型 | 风险(P×I) | 可否纯测试补齐 |
|---|------|------|-----------|----------------|
| 1 | AC-01 评测任务不产生 Run 事件流回放（评测即 Run defer #1） | 实现缺口 | 3×3=9 | ❌ 需实现（Stage 2 适配器）或 MVP 内批量演示 Run |
| 2 | AC-05 ≥10 任务批量激活实验缺测试 | 测试缺口 | 2×3=6 | ✅ 纯测试 |
| 3 | AC-06 密钥不可达断言缺测试 | 测试缺口 | 2×3=6 | ✅ 纯测试 |
| 4 | AC-06 越权「有审计」无事件断言 | 实现缺口（轻） | 2×3=6 | 半（先落 incident 事件再测） |
| 5 | AC-07 置信区间（评审 defer #2） | 实现缺口 | 2×2=4 | ❌ WAIVER 至 Stage 2（需真实方差） |
| 6 | AC-07/FR-064 切片 | 实现缺口（轻） | 2×2=4 | 半（run_ablation 加切片参数，低成本） |
| 7 | AC-08 verifier 随包重执行 | 语义裁决 | 2×2=4 | 需用户裁决：补实现 or WAIVER（Story 4.4 按「最小验证」交付） |
| 8 | FR-022 revise/promote/narrow 算子 | 实现缺口 | 2×2=4 | ❌ WAIVER 至 Stage 2 或补 Story |
| 9 | FR-013 业务实体维度 / FR-024 claim→Plan 标记 | 实现缺口 | 1×2=2 / 2×2=4 | ❌ WAIVER 或补 Story |

**风险治理要求：分数 ≥6 需文档化缓解；=9 强制门禁失败。** 缺口 #1（9 分）单独即构成 FAIL 依据；#2/#3/#4（6 分）需缓解后复评。

**正向结论：** 34/34 ★FR 均有机制级测试（无一条 NONE）；33/42 FULL；四轮 code-review 累计 ~124 项修复全部有守卫测试锚定。缺口集中在**AC 全量词（≥40/≥10/100%）的批量验证**与**蓝图 Stage 2/3 范围的前置字段**，而非已实现功能的覆盖缺失。

---

## 🚨 GATE DECISION: **FAIL**（MVP 出门条件未全满足）

📊 **Coverage Analysis:**
- P0 Coverage: **37.5%**（Required: 100%）→ ❌ FAIL
- P1 Coverage: **88.2%**（PASS 目标 90%，下限 80%）→ ⚠️ WARN
- Overall Coverage: **78.6%**（下限 80%）→ ❌ FAIL

✅ **Decision Rationale:**
SM-2 要求「MVP 验收 AC-01~08 全通过」。当前 3/8 FULL：AC-02/03/04（可信执行、派生回链、偏差失效——平台核心可靠性主张）全量验证；AC-01/05/06/07/08 为 PARTIAL，其中仅缺口 #2/#3 可纯测试补齐（约 2 个测试文件可翻 AC-05、AC-06 大半），#1（评测即 Run）是结构性 defer，#5/#7/#8 属 Stage 2/3 范围。门禁按确定性规则判 FAIL：**不允许以「机制在」替代「判据过」**——这正是本工作流存在的意义（测试 379 绿 ≠ 验收过）。

📝 **Recommended Actions（按性价比排序）:**
1. **补 3 个测试翻 2.5 条 AC**（半天）：AC-05 批量激活实验（≥10 任务回放全过）；AC-06 密钥不可达断言；AC-06 越权落审计事件（配合 ~10 行实现）
2. **切片实现 + 测试**（半天）：`run_ablation(groups=..., task_slice=...)` → 翻 FR-064 与 AC-07 一半
3. **WAIVER 决议**（用户裁决）：AC-07 置信区间（→Stage 2）、AC-08 verifier 重执行（Story 4.4 语义）、FR-022 三算子、FR-013 实体维度、FR-024 Plan 标记——每项按风险治理需 owner + 到期日；豁免后重跑本工作流复评门禁
4. **AC-01 结构项**：Stage 2 模型适配器落地时以 RunEngine 批量跑 VastaLab 任务集（接 defer #1）

📂 Full Report: `test-artifacts/traceability-matrix.md`


---

## 复评记录（2026-09-09，缺口补齐后）

**变更:** 按初评行动项 1/2 补齐——AC-05 批量激活实验、AC-06 密钥断言 + 越权审计事件（含 ~10 行 `incident.opened` 发射实现）、FR-064 切片（`run_ablation(task_ids=)` + `run_ablation_slices`）。+8 测试（380→388 collected，全绿；ruff/import-linter 通过）。

| 判据 | 初评 | 复评 | 依据 |
|------|------|------|------|
| AC-05 | PARTIAL | **FULL** | `test_batch_activation_over_ten_tasks`：15 任务全回放 + 性质 + 批准 → activatable |
| AC-06 | PARTIAL | **FULL** | `test_forbidden_code_emits_incident_audit` / `test_sandbox_env_drops_parent_credentials` / `test_env_access_paths_statically_rejected` |
| AC-07 | PARTIAL（CI+切片） | PARTIAL（仅 CI） | 切片翻绿；置信区间维持 WAIVER 候选 |
| FR-064 | PARTIAL | **FULL** | `TestAblationSlicing` 4 条 |

**复评覆盖:** P0 5/8（62.5%）· P1 31/34（91.2% ✅）· Overall 36/42（85.7%）

## 🚨 GATE DECISION（复评）: **FAIL → 维持 FAIL，缺口收敛**

- P0 62.5%（需 100%）→ 仍 FAIL；但剩余 P0 缺口由 5 个收敛为 3 个，且全部为**结构性/裁决项**而非可补测试项：
  1. **AC-01** 评测任务 × Run 事件流（「评测即 Run」，需 Stage 2 模型适配器——实现级 defer）
  2. **AC-07** 置信区间（需真实任务方差，Stage 2 WAIVER 候选）
  3. **AC-08** verifier 随包重执行（Story 4.4「最小验证」语义，WAIVER 或补实现——用户裁决）
- P1 翻 PASS（91.2%）；P1 剩余 PARTIAL 三条（FR-013/022/024）均为蓝图 Stage 2/3 范围 WAIVER 候选。
- **下一步即 WAIVER 决议**：6 项豁免（上列 3 项 P0 + 3 项 P1）经 owner + 到期日豁免后，重跑本工作流——豁免项不计分母，门禁可达 PASS。


---

## 复评记录二（2026-09-09，Story 8.9 评测即 Run 落地后）

**变更**: Story 8.9（Assumption Audit P1 修正的执行）——`run_tasks_as_runs` 以替身模型批量运行 VastaLab 任务集，评测任务与真实 Run 同构。+5 测试（470 全绿）。

| 判据 | 复评一 | 复评二 | 依据 |
|------|--------|--------|------|
| AC-01 | PARTIAL | **FULL** | `tests/test_eval_as_run.py`：50 任务批量全成功、逐 run timeline 全覆盖 + 终局观察、复现包离线重放数=事件数、同 seed 双库逐任务归一化流一致、模型交换逐步入 CAS |

**复评覆盖:** P0 6/8（75.0%）· P1 31/34（91.2% ✅）· Overall 37/42（88.1%）

## 🚨 GATE DECISION（复评二）: **FAIL → 维持 FAIL，P0 缺口收敛为 2**

- 剩余 P0 缺口：AC-07（置信区间——需真实任务方差，WAIVER 至 Stage 2 后半）、
  AC-08（verifier 随包重执行——Story 4.4「最小验证」语义，WAIVER 或补实现）。
- 「评测即 Run」结构性缺口（原 9 分风险项）就此关闭；Epic 4-7 评审 defer #1 落地。
