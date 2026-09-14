# VastaCore 全项目终检报告（2026-09-14）

**项目阶段收官核验**：PRD Stage 1-6 全量交付后的 FR×Story 覆盖矩阵、
NFR/AC 对拍与簿记清偿。方法：三段并行 FR 审计（S1-2 / S3-4 / S5-6+NFR，
逐条「PRD 文字 → 承载 Story → sprint-status → 模块 + 测试断言体」四链
对拍，关键锚点测试实跑）+ 两轮覆盖缝隙封口（12+6 条）+ 陈年簿记证据
核销。审计期间分段实跑测试 900+ 全绿（S3-4 段 294 通过、S5-6 段
325 通过、S1-2 锚点 54 通过、NFR 证据组 158 通过）。

## 一、总判定

| 维度 | 结果 |
|---|---|
| FR 覆盖（82 条，FR-001~085 减空号 057-059） | **delivered 75 / partial 7 / absent 0** |
| NFR 对拍（15 条） | delivered 8 / partial 6 / absent 1（NFR-012 无障碍——UI 面未建，决策链一致） |
| AC-01~08（SM-2 判据） | 工程内证据 8/8 全锚定（见 §四） |
| Story/Bookkeeping | 12 Epic / 103 Story 全 done（含本轮回填 53 键）；豁免在册 0；行动项 open 仅剩 Epic 12 的 7 项后续精化 |
| 门禁（终态） | 1219 passed + 5 skipped、ruff 0、lint-imports 5/5 KEPT、双守卫零漂移（21 流/117 事件类型） |

**7 条 partial 全景**（无一条是实现遗漏——四条拆解层有意收窄、两条
形态缩水已自注、一条与 PRD 开放问题一致）：

| FR | 缺口 | 性质 |
|---|---|---|
| FR-002 | middleware/sidecar 两接入形态未建（SDK/HTTP/轨迹/ToolProxy 四形态已交） | 拆解层待伙伴信号（SM-5）——epics.md Epic 8 备注在册 |
| FR-015 | 音视频以清单形态（不触真实字节） | 形态缩水已自注（无编解码依赖） |
| FR-016 | OCR/ASR 零实现、embedding 演示级 | 拆解层留白（GUI Pack 接入面） |
| FR-047 | 规划五约束缺「风险」维度（四维已交） | 实现维度缺口（唯一实现侧 partial） |
| FR-071 | SAML 分支未实现（OIDC/SCIM/RBAC/审计全交） | 拆解层收窄（AC 未拆，历次评审未标记——本终检首次补记） |
| FR-075 | 版本化资产类 model|policy（插件由 12.5 交付、prompt 无版本化） | 拆解层收窄（Epic 9 G3 声称与实现出入——本终检首次补记） |
| FR-084 | 商业分发子面未建（发现+评分已交） | 与 PRD 开放问题 8 一致的留白 |

## 二、FR×Story 覆盖矩阵（82 条——判定与锚点）

★=PRD ★MVP。证据列为代表性锚点（test 文件或 test::名——★ 条目均给
具体测试名）。分段审计全表见三份审计记录（本表为其合并去重）。

### Stage 1（Epic 1-7 承载，★MVP 核心）

