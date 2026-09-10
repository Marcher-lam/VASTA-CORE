---
stepsCompleted: [step-01-validate-prerequisites, step-02-design-epics, step-03-create-stories, step-04-final-validation]
incrementalRuns:
  - date: 2026-09-09
    scope: 'Epic 8（Stage 2）增量展开：13 Story（G1-G5 + 并行技术债）；Party Mode 评审 + Assumption Audit 三项修正吸收'
    status: final-validation-passed
  - date: 2026-09-10
    scope: 'Epic 9（Stage 3）增量展开：14 Story（G1-G6）；带入复盘 B1/B5、WAIVER W-1/W-2/W-4 解除条件、NFR-015 接线'
    status: final-validation-passed
inputDocuments: ['docs/prds/prd-VastaCore-2026-09-08/prd.md', 'docs/architecture/architecture-VastaCore-2026-09-08/ARCHITECTURE-SPINE.md', 'plan.md']
---

# VastaCore - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for VastaCore, decomposing the requirements from the PRD and Architecture spine into implementable stories. 首轮拆解以 **MVP（Stage 0–1，34 条 ★MVP FR）为深度覆盖目标**；2026-09-09 增量展开 Epic 8（Stage 2）；其余 Stage 记录到 Epic 级待启动（[[ASSUMPTION] 用户指令"重点覆盖 MVP"，后续阶段到时再拆）。无 UX 设计契约（MVP 无 UI；Console/Domain Studio 属 Stage 2+，届时需先跑 bmad-ux）。

## Requirements Inventory

### Functional Requirements

*来源：PRD §4（FR-001～085，编号/优先级/阶段沿用；★=MVP；FR-057～059 为蓝图遗留空号）。*

- ★FR-001【Must·S1】版本化 Model/Environment/Tool/Storage/Verifier 五协议
- FR-002【Must·S2】SDK、HTTP、middleware、proxy、sidecar 五种接入
- FR-003【Must·S2】模型能力自动探测
- ★FR-004【Must·S1】Run 启动/暂停/恢复/取消/检查点/预算（超限安全停止+复现包）
- ★FR-005【Must·S1】决策/过渡/终局/重置/外部五类 Observation
- FR-006【Must·S2】模型路由/超时/重试/熔断/降级/成本记录
- FR-007【Should·S3】长任务跨进程/节点恢复
- FR-008【Should·S3】定时/事件触发/批量 Run
- FR-009【Could·S5】流式环境与边缘协同
- ★FR-010【Must·S1】全量保存关键原始观察与工具原始响应（before/after 缺失率 0）
- ★FR-011【Must·S1】Artifact 哈希/来源/类型/大小/时间/分类/保留策略（按哈希校验取回）
- ★FR-012【Must·S1】派生物回链源 Artifact/变换/版本
- ★FR-013【Must·S1】时间/动作/事件/区域/对象/业务实体多维检索（无死链）
- ★FR-014【Must·S1】图像 inspect/crop/pixel read/并排 Diff
- FR-015【Should·S2】视频时间窗/音频片段/多模态对齐
- FR-016【Should·S2】按需 OCR/ASR/摘要/状态抽取/embedding
- FR-017【Must·S3】热温冷/法律保留/删除请求/删除证明
- FR-018【Must·S3】原始证据权限独立于派生物
- FR-019【Could·S6】证据签名与第三方验证
- ★FR-020【Must·S1】九类认知（MVP 交付 Working/Hypothesis/Guide/Counterexample 四类；Policy 对 Agent 只读）
- ★FR-021【Must·S1】Claim 含范围/证据/反例/依赖/置信度/版本/状态（缺证据不得 accepted）
- ★FR-022【Must·S1】创建/修订/晋升/争议/缩范围/推翻/退役（推翻不删除留影响链）
- ★FR-023【Must·S1】互斥主张显式 Conflict 不静默覆盖
- ★FR-024【Must·S1】依赖主张失效标记受影响 Plan（偏差注入 100% 失效）
- ★FR-025【Must·S1】Context Builder 按目标/相关性/风险/预算装配（可追溯、不静默截断）
- FR-026【Should·S3】环境升级批量重验证与认知衰减
- FR-027【Must·S5】跨 Agent/项目/组织共享显式发布
- FR-028【Should·S3】领域专家审核与影响分析（Domain Studio）
- FR-029【Could·S4】认知图查询与可视化
- ★FR-030【Must·S1】写动作前置 ActionContract（六段链 100%）
- ★FR-031【Must·S1】契约含前置/预期/不变量/成败条件/核验器/超时（缺段拒执行）
- ★FR-032【Must·S1】工具清单声明风险/幂等/读回/补偿/权限/副作用（未声明不可被写动作调用）
- ★FR-033【Must·S1】策略允许/拒绝/请求批准/降级（R3+ 默认请求批准；MVP 批准=暂停等人工确认）
- FR-034【Must·S3】批准绑定动作/参数/范围/时限/批准者
- ★FR-035【Must·S1】执行后自动采集观察+组合核验（按 verify_with；全过才 pass）
- ★FR-036【Must·S1】核验四态；观察不足不归成功
- ★FR-037【Must·S1】偏差失效计划+有界恢复（次数/副作用上限；达限安全停止）
- FR-038【Should·S3】dry-run/幂等/补偿/事务批次
- FR-039【Should·S5】自治等级按四维动态调整
- ★FR-040【Must·S1】Meta Controller 记录 build/use/repair/bypass/probe/stop 及原因（无留痕不激活）
- ★FR-041【Must·S1】规则 DSL 与受限 Python 局部模型（都实现 §13.3 最小接口）
- FR-042【Should·S5】概率/因果/约束/组合模型
- ★FR-043【Must·S1】模型声明范围/假设/Unknown/覆盖/版本/依赖（激活要求范围匹配）
- ★FR-044【Must·S1】静态检查+历史回放+性质测试（影子 S4；MVP 人工批准替代）
- FR-045【Must·S4】模型全生命周期状态机
- ★FR-046【Must·S1】生成代码隔离沙箱（无网/无凭证/限资源；越权测试全失败）
- ★FR-047【Must·S1】规划受深度/节点/时间/成本/风险约束（超限即止）
- ★FR-048【Must·S1】现实执行逐步核验（仿真不跳过现实批准）
- FR-049【Should·S4】模型组合/修复/版本比较/漂移
- FR-050【Must·S5】委派声明输入范围/权限/预算/输出契约
- FR-051【Must·S5】Working Memory 私有；知识显式发布
- ★FR-052【Must·S1】人类暂停/接管/批准/更正/撤销（任意步骤生效留痕）
- ★FR-053【Must·S1】Supervisor 循环/预算超限/持续偏差检测（触发暂停升级）
- FR-054【Should·S5】五角色可配置
- FR-055【Should·S4】独立模型/人工复核留证据来源
- FR-056【Could·S5】并行探索与模型竞赛
- ★FR-060【Must·S1】完整因果时间线+动作前后证据（全覆盖可追溯）
- FR-061【Must·S2】派生物/记忆/模型/策略回溯当时版本
- ★FR-062【Must·S1】失败 Run 导出最小复现包+回归任务（干净环境可离线重放）
- ★FR-063【Must·S1】评测固定任务/模型/提示/预算/策略/种子/代码版本（报告可完整还原）
- ★FR-064【Must·S1】六组消融/切片/多种子/成本/失败分类（自动产出）
- FR-065【Must·S3】资产发布测试/影子/灰度/提升/回滚
- FR-066【Should·S2】历史轨迹离线评估
- FR-067【Should·S4】漂移/回归/资产影响告警
- FR-068【Must·S4】JSON/HTML 与企业审计导出（含前移注记）
- FR-069【Could·S5】排行榜
- FR-070【Must·S3】租户/项目/环境/用户/服务身份隔离
- FR-071【Must·S4】RBAC/ABAC、OIDC/SAML、SCIM、审计日志
- FR-072【Must·S3】配额/预算/速率/并发/成本归集
- FR-073【Must·S4】数据分类/驻留/保留/法律保留/删除
- FR-074【Should·S4】BYOK/自管数据面/air-gapped
- FR-075【Must·S3】策略/提示/插件/模型资产版本化可回滚
- FR-076【Must·S3】健康/告警/备份/恢复/事故管理
- FR-077【Should·S5】组织级自治与风险预算
- FR-078【Should·S4】用量/计费/成本优化
- FR-079【Could·S6】跨区域数据面/边缘编排
- FR-080【Must·S6】插件清单权限/数据/网络/资源/兼容/签名
- FR-081【Must·S2】脚手架/协议测试/本地开发工具
- FR-082【Must·S6】私有注册表/版本锁定/撤销/弃用
- FR-083【Should·S6】验证发布者/安全扫描/兼容矩阵
- FR-084【Could·S6】公开发现/评分/分发
- FR-085【Should·S4】开放事件与契约 Schema 迁移策略

### NonFunctional Requirements

*来源：PRD §8（NFR-001～015，逐条列表，语义见原文）。*

- NFR-001（完整性）写动作六段链完整率 100%
- NFR-002（可复现）确定性环境非模型事件与核验结果可完全重放
- NFR-003（安全）沙箱越权/批准绕过/跨租户访问 = 0
- NFR-004（可用性）按蓝图 §21 分版本 SLO
- NFR-005（性能）平台开销可单独测量且达蓝图 §21 目标
- NFR-006（扩展性）事件语义单机到分布式不变
- NFR-007（兼容性）N-1 兼容；破坏性变更走主版本
- NFR-008（可移植）Local/SaaS/VPC/Hybrid/air-gapped 共享核心
- NFR-009（隐私）原始证据最小访问/驻留/导出/删除有审计
- NFR-010（可观察）请求/Agent/认知/成本四域遥测关联 Run/Event
- NFR-011（可维护）契约边界；关键路径自动测试与迁移覆盖
- NFR-012（无障碍）Console 键盘/语义标签/对比度
- NFR-013（国际化）UI/时间/数字/策略可本地化；事件语义稳定
- NFR-014（数据耐久）RPO/RTO 达标并定期演练
- NFR-015（成本透明）Run/项目/租户成本可归集