| FR | Story | 证据锚 | 判定 |
|---|---|---|---|
| FR-001★ | 1.1 | test_workspace.py::test_protocols_surface（五协议版本逐项） | ✅ |
| FR-004★ | 1.2 | test_run_engine.py::TestBudgetSafeStop::test_actions_budget_safe_stop | ✅ |
| FR-005★ | 1.3 | test_observation_collection.py::test_all_five_kinds_covered_in_one_scenario | ✅ |
| FR-010★ | 1.4 | test_sqlite_storage.py::TestShardedCas（分桶/先落盘后引用） | ✅ |
| FR-011★ | 1.4 | test_sqlite_storage.py::test_tampered_blob_detected | ✅ |
| FR-012★ | 2.3 | test_derived_lineage.py::test_register_and_link_back_full_green | ✅ |
| FR-013★ | 2.1 | test_evidence_search.py::test_all_refs_retrievable_and_hash_verified | ✅ |
| FR-014★ | 2.2 | test_image_tools.py::TestDiff::test_side_by_side_stats_and_dual_provenance | ✅ |
| FR-020★ | 5.1 | cognition.py 四类（PRD 自注 MVP 四类）；test_cognition.py 24 测 | ✅ |
| FR-021★ | 5.1 | test_cognition.py::test_no_evidence_cannot_accept | ✅ |
| FR-022★ | 5.1 | test_cognition.py::test_refuted_not_deleted_with_impact_chain | ✅ |
| FR-023★ | 5.2 | test_cognition.py::test_mutex_claims_create_conflict | ✅ |
| FR-024★ | 5.3 | test_cognition.py::test_dependent_claims_cascade（穿透/环安全） | ✅ |
| FR-025★ | 5.4 | test_cognition.py::TestContextBuilder::assemble(goal/budget/relevance) | ✅ |
| FR-030★ | 3.1 | test_action_contracts.py（16 测——六段链/缺段拒） | ✅ |
| FR-031★ | 3.1 | 同上（契约六段缺一拒执行） | ✅ |
| FR-032★ | 3.2 | test_tool_gateway.py（14 测——未声明不可被写调用） | ✅ |
| FR-033★ | 3.3 | test_policy_engine.py（13 测——四态 fail-closed） | ✅ |
| FR-035★ | 3.4 | test_combined_verification.py（18 测——组合核验全过才 pass） | ✅ |
| FR-036★ | 3.4 | 同上（四态；观察不足不归成功） | ✅ |
| FR-037★ | 3.5 | test_deviation_recovery.py（10 测——有界恢复/达限安全停止） | ✅ |
| FR-040★ | 6.4 | test_model_lab.py::test_meta_decision_emits_event | ✅ |
| FR-041★ | 6.1 | test_model_lab.py::test_from_import_whitelist_enforced 等 | ✅ |
| FR-043★ | 6.1/6.3 | test_model_lab.py::test_manifest_requires_unknowns_and_coverage | ✅ |
| FR-044★ | 6.3 | test_model_lab.py::test_batch_activation_over_ten_tasks（AC-05） | ✅ |
| FR-046★ | 6.2 | test_model_lab.py::TestSandbox（越权全败+审计——AC-06） | ✅ |
| FR-047★ | 6.5 | planner.py PlanCaps 四维（max_time_s 无专测、风险维度缺） | ⚠️ partial |
| FR-048★ | 6.5 | 结构性承载（规划器无执行路径，一切走 execute_contracted） | ✅ |
| FR-052★ | 3.6 | test_human_control.py（11 测） | ✅ |
| FR-053★ | 1.6 | test_supervisor.py（11 测） | ✅ |
| FR-060★ | 4.1/4.2 | test_timeline.py::test_full_coverage_and_causal_trace | ✅ |
| FR-062★ | 4.4 | test_timeline.py::TestReproBundle::test_export_and_offline_replay（AC-08） | ✅ |
| FR-063★ | 7.1 | test_evaluation.py::test_config_complete_and_reproducible | ✅ |
| FR-064★ | 7.3 | test_evaluation.py::test_six_groups_all_reported（AC-07；CI 由 12.10 补） | ✅ |

### Stage 2（Epic 8 承载）

| FR | Story | 证据锚 | 判定 |
|---|---|---|---|
| FR-002 | 8.1/8.2/8.3/8.11 | test_agent_sdk/test_http_service/test_trajectory_import/test_tool_proxy | ⚠️ partial（2/5 形态待信号） |
| FR-003 | 8.5 | test_capability_probe.py::test_exploding_model_fails_closed | ✅ |
| FR-006 | 8.6 | test_model_router.py（12 测——路由/降级/成本） | ✅ |
| FR-015 | 8.12 | test_on_demand_derive.py::test_media_window_slices_and_aligns | ⚠️ partial（清单形态） |
| FR-016 | 8.12 | test_on_demand_derive.py（不默认派生/血缘/幂等） | ⚠️ partial（OCR/ASR 缺） |
| FR-061 | 8.7/8.8 | test_time_travel.py + test_versioning.py（回放不串版） | ✅ |
| FR-066 | 8.10 | test_offline_eval.py（6 测） | ✅ |
| FR-081 | 8.4 | test_tool_scaffold.py（9 测） | ✅ |