### Additional Requirements

*来源：架构脊柱 ARCHITECTURE-SPINE.md（AD-1～15 + 约定 + Stack seed）与 PRD 附录移交输入。*

- **AD-1** 依赖方向：protocols 为依赖根；组装只在 vastacore-sdk/apps；适配器不被 import
- **AD-2** 事件溯源唯一写路径 + 持久化设施单点（vasta-storage）；(run_id,seq) 唯一约束+乐观并发
- **AD-3** Artifact 先落盘后引用；blob 只经 vasta-storage sharded 布局
- **AD-4** 写动作唯一通道 Contract→Policy→(Approval)→ToolGateway→Verify；分类由网关强制，无只读旁路
- **AD-5** 确定性重放：非模型路径禁不可注入熵，经 RunContext；重放接确定性替身
- **AD-6** 生成代码沙箱：MVP 受限子进程（非生产边界）；激活须带验证轨迹
- **AD-7** 一切持久实体带 (tenant_id, project_id)；查询经作用域过滤
- **AD-8** 控制面不接触原始载荷
- **AD-9** Schema semver + N-1 + 投影迁移器；历史不重写
- **AD-10** async-first；同步驱动经定容池隔离
- **AD-11** 幂等键唯一派生函数 (run_id, plan_step_id, tool, canonical_args_hash)；重复只返回原结果+replayed 标记；投影可重建
- **AD-12** 依赖不可用 fail-closed（Policy 挂→R2+ 拒绝；Evidence 挂→禁新写）
- **AD-13** world_model.\* 唯一状态流；失效桥接唯一 owner=vasta-cognition
- **AD-14** CAS 字节全局去重 + 租户引用映射表分离；删除=删映射
- **AD-15** 沙箱双轨钟：安全墙钟（触发记 system.\* Event），行为注入
- 事件族封闭集 13 族；命名/ID/错误信封/OTel/配置/契约测试约定（Conventions 表）
- Stack seed：Python 3.12+（开发 3.13）、uv workspaces、pydantic 2.13.x、fastapi 0.141.x、typer 0.27.x、uuid6、pytest 9.1.x、hypothesis 6.167.x、SQLite→PG17+、OTel 1.44.x
- **无 starter 模板**（greenfield 自研协议密集平台，脊柱评审已确认不用 full-stack 模板）——Epic 1 Story 1 = 从零搭建 uv workspaces monorepo 骨架
- 蓝图 E0–E13 骨架与关键路径 E0→E1/E3→E2/E4→E5/E6→E7+（plan.md §35，Epic 编号沿用）

### UX Design Requirements

无 UX 设计契约。MVP 交付面为 `vasta` CLI + 自包含 HTML Replay 生成器（纯生成物，无交互前端框架）；Console/Domain Studio（Stage 2+）启动前需先跑 bmad-ux 产出契约再补拆。

### FR Coverage Map

*★=MVP；FR-057～059 为蓝图遗留空号，无需求。[[ASSUMPTION] Epic 结构由笔者按用户价值组织并映射蓝图 E0–E13，待用户批准；MVP=Epic 1–7。]*

- FR-001★ → Epic 1（五协议 schema + 契约测试套件）
- FR-002 → Epic 8；FR-003 → Epic 8；FR-004★ → Epic 1；FR-005★ → Epic 1
- FR-006 → Epic 8；FR-007 → Epic 9；FR-008 → Epic 9；FR-009 → Epic 11
- FR-010★ → Epic 1；FR-011★ → Epic 1；FR-012★ → Epic 2；FR-013★ → Epic 2；FR-014★ → Epic 2
- FR-015 → Epic 8；FR-016 → Epic 8；FR-017 → Epic 9；FR-018 → Epic 9；FR-019 → Epic 12
- FR-020★～FR-025★ → Epic 5
- FR-026 → Epic 9；FR-027 → Epic 11；FR-028 → Epic 9；FR-029 → Epic 10
- FR-030★～FR-033★ → Epic 3；FR-034 → Epic 9；FR-035★～FR-037★ → Epic 3
- FR-038 → Epic 9；FR-039 → Epic 11
- FR-040★/041★/043★/044★/046★/047★/048★ → Epic 6
- FR-042 → Epic 11；FR-045 → Epic 10；FR-049 → Epic 10
- FR-050/051 → Epic 11；FR-052★ → Epic 4；FR-053★ → Epic 1
- FR-054/056 → Epic 11；FR-055 → Epic 10
- FR-060★ → Epic 4；FR-062★ → Epic 4
- FR-061 → Epic 8；FR-063★/064★ → Epic 7
- FR-065 → Epic 9；FR-066 → Epic 8；FR-067 → Epic 10；FR-068 → Epic 10；FR-069 → Epic 11
- FR-070/072/075/076 → Epic 9；FR-071/073/074/078/085 → Epic 10；FR-077 → Epic 11；FR-079 → Epic 12
- FR-080/082 → Epic 12；FR-081 → Epic 8；FR-083/084 → Epic 12
- NFR-001～015 → 跨 Epic：MVP 内嵌验收（NFR-001/002/003/005 MVP 档），其余随所属阶段 Epic 落地

## Epic List

### Epic 1: 可记录的 Agent Run（观察即证据）
开发者把 Agent 跑在 VastaCore Local Runtime 上（L0 Observe-only），Run 全生命周期受预算管理，五类 Observation 与原始证据全量、经哈希校验地落盘；Supervisor 兜底预算与循环。完成后：任何一次 Run 都留下完整、可校验的原始记录。对应蓝图 E0+E1/E3 核心。
**FRs covered:** FR-001★, FR-004★, FR-005★, FR-010★, FR-011★, FR-053★

### Epic 2: 证据回看与检索（无死链的证据库）
开发者可按时间/动作/事件/区域/对象/业务实体检索证据，对历史帧 inspect/crop/pixel read/并排 Diff，一切派生物可回链原始 Artifact。完成后：证据库可查、可看、可校验。对应蓝图 E1 检索面。
**FRs covered:** FR-012★, FR-013★, FR-014★

### Epic 3: 可信执行（写动作六段链）
带副作用的动作执行前成契约、过策略（R3+ 请求批准），执行后组合核验，偏差使依赖计划失效并进入有界恢复；人类可随时暂停/接管。完成后：UJ-2 的不变量拦截在本地可用。对应蓝图 E4。
**FRs covered:** FR-030★～FR-033★, FR-035★～FR-037★, FR-052★

### Epic 4: 回放与排障（十分钟定位首个偏差，UJ-1 达成）
`vasta inspect RUN_ID`：完整因果时间线、动作前后证据同屏、一键跳首个偏差、自包含 HTML Replay、导出最小复现包转回归任务（干净环境可离线重放）。完成后：UJ-1 全流程可用。对应蓝图 E7 MVP 档（依赖 Epic 3 的契约与偏差事件，对齐蓝图关键路径 E4→E7）。
**FRs covered:** FR-060★, FR-062★

### Epic 5: 认知资产初版（Agent 会记事）
Working/Hypothesis/Guide/Counterexample 四类记忆；Claim 带证据/反例/版本/状态全生命周期；互斥主张显式冲突；失效传播标记受影响计划；Context Builder 预算内装配。完成后：跨会话积累可撤回的理解。对应蓝图 E2。
**FRs covered:** FR-020★～FR-025★

### Epic 6: 世界模型实验室（按需可执行机制）
规则 DSL 与受限 Python 局部模型（最小接口）；生成代码进沙箱；静态检查+历史回放+性质测试（人工批准替代影子）；Meta Controller 元决策留痕；受约束规划且逐步现实核验。完成后：高价值机制可蒸馏、可验证、可用于规划。对应蓝图 E5。
**FRs covered:** FR-040★, FR-041★, FR-043★, FR-044★, FR-046★～FR-048★

### Epic 7: 评测与消融（可证明的净收益）
评测配置全固化可还原；六组消融（Baseline→Full）、切片、多种子、成本、失败分类自动产出；VastaLab 任务集初版（20+ 任务）。完成后：一份证明 Full 相对 Baseline 净收益的报告。对应蓝图 E6 + VastaLab。
**FRs covered:** FR-063★, FR-064★（+VastaLab 任务资产）

### Epic 8: 开发者接入体验（Stage 2，已展开——2026-09-09 增量拆解）
五种接入方式（轨迹导入升为一等形态）、模型能力探测与路由、插件脚手架与协议测试工具、GUI Pack（Playwright）与 Tool Proxy、按需派生、版本回溯、历史轨迹离线评估；评测即 Run（替身模型）与 lab.py 技术债并行。**FRs covered:** FR-002, FR-003, FR-006, FR-081, FR-015, FR-016, FR-061, FR-066（详见下文 Epic 8 详细节）

### Epic 9: 团队协作与控制面（Stage 3，已展开——2026-09-10 增量拆解）
集中存储（PG/S3）与统一 Sequencer、数据生命周期与删除证明、原始证据权限独立、审批记录、资产发布灰度与版本回滚、配额与成本归集、定时/批量/跨进程 Run、批量重验证、运维基线、Domain Studio 初版、沙箱生产化与桥接收口。**FRs covered:** FR-007, FR-008, FR-017, FR-018, FR-026, FR-028, FR-034, FR-038, FR-065, FR-070, FR-072, FR-075, FR-076（详见下文 Epic 9 详细节）

### Epic 10: 企业保障（Stage 4，2026-09-09 增量拆解）
模型全生命周期与影子、漂移告警、审计导出、RBAC/ABAC/SSO/SCIM、驻留/保留/法律保留、BYOK/air-gapped、计费、开放 Schema 迁移。**FRs covered:** FR-029, FR-045, FR-049, FR-055, FR-067, FR-068, FR-071, FR-073, FR-074, FR-078, FR-085