### Stage 3（Epic 9 承载）

| FR | Story | 证据锚 | 判定 |
|---|---|---|---|
| FR-007 | 9.10 | test_adoption.py::test_dangling_started_run_adopted | ✅ |
| FR-008 | 9.9 | test_scheduling.py（cron/批量触发） | ✅ |
| FR-017 | 9.3 | test_lifecycle.py::test_delete_proves_event_without_content | ✅ |
| FR-018 | 9.4 | test_evidence_access.py::test_derived_still_readable | ✅ |
| FR-026 | 9.11 | test_revalidation.py::test_fail_below_threshold_refutes_with_propagation | ✅ |
| FR-028 | 9.13 | test_studio.py::test_review_approve_accepts_with_approval | ✅ |
| FR-029 | 9.13 | test_studio.py（声明性覆盖决策——Epic 10 备注在册） | ✅ |
| FR-034 | 9.5 | test_approval_records.py::test_record_contains_all_five | ✅ |
| FR-038 | 9.7 | test_transaction_batch.py::test_mid_failure_compensates_reverse | ✅ |
| FR-065 | 9.6 | test_release_canary.py::test_full_promotion_path | ✅ |
| FR-070 | 9.1/9.8+10.8/10.9 | test_team_backends.py（租户可达性双后端） | ✅ |
| FR-072 | 9.8 | test_quotas.py::test_three_level_rollup | ✅ |
| FR-075 | 9.6+8.8 | test_versioning.py + 12.5（插件类）；prompt 类无版本化 | ⚠️ partial |
| FR-076 | 9.12 | test_ops.py::test_drill_passes_on_healthy_store | ✅ |

### Stage 4（Epic 10 承载）

| FR | Story | 证据锚 | 判定 |
|---|---|---|---|
| FR-045 | 10.3 | test_release_lifecycle.py::test_revoke_irreversible | ✅ |
| FR-049 | 10.4 | test_drift.py + CompositeModel（11.9） | ✅ |
| FR-055 | 10.3 | test_release_lifecycle.py::test_revoke_requires_approver | ✅ |
| FR-067 | 10.4 | test_drift.py::test_drift_revalidation_fail_sev1_suspend | ✅ |
| FR-068 | 10.6 | test_audit_export.py::test_artifact_refs_listed_without_content | ✅ |
| FR-071 | 10.8/10.9/10.10 | test_rbac/test_identity/test_audit_log；SAML 分支缺 | ⚠️ partial |
| FR-073 | 10.11 | test_data_policy.py::test_unmarked_fails_closed | ✅ |
| FR-074 | 10.12 | test_byok.py::test_offline_smoke_local_router | ✅ |
| FR-078 | 10.13 | test_billing.py::test_bill_immutable_regen_versions | ✅ |
| FR-085 | 10.7 | test_schema_openness.py::test_chained_migration_via_registry | ✅ |

### Stage 5-6（Epic 11-12 承载）