#### Epic 10 内部能力分组（2026-09-09 拆解）

| 组 | 用户价值 | FR | 带入项 |
|---|---|---|---|
| G0 工程前置 | 地基先稳：sdk 子包化（26 模块临界）与测试卫生（flaky/Fake 约束/常驻 Sequencer）——零行为变更 | —（Epic 9 复盘 C2/C3） | 子包化后新增模块不再进平铺目录 |
| G1 模型与认知治理 | 模型资产可信退役：全生命周期状态机、漂移检测与影响告警、认知三算子 | FR-045 + FR-055 + FR-067（+FR-049 版本比较/影响分析部分；组合属 Stage 5） | W-3 解除挂 10.5；C4 模型级重验证并入 10.4（漂移判定即重验证入口） |
| G2 审计与开放 | 审计导出是采购硬条件：JSON/HTML 企业导出 + 事件/契约 Schema 版本化与迁移策略 | FR-068 + FR-085 | — |
| G3 身份与访问 | 谁能做什么：RBAC/ABAC 角色模型、OIDC/SAML 集成、SCIM 同步、审计日志 | FR-071 | 机制面完整交付；真实 IdP 集成测试门控（先例：VASTA_PG_DSN） |
| G4 数据治理企业档 | 数据放哪里留多久：分类/驻留/保留时间表/法律保留（9.3/9.4 企业档扩展）+ BYOK/air-gapped | FR-073 + FR-074 | C4 PG 档备份并入 10.11（备份是保留策略执行面） |
| G5 计量计费 | 用量可计费、成本可优化：计费周期聚合、租户账单、成本优化建议 | FR-078 | 9.8 成本台账为底座 |

备注：FR-029（认知图查询可视化，Could）大部已由 9.13 Domain Studio 覆盖（认知图浏览/冲突/下钻），可视化分析增强随 Studio 迭代不再单列 Story；FR-049 的模型组合明确 Stage 5（多 Agent 前置）。

#### Story 列表

### Story 10.1: sdk 子包化（G0）

As a 平台架构师,
I want vastacore-sdk 按 storage/governance/ops 分子包（平铺 26 模块临界）,
So that Stage 4+ 新增企业模块不再进平铺目录。

**Acceptance Criteria:**

**Given** Epic 9 复盘 C2（26 模块 5762 行）
**When** 分子包重构
**Then** 零行为变更（727 测试全绿不动断言）；导入面后向兼容（顶层 `vastacore.*` 再导出保留一个 Stage）
**And** import-linter 增子包边界契约；常驻 Sequencer 评估结论入档（C3③——是否随包装配收敛）

**完成注记（2026-09-09）**：五子包（governance 7 / ops 4 / models 3 /
execution 3 / evidence 3）+ 根装配（cli/quickstart/scaffold）；727 全绿
零断言改动；顶层 96 符号再导出后向兼容；import-linter 5 契约 KEPT
（layers: ops→governance→base + 底层三包 independence + 子包禁导装配）。
**常驻 Sequencer 评估结论（C3③）**：维持按调用新建 + 有界重试——常驻化
的主要收益（省同步）已被 last_event_info O(1) 点查消解；竞态面已被
有界重试兜底（8 并发实测）；常驻需引入生命周期注册表增加装配复杂度，
收益不抵。F3 竞态问题就此关闭。

### Story 10.2: 测试卫生三件套（G0）

As a 平台维护者,
I want 子集 flaky 修复 + Fake 约束对齐惯例 + 真实存储关键路径覆盖,
So that 回归信号不被测试基础设施噪声侵蚀。

**Acceptance Criteria:**

**Given** G4-G6 验收审计（子集漂移失败）与两轮评审（FakeStorage 不查 event_id UNIQUE 等三类假绿面）
**When** 修复测试基础设施
**Then** Epic 9 测试文件与 TestClient 类任意组合选取稳定绿（复现命令 5/5）；FakeStorageAdapter 补 event_id 唯一模拟（或惯例文档化+关键路径真实存储测试）
**And** asyncio/TestClient portal 干扰根因记录入档

**完成注记（2026-09-09）**：① 审计复现命令修复后代码上 5/5 绿 + 4 变体
组合 ×3 全绿——**flaky 未复现**（G4-G6 评审修复大概率顺带消除触发面：
F8 Studio refresh/F3 重试路径改变了循环交互）；机制性隐患仍实修：
5 处裸 `new_event_loop()` 循环泄漏 → `asyncio.run`（创建即关闭）。
② Fake 约束对齐：`InMemoryEventLog` 补 event_id 全局唯一模拟（错误码
对齐 sqlite event.duplicate_id）+ 契约套件锚定 test_duplicate_event_id_
rejected（所有实现强制）；顺带修出契约测试自身复用 event_id 的假信封
构造债 2 处。728 全绿。

### Story 10.3: 模型全生命周期状态机（G1）

As a 模型治理负责人,
I want candidate/shadow/active/suspended/retired/revoked 全生命周期,
So that 模型资产从试验到吊销每一步有门有痕。

**Acceptance Criteria:**

**Given** 9.6 发布灰度（五态）与 8.8 版本化 registry
**When** 扩展生命周期
**Then** 六态+revoked 全状态机（非法迁移拒）；吊销（revoked）不可逆且级联（依赖它的计划/路由失效）
**And** 生命周期事件全留痕（release 族扩展）；FR-055 独立复核（人工复核门——复用 9.5 批准流）

### Story 10.4: 漂移检测与影响告警（G1）

As a 模型治理负责人,
I want 模型漂移检测、版本比较与影响分析接入告警,
So that 世界变了模型结论的可信度跟着变、有人被通知。

**Acceptance Criteria:**

**Given** 9.11 重验证（主张侧）与 9.12 告警规则
**When** 模型漂移事件到达（性能衰减/重验证失败率/分布偏移指标）
**Then** **模型级重验证**（C4 解除：受影响模型跑离线评估/性质测试——lab validation 复用）；漂移超阈 → 告警规则触发 → incident 联动
**And** 版本比较与影响分析（FR-049 部分——受影响 Run/计划清单报告）

### Story 10.5: 认知三算子——revise/promote/narrow（G1）

As a 认知资产维护者,
I want revise（修订）/promote（晋升）/narrow（收窄范围）显式算子,
So that 主张演化有精确语义而非 support/accept 近似（W-3 解除）。

**Acceptance Criteria:**

**Given** CognitionService（Epic 5）与 W-3 解除裁决（复评八）
**When** 调用三算子
**Then** claim.revised/claim.promoted/claim.narrowed 显式事件（payload 携旧值→新值）；状态机迁移合法（含 version 递增）；narrow 收窄 scope 显式入流
**And** 三算子状态机测试（W-3 解除条件字面达成——矩阵转正复评）

### Story 10.6: 企业审计导出（G2）

As a 企业合规官,
I want JSON 只读导出与 HTML 审计报告,
So that 审计与采购合规有交付物（FR-068 采购硬条件）。

**Acceptance Criteria:**

**Given** 事件溯源（AD-2）与既有系统流（approvals/access/quotas/incidents/billing）
**When** 触发审计导出（时间窗 + 作用域）
**Then** JSON 导出（只读——事件流逐条+工件引用清单，不含 blob 内容）；HTML 报告（时间线/批准/访问拒绝/事故/成本五节）
**And** 导出本身留痕（incident 族或 evaluation 族——导出行为可审计）

### Story 10.7: 开放 Schema 与迁移策略（G2）

As a 平台架构师,
I want 事件与契约 Schema 显式版本化 + 迁移工具,
So that 下游消费者与企业集成有稳定契约（FR-085）。

**Acceptance Criteria:**

**Given** ENVELOPE_SCHEMA_VERSION（协议已有版本位）与 13 族封闭集
**When** Schema 演进
**Then** JSON Schema 导出（信封/事件类型目录/系统流清单）；版本迁移器（旧→新版事件可读升级）；破坏性变更检测（同 run 混版本拒或显式升级）
**And** 迁移测试（构造 v0.1 事件 → 升级 → 断言等价）

### Story 10.8: RBAC/ABAC 角色模型（G3）

As a 安全负责人,
I want 角色与属性访问控制贯穿服务面与 Studio,
So that 共享 token 升级为每操作鉴权。

**Acceptance Criteria:**

**Given** Epic 9 复盘（进程侧身份未落地——共享 Bearer token）
**When** 定义角色（admin/auditor/operator/viewer）与属性规则（作用域×动作×资源类）
**Then** 策略评估点接入 service.py 与 studio.py 端点（拒绝 403 留痕）；approver/annotator 事件携带真实身份
**And** 角色分配留痕；策略评估单测 + 端点集成测试

### Story 10.9: OIDC/SAML 集成与 SCIM 同步（G3）

As a IT 管理员,
I want 企业 IdP 联邦登录与 SCIM 用户组同步,
So that 身份生命周期由企业系统管理。

**Acceptance Criteria:**

**Given** 10.8 角色模型
**When** 配置 IdP（OIDC issuer/JWKS）与 SCIM 端点
**Then** token 验签（JWKS 轮换）；SCIM 用户/组同步到角色映射；机制面完整 + 真实 IdP 集成测试门控（环境变量注入，先例 VASTA_PG_DSN）
**And** 身份断言审计留痕；无 IdP 配置时回退本地 token（开发档标注）

### Story 10.10: 审计日志聚合（G3）

As a 合规官,
I want 「谁在何时对什么做了什么」的统一审计日志,
So that 安全审查与追责有单一查询面。

**Acceptance Criteria:**

**Given** 分散系统流（approvals/access/quotas/incidents/lifecycle/release）
**When** 查询审计日志（时间窗 + 主体 + 资源）
**Then** 跨流聚合统一视图（主体→动作→资源→结果四元组）；导出接 10.6
**And** 不可篡改声明（append-only 事件流为源——与 AD-2 一致性说明）

### Story 10.11: 驻留、保留与法律保留策略（G4）

As a 数据保护官,
I want 数据分类、区域驻留策略、保留时间表与企业档法律保留,
So that 数据生命周期合规可执行可证明。

**Acceptance Criteria:**

**Given** 9.3 生命周期（热温冷+法律保留+删除证明）与 9.4 证据权限
**When** 配置企业策略（分类标签×区域×保留期×管辖域）
**Then** 保留到期自动处置建议（删除/归档清单+证明事件延续）；区域驻留校验（store 路径/后端标记 vs 策略——违规拒写或告警）；**C4 PG 档备份并入**（pg_dump 形态备份+恢复演练对 PG）
**And** 策略配置留痕；处置演练报告

### Story 10.12: BYOK 与 air-gapped 形态（G4）

As a 安全架构师,
I want 客户自管密钥与离线部署形态,
So that 敏感环境可用（FR-074）。

**Acceptance Criteria:**

**Given** 模型凭证经适配器注入（AD-4 网关唯一持有）
**When** 配置外部 KMS/密钥引用（BYOK）
**Then** 凭证不落库（引用+运行期解析）；air-gapped 检查（无外网依赖清单——模型路由降级链在纯本地形态可用）
**And** 密钥引用配置留痕（不含密钥本体）；离线形态冒烟测试

### Story 10.13: 用量计费与成本优化（G5）

As a 运营负责人,
I want 计费周期聚合、租户账单与成本优化建议,
So that 用量可计费、成本可归因可优化（FR-078）。

**Acceptance Criteria:**

**Given** 9.8 CostLedger 三级归集（run→项目→租户）
**When** 计费周期闭合（月度/自定义窗）
**Then** 账单生成（按模型/项目分项，basis 口径延续）；预算使用率与优化建议（低效路由/高成本模型替代候选——router 成本面复用）
**And** 账单留痕（billing 流周期闭合事件）；账单不可变（再生成=新周期版本）

### Epic 11: 平台化与多 Agent（Stage 5，仅 Epic 级）
组合/概率模型、动态自治、多 Agent 委派与共享边界、组织级风险预算、跨组织知识、排行榜、流式/边缘协同。**FRs covered:** FR-009, FR-027, FR-039, FR-042, FR-050, FR-051, FR-054, FR-056, FR-069, FR-077

### Epic 12: 开放生态（Stage 6，仅 Epic 级）
插件清单与签名、私有注册表与撤销、验证发布者、公开分发、证据第三方验证、跨区域/边缘编排。**FRs covered:** FR-019, FR-079, FR-080, FR-082, FR-083, FR-084

## Epic 1: 可记录的 Agent Run（观察即证据）

开发者把 Agent 跑在 VastaCore Local Runtime 上（L0 Observe-only），Run 全生命周期受预算管理，五类 Observation 与原始证据全量、经哈希校验地落盘，Supervisor 兜底。**FRs：FR-001★/004★/005★/010★/011★/053★；NFR-002 基础（AD-5 注入）；AD-1/2/3/5/7/10/11。**

### Story 1.1: Monorepo 骨架与协议基座

As a VastaCore 开发者,
I want 一个按依赖规则（AD-1）搭好的 uv workspaces monorepo 与 vasta-protocols 基座（事件信封 schema + 五协议接口 + 契约测试套件框架）,
So that 后续所有能力在一致、可测试的骨架上生长。

**Acceptance Criteria:**

**Given** 全新克隆的仓库
**When** 运行 `uv sync` 与 `uv run pytest`
**Then** 十个 `vasta-*` 包骨架全部可安装、测试与 lint 在 CI 通过
**And** `vasta-protocols` 对本仓库其他包零依赖（AD-1 可用 import-linter 校验）；事件信封含 `run_id/seq/type/parent_event_id/ts/tenant_id/project_id` 且实现 `(run_id, seq)` 唯一约束（AD-2）；Model/Environment/Tool/Storage/Verifier 五协议 Protocol 类可被 adapter 实现并被契约测试套件驱动；协议与 schema 均携带版本字段（FR-001 后果）

### Story 1.2: Run 生命周期与预算

As a Agent 平台工程师,
I want Run 的启动/暂停/恢复/取消/完成/失败状态机与三档预算（动作数/模型调用/时长）,
So that 任何失控 Run 都会安全停止而不是无限消耗。

**Acceptance Criteria:**

**Given** 已装配的 Local Runtime 与假环境适配器
**When** 启动 Run 并逐步执行动作
**Then** 每次状态转移产生对应 `run.*` 事件（含因果父项），暂停后恢复时先重新观察环境再与检查点比对（FR-004）
**And** 任一预算超限触发安全停止并落安全停止事件（复现包导出能力由 Epic 3 提供）；检查点含最后已提交动作、活跃计划、剩余预算

### Story 1.3: 五类 Observation 采集

As a Agent 开发者,
I want 环境交互产生的决策/过渡/终局/重置/外部五类 Observation 被正确分类并落库,
So that 核验与回放不会把动画帧或终局画面误判为可行动状态。

**Acceptance Criteria:**

**Given** 一个返回"决策帧→动画过渡帧→终局帧"序列的环境适配器
**When** Run 执行动作并采集观察
**Then** 五类 Observation 以 `observation.decision/transition/terminal/reset/external` 事件类型落库（FR-005，13 族封闭集）
**And** 终局与过渡帧不被标记为可行动状态（下游核验器测试可断言）

### Story 1.4: 原始证据内容寻址入库

As a Agent 开发者,
I want 每个原始观察与工具响应作为 sha256 内容寻址 Artifact 持久化并可校验取回,
So that 任何结论都能回到不可篡改的原始证据。

**Acceptance Criteria:**

**Given** Run 产生图像与 JSON 载荷
**When** Artifact 写入
**Then** 载荷按 sha256 前缀分桶存储（AD-3），元数据（来源/类型/大小/时间/分类/保留策略）事务写入，按哈希取回并校验成功（FR-010/011）
**And** 写入失败不产生"已捕获"事件（先落盘后引用）；一切实体含 `(tenant_id, project_id)` 作用域键且查询经作用域过滤（AD-7）；写动作 before/after 观察缺失率为 0（NFR-001 测试）

### Story 1.5: RunContext 确定性注入

As a 平台工程师,
I want Run 的时钟、随机种子与配置经 RunContext 注入、模型请求响应整体 Artifact 化,
So that Run 历史可在干净环境确定性重放。

**Acceptance Criteria:**

**Given** 使用了时间与随机的核心路径代码
**When** 以相同种子重放事件流
**Then** 非模型事件与核验结果逐字节一致（NFR-002）
**And** 直接调用系统时钟/随机/环境读取的路径在 review 检查（import-linter 禁令）下为零（AD-5）；重放模式适配器接确定性替身，接真实工具需显式授权

### Story 1.6: Supervisor 循环与预算监控

As a 平台工程师,
I want Supervisor 检测重复状态/动作模式与持续偏差并自动暂停升级,
So that 失控循环不继续烧预算。

**Acceptance Criteria:**

**Given** 构造的循环环境（同一状态-动作模式重复 N 次）
**When** Run 运行至循环出现
**Then** Supervisor 触发暂停、落 `run.paused` + 升级事件且不再消耗动作预算（FR-053）
**And** 检测阈值可配置；持续偏差（连续 M 次核验偏差）同样触发暂停升级（FR-053）；与 Story 1.2 的预算停止协同（预算先到→安全停止；循环/持续偏差先到→暂停升级）

### Story 1.7: 示例环境与端到端首跑

As a Agent 开发者,
I want 一个网格世界示例 EnvironmentAdapter 与 `vastacore-sdk` 一行装配入口,
So that 克隆后即可端到端跑通一个 L0 完整记录的 Run。

**Acceptance Criteria:**

**Given** 安装了 vastacore-sdk 的干净环境
**When** 运行 quickstart 示例
**Then** 一个完整 Run 跑通：证据全部落盘、事件链完整、可被后续 Epic 的检索/回放消费
**And** quickstart 文档与示例代码版本同步；此故事即 Epic 1 的验收演示

## Epic 2: 证据回看与检索（无死链的证据库）

**FRs：FR-012★/013★/014★；AD-3/7/14（引用映射表）。**

### Story 2.1: 多维检索索引

As a Agent 开发者,
I want 按时间窗、动作、事件类型、区域、对象与业务实体标签组合检索证据,
So that 排障时能直接定位相关证据而不是翻全量记录。

**Acceptance Criteria:**

**Given** 含多类型 Artifact 与事件的 Run 历史
**When** 任意维度或维度组合查询
**Then** 返回的 Artifact/Event 引用全部可取回且哈希校验通过——无死链（FR-013）
**And** 检索只经租户引用映射（AD-14），跨作用域查询被拒绝

### Story 2.2: 图像回看工具集

As a Agent 开发者,
I want 对历史帧做原分辨率 inspect、区域 crop、精确 pixel/color read 与并排 Diff,
So that 细粒度视觉疑问（边框？残影？颜色变化？）能用证据回答。

**Acceptance Criteria:**

**Given** 历史帧已入库
**When** 调用 inspect/crop/read_pixels/diff
**Then** 历史帧按原分辨率恢复；read_pixels 返回指定区域精确颜色值；Diff 输出同源区域并排对齐（FR-014）
**And** 工具输出带帧号与回合号引用，可直接用于新 Claim 的证据

### Story 2.3: 派生血缘与回链校验

As a 平台工程师,
I want 每个 DerivedAsset 登记源 Artifact、变换参数与版本并可一键回链校验,
So that 摘要与抽取永远只是索引层、不是唯一事实源。

**Acceptance Criteria:**

**Given** 由源 Artifact 生成的摘要/状态抽取派生物
**When** 查看派生物并执行回链
**Then** 源 Artifact 取回且哈希校验通过、变换参数与版本完整展示（FR-012，对应 AC-03）
**And** 源被删除时派生物标记"来源不可再验证"而非静默可用