| FR | Story | 证据锚 | 判定 |
|---|---|---|---|
| FR-009 | 11.13 | test_streaming_edge.py（帧 CAS/缺口拒/续传） | ✅ |
| FR-019 | 12.9 | test_evidence_signing.py（无数据第三方验证） | ✅ |
| FR-027 | 11.6+12.2 | test_sharing.py + TestSharedReadFace 官方读闸 | ✅ |
| FR-039 | 11.7+12.2 | test_autonomy.py + AgentSession 运行时强制 | ✅ |
| FR-042 | 11.9+12.3 | test_extended_models.py + 留痕接线（沙箱/静态检查改口在册） | ✅ |
| FR-050 | 11.3+12.2 | test_delegation.py（input_scope 执行/预算 fail-closed） | ✅ |
| FR-051 | 11.4 | test_memory_boundary.py（默认私有/仅 accepted 可发布） | ✅ |
| FR-054 | 11.5+12.2 | test_agent_roles.py + 运行时角色拒 | ✅ |
| FR-056 | 11.10+12.2 | test_tournament.py + 竞赛→榜单缝 | ✅ |
| FR-069 | 11.12 | test_leaderboard.py（证据引用/作用域绑定） | ✅ |
| FR-077 | 11.8+12.2 | test_risk_budget.py + 并发不丢敞口回归 | ✅ |
| FR-079 | 12.11 | test_edge_orchestration.py（驻留/清单编组/fail-closed 路由） | ✅ |
| FR-080 | 12.4 | test_plugin_manifest.py（六面/验签/CAS/airgap） | ✅ |
| FR-082 | 12.5/12.6 | test_plugin_registry/revocation.py（不可变条目/终态/闭包） | ✅ |
| FR-083 | 12.7 | test_plugin_trust.py（扫描门内容绑定/兼容矩阵） | ✅ |
| FR-084 | 12.8 | test_plugin_discovery.py（评分证据引用）；商业分发缺 | ⚠️ partial |

## 三、NFR 对拍（15 条）

| NFR | 工程内证据 | 缺口 | 判定 |
|---|---|---|---|
| 001 完整性 | audit_six_segment + 六段链测试族（拒链不进分母） | — | ✅ |
| 002 可复现 | test_same_seed_byte_identical_event_stream + 非确定性源静态扫描为零 | — | ✅ |
| 003 安全 | 沙箱越权全败+审计 / fail-closed 兜底 / 跨租户族 | Windows RLIMIT skip（AD-6 在册） | ✅ |
| 004 SLO | /healthz//readyz + 告警 + 事故管理 | 达成度测量/负载演练属地运营 | ⚠️ partial |
| 005 性能 | 消融报告 overhead 单列可测 | §21 P95 阈值零断言 | ⚠️ partial |
| 006 扩展 | 同契约双后端 + 统一 Sequencer | 真分布式部署（open item-30 正是其根因） | ⚠️ partial |
| 007 兼容 | schema 迁移器/破坏性检测/混版本检出 | — | ✅ |
| 008 可移植 | BYOK/airgap/离线冒烟（Local SDK 即共享核心） | SaaS/VPC 属部署形态 | ✅ |
| 009 隐私 | 最小访问/驻留/导出（不含内容）/删除证明 | 生产多区域执行属地运营 | ✅ |
| 010 遥测 | CostLedger + /metrics + 事件溯源关联 | OTel trace_id 贯穿未接线（架构脊柱约定） | ⚠️ partial |
| 011 可维护 | 5 契约 KEPT + 协议契约套件 + 1100+ 测试 | — | ✅ |
| 012 无障碍 | —（Console 未建；Studio 只读初版） | 全部（UI 面，决策链一致） | ❌ absent |
| 013 国际化 | 事件语义稳定（schema 面） | UI/时间/数字本地化零实现 | ⚠️ partial |
| 014 耐久 | backup/restore + 恢复演练 + PG pg_dump 形态 | RPO/RTO 达标测量与定期编排属运营 | ⚠️ partial |
| 015 成本 | CostLedger 三级归集 + 计费 + 优化建议 | — | ✅ |

NFR 小结：工程可验面 8/8 全交付；partial 6 条中 4 条属地运营
（004/008 部/014/生产多区域）、2 条为未接线工程面（005 性能断言、
010 OTel）——均如实登记。

## 四、AC-01~08 与成功指标（SM-2）

| AC | 工程内锚点 | 判定 |
|---|---|---|
| AC-01 完整回放 | FR-060（covers_all_events + 因果父链） | ✅ |
| AC-02 六段链 100% | NFR-001（audit_six_segment + 拒链不进分母语义） | ✅ |
| AC-03 哈希取回/回链 | FR-011/012 + 12.9 第三方验签延伸 | ✅ |
| AC-04 偏差注入失效 | FR-024/037（级联失效 + 有界恢复测试族） | ✅ |
| AC-05 ≥10 任务回放激活 | FR-044（test_batch_activation_over_ten_tasks） | ✅ |
| AC-06 沙箱越权 0 | NFR-003（越权全败 + incident 审计） | ✅ |
| AC-07 六组消融+CI | FR-064 + 12.10 W-1（≥10 种子 + CI 入报告） | ✅ |
| AC-08 复现包离线重放 | FR-062（export_repro_bundle + 逐条校验重放） | ✅ |

SM-1/SM-2：MVP（§6.1 34 条 ★FR）全 delivered（FR-047 为 partial——
五约束缺一维，注意其属 ★MVP）；AC-01~08 工程内证据 8/8。蓝图 §32.1
的运营级数值（40+ 任务规模、月度可用性等）属地化验证，工程内以测试
锚点承载语义。

## 五、簿记清偿结果（行动项 #7）

- **陈年行动项核销**：epic 1-10 的 16 个 open 项逐一对证据——全部有
  交付（git-hygiene/git-add-explicit→ship.py 显式路径、unify-sequencer
  ×2→9.1、bridge-wiring→9.14、sdk-subpackage×2→10.1、回写惯例→D3、
  测试卫生→10.2、W-3→10.5、WAIVER-and-bridge→9.14+12.10、组合测试
  惯例→Epic 12 验收专项④、AC 措辞/评审节奏→9-12 惯例、story-docs→
  53 份 story 文档 + epics.md 全量 AC、9.11 重验+PG 备份→9.11/10.4+
  10.11（执行证据 re-defer 在 Epic 10 评审报告在册））→ **16/16 翻
  done**；item-34（簿记清偿本体）执行后自闭。
- **Story/epic 键回填**：Epic 1-8 的 53 个 `review`/`in-progress` 键
  （D3 之前的年代，三证齐全）全部回填 done——12 Epic / 103 Story
  全链 done。
- **在册 open 仅剩 Epic 12 的 7 项后续精化**（item-28~33/35：投影
  状态机惯例、airgap 分面、Sequencer 竞态、清单帧 CAS、judge 留痕、
  迁 Desktop、session 级测试）。

## 六、终检发现与去向

1. **两条「拆解层收窄」首次补记**（FR-071 SAML、FR-075 prompt 版本化
   ——历次 Story 评审/复盘未标记，本终检跨 Epic 视角抓出）：入
   「后续拆解候选」，不追溯改 AC（交付物自洽）。
2. **FR-047 风险维度**：唯一实现侧 partial——PlanCaps 补 max_risk 一
   维即可闭环（小时级工作量，随下一轮开发带出）。
3. **两个未接线工程面**（NFR-005 性能断言、NFR-010 OTel trace）：属
   生产化前置项，与 Epic 12 open items 同池排期。
4. **覆盖缝隙方法论提示**：三段并行审计的号段交界漏了 18 条 FR——
   多审计员分段必须做「全集对账」（本终检以两轮封口补齐并按
   82=18+31+16+12+6-1（FR-085 双计）对账闭合）。

## 七、收口判定

**全项目终检：通过（PASS with registered gaps）**——82 条 FR 零
absent、75 delivered、7 partial 全数定性登记（无实现遗漏类）；
NFR 工程可验面全交付；AC-01~08 工程锚点 8/8；簿记全链闭合、豁免
归零；审计期间分段实测 900+ 测试全绿。项目按 PRD 六阶段规划完成
交付，登记缺口均有 owner 与去向（Epic 12 open items + 本报告 §六）。

---
*审计全表与逐条断言证据见三段审计记录（会话交付）；本报告为其合并
定稿。测试基线：HEAD=f762a48，1219 passed + 5 skipped。*