## Epic 3: 可信执行（写动作六段链）

**FRs：FR-030★~033★/035★~037★/052★；AD-4/11/12；NFR-001/003。**（先于回放交付：偏差与契约事件是回放排障的输入，对齐蓝图关键路径 E4→E7。）

### Story 3.1: ActionContract 模型与缺段拒执行

As a 平台工程师,
I want 每个状态改变型动作执行前生成含前置/预期变化/不变量/成败条件/核验器/超时的契约且缺段即拒,
So that 无预期的写动作根本无法发生。

**Acceptance Criteria:**

**Given** 一个声明为写动作的工具调用
**When** 生成契约时缺少任一必填段
**Then** 动作不执行并落 `action.policy_denied`（含拒因）事件（FR-030/031）
**And** 完整契约的六段链（before/contract/policy/execution/after/verification）在成功路径 100% 完整（NFR-001，AC-02）；幂等键与补偿字段按 AD-11/FR-038 预留、Stage 3 激活

### Story 3.2: 工具清单与 Tool Gateway

As a 平台工程师,
I want 工具以清单声明风险/幂等/读回/补偿/权限，Tool Gateway 强制分类并统一派生幂等键,
So that 旁路执行与重复副作用在结构上不可能。

**Acceptance Criteria:**

**Given** 未声明风险与幂等语义的工具
**When** 某写动作尝试调用它
**Then** 调用被拒绝（FR-032）
**And** 读写/风险分类由网关依清单强制判定，调用方自声明无效（AD-4）；同幂等键 `(run_id, plan_step_id, tool, canonical_args_hash)` 的重复请求返回原结果 + `replayed=true`，绝不静默重执行（AD-11）；业务工具凭证只存在于网关

### Story 3.3: 策略引擎四态与 fail-closed

As a 安全治理人员,
I want 策略输出允许/拒绝/请求批准/降级四态、R3+ 默认请求批准、策略服务不可用时高风险 fail-closed,
So that 权限收紧不需要逐工具改造、故障也不会放大风险。

**Acceptance Criteria:**

**Given** R3 风险动作与生效策略
**When** 动作进入策略判定
**Then** 默认进入"请求批准"（MVP 落地为暂停等待人工在本地界面确认，FR-033）并留判定依据事件
**And** 策略引擎不可用时 R2+ 动作一律拒绝（AD-12）；降级路径被记录为事件

### Story 3.4: 执行后组合核验

As a Agent 开发者,
I want 动作执行后自动采集观察并按契约 verify_with 运行组合核验器（schema/读回/不变量/视觉 Diff 首版）,
So that "执行了"与"生效且没弄坏别的"被分别证明。

**Acceptance Criteria:**

**Given** 已执行的写动作与采集到的动作后观察
**When** 组合核验运行
**Then** 全部核验器通过才判 pass；结果为 pass/deviation/inconclusive/system_error 四态之一（FR-035/036）
**And** 观察不足（如读回超时）判 inconclusive 而非成功；不变量核验可由用户以结构化规则定义（UJ-2 的本地版）

### Story 3.5: 偏差失效与有界恢复

As a 平台工程师,
I want 核验偏差立即使依赖计划失效，恢复按有界序列（等待→读回→回看→分类→重试/补偿/重新规划/接管）进行且达限安全停止,
So that 一次偏差不会被盲目重试放大。

**Acceptance Criteria:**

**Given** 偏差注入测试场景（AC-04）
**When** 偏差发生
**Then** 依赖该动作的旧计划 100% 失效、不继续批量执行
**And** 恢复次数与副作用上限可配置，达上限触发安全停止并导出复现包（FR-037）；故障分类结果（环境延迟/工具错误/权限拒绝/模型误解/外部变化）落事件

### Story 3.6: 人工暂停/接管/批准/撤销

As a 终端监督者,
I want 在任意步骤暂停 Run、接管控制、批准等待中的动作或撤销决定且全部留痕,
So that 人始终能收回控制权。

**Acceptance Criteria:**

**Given** 运行中的 Run（含等待批准的动作）
**When** 执行暂停/接管/批准/撤销
**Then** 操作在当前步骤生效并产生 `run.*`/`action.approved` 类事件（FR-052）
**And** 接管后的动作需人工确认才执行；CLI 提供全部四操作

## Epic 4: 回放与排障（十分钟定位首个偏差，UJ-1 达成）

**FRs：FR-060★/062★；AD-5/11（重放）；NFR-002。**

### Story 4.1: 因果时间线投影

As a Agent 开发者,
I want 从事件流投影出按因果（而非纯时间）组织的完整时间线（CLI 表格 + JSON 输出）,
So that 理解一次 Run 的真实决策路径。

**Acceptance Criteria:**

**Given** 任一完成的 Run
**When** 生成时间线投影
**Then** 覆盖该 Run 全部事件类型且每个事件的因果父项可向上追溯（FR-060，对应 AC-01 完整回放）
**And** 投影可从事件历史随时删除重建（AD-11）

### Story 4.2: 首个偏差定位

As a Agent 开发者（陈默，UJ-1）,
I want 一键跳到 Run 的首个偏差并同屏看到该动作前后证据,
So that 排障从小时级翻日志变成分钟级看证据。

**Acceptance Criteria:**

**Given** 含注入偏差（核验 deviation/预期不符/外部变化）的 Run
**When** 执行首偏差定位
**Then** 定位到时间上第一个偏差事件，展示其前后原始观察、当时生效的契约与计划
**And** 外部变化类偏差被单独分类提示（区分"改 Agent"与"环境变了"两类响应）

### Story 4.3: 自包含 HTML Replay 生成器

As a Agent 开发者,
I want 把时间线、偏差点与动作前后证据渲染为单个无外部依赖的 HTML 文件,
So that 排障报告可以离线发给没装环境的同事与审计方。

**Acceptance Criteria:**

**Given** 任一完成的 Run
**When** 生成 HTML Replay
**Then** 单 HTML 文件包含因果时间线、首偏差高亮、动作前后证据（图像内嵌缩略图、工具响应可折叠），无网络与外部资源依赖
**And** 文件头含生成器版本与配置快照；证据可点击展开到 Epic 2 的 inspect/diff 引用

### Story 4.4: 最小复现包与回归任务

As a QA/评测工程师,
I want 把失败 Run 导出为最小复现包并一键登记为回归任务,
So that 每个失败都沉淀为可重复执行的测试资产。

**Acceptance Criteria:**

**Given** 任一失败 Run
**When** 导出复现包
**Then** 包含事件流、Artifact 引用、配置快照与确定性替身，在干净环境离线重放非模型事件与核验器通过（FR-062，对应 AC-08）
**And** 包内不含模型密钥与无关租户数据；回归任务以 vasta-protocols 定义的登记格式导出并通过其契约测试（评测框架可直接消费该格式）

## Epic 5: 认知资产初版（Agent 会记事）

**FRs：FR-020★~025★；AD-2/7/13 预留；蓝图 §11。**

### Story 5.1: 四类记忆与 Claim 全生命周期

As a Agent 开发者,
I want Working/Hypothesis/Guide/Counterexample 四类记忆以 Claim（范围/证据/反例/依赖/置信度/版本/状态）建模,
So that Agent 的每条理解都可治理。

**Acceptance Criteria:**

**Given** Run 中产生的候选认知
**When** 创建与演进 Claim
**Then** 全生命周期状态（proposed/supported/accepted/disputed/refuted/retired）转移均落 `claim.*` 事件（FR-020/021/022）
**And** 缺证据链路的 Claim 无法进入 accepted；被推翻的 Claim 不删除、保留影响链；Policy 类记忆对 Agent 只读

### Story 5.2: 显式冲突

As a 领域专家,
I want 同范围内互斥的主张产生显式 Conflict 记录而不是被静默覆盖,
So that 矛盾的理解可见、可裁决。

**Acceptance Criteria:**

**Given** 同范围两条互斥陈述的 Claim
**When** 第二条提出
**Then** 产生显式 Conflict 记录关联双方，检索双双呈现（FR-023）
**And** 冲突解决（缩范围/推翻一方/合并）产生新事件且可追溯

### Story 5.3: 失效传播

As a 平台工程师,
I want 依赖主张失效时受影响的 Plan 与资产被自动标记,
So that 建立在过时理解上的行动不会继续。

**Acceptance Criteria:**

**Given** 依赖某 Hypothesis 的活跃 Plan 与该 Hypothesis 被反例推翻
**When** 失效传播执行
**Then** 受影响 Plan/资产被标记失效并通知（FR-024）
**And** 与 Epic 3 联动：偏差注入场景中旧计划 100% 停止（AC-04 的认知侧路径）

### Story 5.4: Context Builder 预算内装配

As a Agent 开发者,
I want Context Builder 按目标、相关性、风险与预算装配上下文且选择依据可追溯,
So that 模型每次调用拿到的是可解释、不超预算的上下文。

**Acceptance Criteria:**

**Given** 目标、记忆库与 token/条目预算
**When** 装配上下文
**Then** 输出含每项入选依据（相关性/风险/来源），超预算按优先级裁剪并留裁剪记录（FR-025）
**And** 不发生静默截断（被裁剪项显式列出）

## Epic 6: 世界模型实验室（按需可执行机制）

**FRs：FR-040★/041★/043★/044★/046★~048★；AD-4/5/6/15。**

### Story 6.1: 模型接口、清单与双形态加载

As a 研究工程师,
I want 规则 DSL 与受限 Python 两种局部模型都实现蓝图 §13.3 最小接口并携带完整 manifest（范围/假设/Unknown/覆盖/版本/依赖）,
So that 任何候选模型都能被统一加载与验证。

**Acceptance Criteria:**

**Given** 一个候选局部模型（DSL 或 Python 形态）
**When** 提交加载
**Then** 两种形态都实现 init_state/transition/observe/outcome（+allowed_actions/state_hash/heuristic）接口；manifest 缺任一声明项被拒收（FR-041/043）
**And** 不满足接口的候选不进入回放流水线；manifest 的 Unknown/覆盖声明可被后续验证读取

### Story 6.2: 沙箱执行器（受限子进程）

As a 安全工程师,
I want 生成代码在无网络、无凭证、无宿主目录、资源受限的子进程沙箱中执行，安全强制用真实墙钟并把触发记为事件,
So that 生成代码的越权在结构上不可能。

**Acceptance Criteria:**

**Given** 沙箱内运行的世界模型代码
**When** 尝试网络访问、读取宿主文件、超出 CPU/内存/时间限制
**Then** 全部失败且越权尝试写入审计（FR-046，对应 AC-06）
**And** 安全超时/资源上限触发产生 `system.timeout/limit` 事件，重放读记录不重新计时（AD-15）；沙箱进程环境中不存在任何业务凭证（密钥不可达，FR-046/AC-06）；沙箱标注"非生产边界"，接口预留 Stage 3 容器化替换（AD-6）

### Story 6.3: 验证流水线（静态/回放/性质）

As a 研究工程师,
I want 候选模型经过静态检查、声明范围内全量历史回放与性质测试后由人工批准激活,
So that 只有真正重现已知历史的机制才获得执行信任。

**Acceptance Criteria:**

**Given** 带历史轨迹的确定性任务与候选模型
**When** 运行验证流水线
**Then** 静态检查（接口/禁止依赖/复杂度）+ 历史回放（真实动作序列重建状态并比对观察）+ 性质测试全部执行并留结果（FR-044）
**And** ≥10 个确定性任务的激活模型通过声明范围内全部历史回放（AC-05）；激活时校验 manifest 适用范围覆盖当前动作与环境（FR-043 后果）；MVP 激活需人工批准且批准留痕（影子期 Stage 4 替代）

### Story 6.4: Meta Controller（规则版）

As a 平台工程师,
I want 规则式 Meta Controller 决定 build/use/repair/bypass/probe/stop 并把每次决策及原因落事件,
So that "要不要建模"本身可审计。

**Acceptance Criteria:**

**Given** 规划视界、试错成本、机制复用度等输入信号
**When** 元决策触发
**Then** 决策（六选一）与依据落 `world_model.*`/`action.proposed` 关联事件（FR-040）
**And** 无决策留痕的模型不得激活；规则可配置且规则版本入配置快照

### Story 6.5: 受约束规划与逐步现实核验

As a 研究工程师,
I want 在验证过的模型内做受深度/节点/时间/成本/风险约束的规划，现实执行逐步核验,
So that 仿真通过不等于盲目批量执行。

**Acceptance Criteria:**

**Given** 激活模型与目标
**When** 规划器搜索
**Then** 超出任一上限即终止并返回已达最佳（FR-047）
**And** 计划逐步现实执行、每步走 Epic 3 核验，偏差立即暂停模型计划（FR-048）；仿真通过的 R2+ 动作仍需现实批准

### Story 6.6: WorldModel 失效桥接（AD-13）

As a 平台工程师,
I want 使 WorldModel 失效的反例经 claim.refuted 后由 vasta-cognition 作为唯一 owner 桥接为 world_model.suspended,
So that 认知与模型两条状态流不会各说各话、反例一定传导到模型侧。

**Acceptance Criteria:**

**Given** 一个激活的 WorldModel 与推翻其依赖假设的反例 Claim
**When** `claim.refuted` 发生
**Then** cognition 发出对应 `world_model.suspended`（或 scope_narrowed），桥接是唯一路径（AD-13）
**And** model-lab 不自建反例监听；下游读"当前活跃模型"只读 cognition 投影；桥接事件保留因果父项可追溯

## Epic 7: 评测与消融（可证明的净收益）

**FRs：FR-063★/064★ + VastaLab 任务资产；AD-5/11；蓝图 §15/§32.1。**

### Story 7.1: 评测框架与配置固化

As a QA/评测工程师,
I want 评测固定任务、模型、提示、预算、策略、种子与代码版本，报告可完整还原,
So that 任何分数都能被复现与审计。

**Acceptance Criteria:**

**Given** 一组评测任务与运行配置
**When** 评测执行完成
**Then** 报告可完整还原上述全部配置（缺一即不通过，FR-063）
**And** 评测运行复用 Run/事件/Evidence 设施（评测即 Run）；报告单列平台编排开销（非模型时延/成本），使其可单独测量与对照预算（NFR-005 MVP 档）

### Story 7.2: VastaLab 任务集初版

As a QA/评测工程师,
I want 20+ 个隐藏规则/布局变化/噪声/偏差注入的网格任务与基线记录,
So that 评测有可信的私有任务来源且不依赖公开集。

**Acceptance Criteria:**

**Given** 任务生成器与任务定义
**When** 加载并运行任务集
**Then** ≥20 个主任务 + 变体合计 ≥40 个可运行任务全部生成完整回放（AC-01 任务基础）
**And** 任务含偏差注入与噪声变体；基线（Baseline 配置）分数入库可作为后续回归参照

### Story 7.3: 六组消融 Runner

As a 产品负责人,
I want 一条命令跑出 Baseline/Evidence/Cognition/Contract/Model/Full 六组消融（含切片、多种子、成本与失败分类）,
So that 每层能力的净收益有数字、故事不靠感觉讲。

**Acceptance Criteria:**

**Given** Story 7.2 的 VastaLab 任务集与六组配置
**When** 运行消融
**Then** 自动产出六组报告：成功率/错误动作/成本（均值+方差+置信区间）与失败分类（FR-064，对应 AC-07）
**And** 组间仅目标能力差异（协议组合启停，FR-001 后果）；Full 相对 Baseline 净收益为正进入 Stage 1 出门条件

---

## Epic 8: 开发者接入体验（Stage 2 展开）

**用户成果**：开发者用熟悉的方式（SDK / HTTP / 轨迹导入 / Tool Proxy）在 ≤3 工程日内把 VastaCore 挂到自己的 Agent 上——工具经脚手架与协议测试接入、模型五维能力被自动探测并按策略路由熔断、任何派生物/记忆/模型/策略可回溯到当时版本、历史轨迹可离线评估新配置。（SM-5 出门条件：基础接入 ≤3 工程日 + ≥3 设计伙伴团队每周使用，验证 FR-002/081）

### Epic 8 内部能力分组（2026-09-09 批准，经 Party Mode 评审 + Assumption Audit 修订）

| 组 | 用户价值 | FR | 备注 |
|---|---|---|---|
| G1 接入面 | 我的 Agent 三天接入：SDK / HTTP / **轨迹导入（一等形态）** / Tool Proxy | FR-002 | middleware/proxy/sidecar 排 SM-5 伙伴信号之后；首个 Story 验收含**自测接入计时**（≤3 工程日从假设变实验） |
| G2 工具面 | 写个工具像写函数：脚手架生成清单骨架 + 协议测试本地一键跑 | FR-081 | SM-5 出门条件之二 |
| G3 模型面 | 换个模型不动代码：五维能力探测 + 路由/超时/重试/熔断/降级 + 成本归集（NFR-015） | FR-003 + FR-006 | 真实模型适配器为实现载体（PRD 无独立 FR 编号，[ASSUMPTION] 披露）；各 Story 标注「伙伴信号可调整」 |
| G4 回溯与离线评估 | 回到当时那一刻 + 旧轨迹评新配置 | FR-061 + FR-066 | ①已回溯类收口（派生物血缘+Claim.version）②**模型/策略版本化新建**（模型入 CAS+版本链、策略快照入事件）③**评测即 Run**：RunEngine+替身模型（FakeModel 契约）批量跑 VastaLab 产生完整事件流回放——不必等真实适配器，早期关验收矩阵 AC-01 P0 缺口并触发 WAIVER 复评 |
| G5 多模态按需派生 | 要时才算：视频时间窗/音频对齐 / 按需 OCR·ASR·embedding | FR-015 + FR-016 | Should 级；每个 Story 标注 GUI Pack 决议门槛（无 UX 契约前不实施） |
| 并行技术债 | lab.py（667 行十概念）拆分 sandbox/models/planner/meta | —（复盘 A5） | 并行不阻塞；388 测试回归护栏 |

### FR Coverage Map（Epic 8）

```
FR-002 → G1  五种接入 + Tool Proxy（轨迹导入一等形态）
FR-003 → G3  五维能力探测（真实适配器载体，ASSUMPTION 披露）
FR-006 → G3  路由/超时/重试/熔断/降级/成本
FR-081 → G2  脚手架 + 协议测试 + 本地开发工具
FR-061 → G4  版本回溯（2 类已有收口 + 2 类新建）
FR-066 → G4  历史轨迹离线评估（与 G1 轨迹导入配对）
FR-015 → G5  视频时间窗/音频对齐（GUI Pack 门槛）
FR-016 → G5  按需 OCR/ASR/embedding（GUI Pack 门槛）
```

**依赖**：G1/G2 可并行；G3 挂在 G1 的 Run 路径上；G4 依赖既有 CAS/事件基座；G5 独立可延后。组间无前向依赖。


### Story 8.1: SDK 接入与自测计时（G1）

As a Agent 开发者,
I want 一个 pip 安装的 SDK 把我的 Agent 循环挂进 RunEngine（生命周期/预算/证据落盘/六段链对我透明）,
So that 不改架构就获得可信执行与完整回放。

**Acceptance Criteria:**

**Given** 空仓库与一个示例 Agent（README 快速上手为准）
**When** 按文档从零接入并**计时记录**
**Then** ≤3 工程日完成接入（SM-5 实验证据，计时记录入档）
**And** 写动作自动走六段链（开发者无需手工编排核验）；同 seed 字节级复现（FR-002，SM-5）

### Story 8.2: 轨迹导入——一等接入形态（G1）

As a 已有生产 Agent 的团队负责人,
I want 把历史执行日志导入证据库（映射事件族 + 工具原始响应入 CAS）,
So that 零侵入获得检索/回放/离线评估。

**Acceptance Criteria:**

**Given** 常见轨迹格式样例（OpenAI messages 风格与自定义 JSONL）
**When** 执行导入
**Then** 逐条映射为合法信封事件（schema 校验过）且工具响应入 CAS 可哈希取回
**And** 导入产物可被 search/timeline/复现包消费；不合法轨迹明确报错不入库（fail-closed）（FR-002 第六种形态）

### Story 8.3: HTTP 接入服务（G1）

As a 非 Python 技术栈的工程师,
I want HTTP 服务暴露 Run 生命周期与证据查询,
So that 任何语言都能接入 VastaCore。

**Acceptance Criteria:**

**Given** SDK 已就绪（Story 8.1）
**When** 以服务模式启动
**Then** run/step/evidence/timeline 端点可用且经令牌鉴权
**And** 事件写入仍走唯一通道（AD-2，服务层不旁路）；服务崩溃不丢已落盘证据（FR-002）

### Story 8.4: 工具脚手架与协议测试（G2）

As a 工具作者,
I want `vasta tool init` 生成清单骨架 + 一键协议测试,
So that 我的工具过五协议契约才上架，不用读文档抄样例。

**Acceptance Criteria:**

**Given** 脚手架命令与空工具项目
**When** 生成骨架、填实现、本地跑协议测试
**Then** 契约套件（manifest 完整性/幂等/读回/风险分类/dry-run）全绿才可注册网关
**And** 缺风险/幂等声明在构造期拒绝（复用 FR-032 语义）（FR-081，SM-5）

### Story 8.5: 模型五维能力探测（G3）

As a 平台使用者,
I want 系统自动探测模型的视觉/结构化输出/工具调用/上下文/流式能力,
So that 路由与提示策略按真实能力走，而不是我手工声明。

**Acceptance Criteria:**

**Given** 任一模型适配器
**When** 运行能力探测
**Then** 产出五维能力清单（含探测方法与置信度）作为 Artifact 落盘留痕
**And** 探测失败 fail-closed（按无该能力处理，不猜测）（FR-003；伙伴信号可调整）

### Story 8.6: 模型路由、熔断与成本（G3）

As a 平台使用者,
I want 按能力+成本+健康的路由（超时/重试/熔断/降级）,
So that 换模型不动代码，故障不放大，成本看得见。

**Acceptance Criteria:**

**Given** 多个适配器与可配置路由策略
**When** 发起模型调用
**Then** 路由决策落事件留痕；失败按阈值熔断计数；成本计入预算归集（NFR-015）
**And** 降级链可配置且降级发生留痕（FR-006；伙伴信号可调整）

### Story 8.7: 版本回溯收口——派生物与记忆（G4）

As a 调试中的开发者,
I want 派生物与记忆一键回到当时版本,
So that 历史结论可复现、可对质。

**Acceptance Criteria:**

**Given** 任一派生物或 Claim ID
**When** 执行 as-of 时间点查询
**Then** 取回当时版本及其血缘链/证据链（哈希校验过）
**And** 查询只读零副作用（FR-061，验收性收口：复用既有血缘与 Claim.version）

### Story 8.8: 模型与策略版本化（G4）

As a 平台使用者,
I want 模型资产带版本链、策略配置有快照,
So that 「回到当时那一刻」覆盖全部四类对象。

**Acceptance Criteria:**

**Given** 模型 manifest 变更或策略配置变更
**When** 发布新版本
**Then** 旧版本可完整取回（模型资产入 CAS+版本引用链；策略配置快照入事件流）
**And** 历史 Run 的事件引用当时的版本（回放不串版）（FR-061）

### Story 8.9: 评测即 Run——替身模型批量回放（G4）

As a 平台负责人,
I want VastaLab 任务集经 RunEngine（替身模型）批量运行并产生完整事件流回放,
So that 评测任务与真实 Run 同构，验收 AC-01 从 PARTIAL 翻 FULL。

**Acceptance Criteria:**

**Given** ≥40 个 VastaLab 任务与 FakeModel 契约替身
**When** 批量运行
**Then** 每任务产出完整事件流（timeline 全覆盖、因果链可溯）且复现包可离线重放
**And** 触发验收矩阵 AC-01 与相关 WAIVER 复评（不等真实适配器——Assumption Audit P1 修正）

### Story 8.10: 历史轨迹离线评估（G4）

As a 平台负责人,
I want 对导入的历史轨迹离线评估新策略/核验器/模型,
So that 不重跑生产就能预判切换影响。

**Acceptance Criteria:**

**Given** Story 8.2 导入的轨迹与新核验器/策略配置
**When** 离线评估
**Then** 产出旧结果 vs 新结果对比报告（偏差清单含事件定位）
**And** 评估零副作用（只读回放，不产生新动作）（FR-066）

### Story 8.11: Tool Proxy（G1，排 SM-5 信号后）

As a 浏览器自动化团队,
I want Tool Proxy 把现有 Playwright 工具调用代理进六段链,
So that GUI Pack 不必重写既有工具。

**Acceptance Criteria:**

**Given** 既有 Playwright 工具调用
**When** 经 Proxy 执行
**Then** 走网关通道（清单/幂等/风险分类/超时）；原始响应入 CAS
**And** 蓝图 §31 Stage 2 交付物项（SM-5 伙伴信号确认需求后启动）

### Story 8.12: 多模态按需派生（G5，GUI Pack 决议门槛）

As a 多模态 Agent 开发者,
I want 按需触发 OCR/ASR/摘要/embedding 与视频时间窗/音频对齐（不默认全量派生）,
So that 派生成本可控、需要才算。

**Acceptance Criteria:**

【GUI Pack 决议门槛：UX 契约与 GUI Pack 决议未定前不实施】
**Given** 证据引用（图像/音视频）
**When** 显式请求派生
**Then** 派生物带血缘可回链源时间轴/源 Artifact；按需触发留痕
**And** 不请求不派生（FR-015 + FR-016，Should）

### Story 8.13: lab.py 模块拆分（并行技术债，复盘 A5）

As a 维护者,
I want lab.py（667 行十概念）拆分为 sandbox/models/planner/meta 模块,
So that Epic 8 各接入扩展不再挤单文件。

**Acceptance Criteria:**

**Given** 现有 vasta_model_lab 单文件实现
**When** 拆分模块
**Then** 公共 API 不变（`__all__` 兼容再导出）；388 测试全绿；import-linter 契约 KEPT
**And** 与 G1–G5 并行、不阻塞任何接入 Story（复盘 A5 行动项）

---

*Epic 8 备注：middleware/proxy/sidecar 三种接入形态（FR-002 余下）待 SM-5 伙伴信号确认需求后回到本工作流补拆 Story；真实模型适配器为 FR-003/006 实现载体（PRD 无独立 FR 编号，[ASSUMPTION] 披露）。*

---

## Epic 9: 团队协作与控制面（Stage 3 展开）

**用户成果**：团队在共享的集中证据库上协作——多成员多服务安全并发、数据生命周期合规（删除有证明）、审批有记录、资产发布可灰度可回滚、长任务规模化编排（定时/批量/跨节点恢复）、成本配额透明，并有运维基线与 Domain Studio 首版供领域专家审核。

### Epic 9 内部能力分组（2026-09-10 批准）

| 组 | 用户价值 | FR | 带入项 |
|---|---|---|---|
| G1 团队数据面 | 全团队共享一个证据库：PG 事件库 + S3 CAS（Team 档）；统一 Sequencer（5 处构造点收敛）；实体索引 | FR-070（存储侧） | 复盘 B1 首项、WAIVER W-2 解除 |
| G2 数据治理 | 删得掉、说得清：热/温/冷、法律保留、删除请求+不含内容的证明事件、删除前依赖检查；原始证据权限独立于派生物 | FR-017 + FR-018 | — |
| G3 审批与发布 | 谁批的、批了什么、可回滚：批准绑定动作/参数/范围/时限/批准者；发布测试→影子→灰度→提升→回滚；四类资产版本化回滚 | FR-034 + FR-065 + FR-075 | 8.8 registry 为 FR-075 底座 |
| G4 运行编排规模化 | 无人值守也可靠：定时/事件触发/批量 Run；跨进程恢复；配额/速率/并发/成本归集；批量重验证+认知衰减 | FR-007 + FR-008 + FR-072 + FR-026 | NFR-015 接线（epic8 defer #1）；W-1 挂重验证 Story |
| G5 运维与 Studio | 出事知道、坏了能修：健康/告警/备份/恢复/事故管理；Domain Studio 初版（UJ-2） | FR-076 + FR-028 | — |
| G6 沙箱与桥接收口 | 生产边界真到位：rootless 容器/microVM 沙箱池（AD-6 Stage 3 升级点）；cognition→lab 桥接接线 | —（架构带入） | 复盘 B5/A3、WAIVER W-4 解除 |

### FR Coverage Map（Epic 9）

```
FR-007 → G4  跨进程/节点恢复
FR-008 → G4  定时/事件触发/批量 Run
FR-017 → G2  生命周期 + 删除证明
FR-018 → G2  原始证据权限独立
FR-026 → G4  批量重验证 + 认知衰减
FR-028 → G5  Domain Studio 初版
FR-034 → G3  批准记录（绑定五要素）
FR-038 → G3  dry-run/幂等/补偿/事务批次（契约预留段激活）
FR-065 → G3  发布灰度与回滚
FR-070 → G1  身份隔离（存储侧强化；进程侧身份随 G4 服务化）
FR-072 → G4  配额/速率/并发/成本归集
FR-075 → G3  四类资产版本化回滚
FR-076 → G5  运维基线
```

**依赖**：G1 为地基（存储抽象先行）；G2/G3 并行；G4 依赖 G1；G5/G6 独立可并行。组间无前向依赖。

**进度（2026-09-10）**：**Epic 9 全部 14 Story 交付完毕**——G1-G3 与
G4-G6 均已通过四层代码评审（分别 +25/+22 锚定；报告见
docs/reviews/epic9-g123-code-review.md 与 epic9-g456-code-review.md；
defer 项入复盘清单）。事件命名注记：9.9 AC 字面 schedule.created/fired
在 AD-5 13 族约束下实现为 plan.scheduled/plan.fired（族内形态）；
9.14「模型执行全经池」经 make_sandbox_pool 接线（评审修复）。


### Story 9.1: 存储抽象双后端与统一 Sequencer（G1）

As a 平台维护者,
I want StorageAdapter 的 PG/S3 双后端实现与全仓统一的 Sequencer/EnvelopeBuilder,
So that 团队档存储切换不动业务代码，五个手工信封构造点收敛为一。

**Acceptance Criteria:**

**Given** 现有 SQLite 实现与 5 处 EventEnvelope 手工构造点
**When** 实现 PostgresEventStore + S3BlobStore（StorageAdapter 同契约）与统一 Sequencer
**Then** 契约套件（storage 七项）对双后端全绿；五处构造点全部改经 Sequencer（grep 零残留）
**And** SQLite 路径行为不变（502 测试全绿）；Sequencer 并发分配无 seq 洞（测试锚定）（FR-070 存储侧；复盘 B1）

### Story 9.2: 实体索引与检索维度补全（G1）

As a 团队分析师,
I want 业务实体维度的专用索引与别名检索,
So that 按订单号/客户号等实体键秒级定位全部相关证据。

**Acceptance Criteria:**

**Given** G1 双后端与既有 payload_equals 检索
**When** 工件/事件登记实体标签（entity_index 表或 PG 等价）
**Then** search_by_entity 命中跨事件/工件/派生物三类；空/未知实体明确空结果
**And** WAIVER W-2 解除（实体索引 + 检索测试入矩阵复评）（FR-013 字母级收口）

### Story 9.3: 数据生命周期与删除证明（G2）

As a 合规负责人,
I want 热/温/冷分层、法律保留、删除请求与不含内容的删除证明,
So that 「已删除」是可审计的事实而非口头承诺。

**Acceptance Criteria:**

**Given** 集中存储中的证据与认知/评测/法律保留依赖
**When** 发起删除请求
**Then** 删除前依赖检查（活跃认知/评测/法律保留阻止并说明）；执行后留不含内容的证明事件（deletion.proved）
**And** 热/温/冷分层策略可配置；法律保留期间删除被拒且留痕（FR-017）

### Story 9.4: 原始证据权限独立（G2）

As a 数据管理者,
I want 原始证据的访问权限独立于派生物与聚合指标,
So that 共享分析结论不等于泄露原始截图/响应。

**Acceptance Criteria:**

**Given** 派生物（血缘可达）与原始 Artifact
**When** 原始证据设为受限作用域
**Then** 派生物/聚合指标仍可读；原始 blob 取回被拒（作用域检查）；血缘链不因权限断链（引用可见、内容不可达）
**And** 权限判定落审计事件（FR-018）

### Story 9.5: 批准记录五要素绑定（G3）

As a 合规审计员,
I want 每次批准绑定动作、参数、范围、时限与批准者,
So that 「谁在何时批了什么」不可抵赖。

**Acceptance Criteria:**

**Given** Epic 3 的人工控制（approve_pending/revoke）
**When** 批准发生
**Then** approval 记录含五要素（action/args/scope/expires_at/approver）入事件流；超时批准自动失效（时限）
**And** 与既有 approval 工作流集成零语义冲突；审计可按批准者检索（FR-034）

### Story 9.6: 资产发布灰度与回滚（G3）

As a 资产负责人,
I want 模型/策略/工具/提示资产发布经测试→影子→灰度→提升→回滚,
So that 坏版本影响面可控、可退。

**Acceptance Criteria:**

**Given** 8.8 版本化 registry
**When** 发布新资产版本
**Then** 状态机 candidate→testing→shadow→canary→active（+rolled_back）；各状态转换落事件；回滚恢复引用至前 active 版本
**And** 影子期新旧版本并行对比产出差异报告；灰度比例可配（FR-065）

### Story 9.7: 契约预留段激活——dry-run/幂等/补偿/事务批次（G3）

As a 工具开发者,
I want ActionContract 预留的幂等键与补偿字段真正激活，支持事务批次,
So that 多步写操作要么全成、要么按逆序补偿。

**Acceptance Criteria:**

**Given** 契约预留字段（idempotency_key/compensation）与网关幂等缓存
**When** 声明事务批次（步骤列表 + 整体补偿计划）
**Then** 任一步失败按逆序执行已成功步的 compensate（各留痕）；批次整体一个事务事件（transaction.settled/aborted）
**And** dry-run 门对批次整体先行；幂等键跨批次稳定（AD-11）（FR-038）

### Story 9.8: 配额、速率与成本归集（G4）

As a 平台运营者,
I want 租户/项目级配额（速率/并发/预算）与 per-Run 成本归集,
So that 资源滥用有闸、成本按 Run/项目/租户可记账。

**Acceptance Criteria:**

**Given** Budget（Run 级）与 8.6 路由器成本估算
**When** 配置租户/项目配额
**Then** 超速率/并发被限流（429 语义）；成本记录贯穿 Run→项目→租户三级汇总（NFR-015 全档接线，epic8 defer #1 解除）
**And** 配额事件留痕；Router cost_summary 并入归集（FR-072）

### Story 9.9: 定时、事件触发与批量 Run（G4）

As a 运营负责人,
I want 定时/事件触发的批量 Run 调度,
So that 例行任务无人值守可靠执行。

**Acceptance Criteria:**

**Given** RunEngine 与 AgentSession
**When** 定义调度（cron/事件源）与批量任务清单
**Then** 到点触发批量执行；每次执行独立 Run（复用 8.9 批量语义）；调度本身是留痕事件（schedule.created/fired）
**And** 触发失败重试有上限；并发受配额约束（复用 9.8）（FR-008）

### Story 9.10: 长任务跨进程恢复（G4）

As a 长任务负责人,
I want Run 状态跨进程/节点可恢复,
So that 进程重启/节点故障不丢任务进度。

**Acceptance Criteria:**

**Given** 事件溯源（AD-2）与 checkpoint（Epic 1）
**When** 工作进程崩溃后新进程接管 Run
**Then** 从事件流重建引擎状态（checkpoint + 重观察比对既有语义）；接管留痕（run.adopted）
**And** 至少一次语义下的动作不重复执行（幂等键跨进程稳定）（FR-007）

### Story 9.11: 环境升级批量重验证与认知衰减（G4）

As a 平台负责人,
I want 环境升级后对历史认知/模型批量重验证并标记置信衰减,
So that 世界变了，旧结论的可信度跟着变。

**Acceptance Criteria:**

**Given** 8.10 离线评估与 Claim 依赖图
**When** 环境版本升级事件到达
**Then** 受影响主张/模型批量重验证（离线评估复用）；仍通过者保留、失败者按衰减规则降置信或推翻（事件留痕）
**And** 影响面报告（受影响清单+处置结果）；W-1（AC-07 CI）解除条件挂此 Story（真实适配器方差）（FR-026）

### Story 9.12: 运维基线——健康、告警、备份、恢复、事故（G5）

As a 运维工程师,
I want 服务健康检查、告警、备份恢复与事故管理基线,
So that 出事知道、坏了能修。

**Acceptance Criteria:**

**Given** HTTP 服务与存储双后端
**When** 部署运维基线
**Then** /healthz（活性/就绪分离）；关键指标告警规则（错误率/队列深/配额触顶）；存储快照备份+恢复演练（恢复后事件流完整校验）
**And** 事故（incident.*）可关联 Run 并复盘归档（FR-076）

### Story 9.13: Domain Studio 初版（G5）

As a 领域专家,
I want 一个界面审核 Agent 的认知与批量影响分析,
So that 不写代码就能参与治理（UJ-2）。

**Acceptance Criteria:**

**Given** 认知服务（Claim/冲突/上下文）与检索
**When** 打开 Domain Studio 初版（Web，只读为主）
**Then** 认知图浏览（主张/冲突/依赖）、证据下钻（时间线+复现包下载）、批量影响分析入口（环境升级→受影响清单预览）
**And** 专家操作（审核/标注）经 HTTP 服务走事件留痕——UI 零旁路（AD-2）；写操作复用 9.5 批准流（FR-028）

### Story 9.14: 沙箱生产化与桥接收口（G6）

As a 平台架构师,
I want rootless 容器/microVM 沙箱池替代受限子进程，cognition→lab 桥接自动接线,
So that 生产边界与架构语义（AD-6/AD-13）都真到位。

**Acceptance Criteria:**

**Given** MVP 受限子进程（AD-6 明示非生产边界）与手动桥接
**When** Stage 3 生产化
**Then** 沙箱池（rootless 容器 Podman 类；Windows 开发档回退子进程并标注）；模型执行全经池（模块/系统调用 allowlist）
**And** refute 后自动 world_model.suspended + 受影响 Plan 标记（plan.invalidated 链路）——**W-4 解除**（AD-6/AD-13；复盘 B5/A3）

---

*Epic 9 备注：进程侧身份（服务账号/用户身份传播）随 9.8 服务化与 9.13 Studio 落地；FR-038 幂等/补偿为契约预留段激活（Epic 3 已留位）。W-1/W-2/W-4 解除条件分别挂 9.11/9.2/9.14——解除时触发验收矩阵复评。*

---

*Stage 4+ 的 Epic 10–12（企业保障/平台化多 Agent/开放生态）按 PRD 阶段标注记录于上文 Epic List，到各自 Stage 启动时再回到本工作流展开 Story。*

