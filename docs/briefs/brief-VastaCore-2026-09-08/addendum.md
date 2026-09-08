---
title: VastaCore 产品简报附录
status: draft
created: 2026-09-08
updated: 2026-09-08
---

# 附录：承接下游文档的深度内容

本附录保存简报装不下、但 PRD/架构/Epic 拆解直接需要的内容。完整原始蓝图见仓库根目录 [plan.md](../../../plan.md)（v2.0，约 2100 行），研究调研见 [VASTA-BRAINSTORM.md](../../../VASTA-BRAINSTORM.md)；本附录做的是**索引 + 已收敛决策摘要**，不复制全文。

## 1. 事实边界（源自头脑风暴的勘误，下游必须遵守）

- VISTA 作者来自 MIT，而非 [VASTA-BRAINSTORM.md](../../../VASTA-BRAINSTORM.md) 开头所写的"斯坦福/伯克利团队"。
- VISTA/Tycho/Schema/AVO 公开集满分只证明 Harness 工程的杠杆作用，**不构成**私有任务泛化或商业价值证明。
- "纯视觉优于结构化输入""程序模型优于语言推理"都不是预设结论，生产系统按证据质量、风险、成本选组合。
- 头脑风暴中的市场比例（80% 嵌入 / 31% 投产 / 88% pilot 失败等）不作为硬性商业依据，需 Stage 0 访谈重新验证。
- VastaCore 是拟议产品名，与外部研究项目 VISTA 无隶属关系；公测前需商标/域名核查。

## 2. 研究 → 产品能力映射（PRD 的能力来源依据）

| 研究路线 | 吸收的机制 | 对应 VastaCore 组件 | 不照搬的部分 |
|---|---|---|---|
| VISTA | 原始视觉、无损历史、行动前预测 | Evidence Store、分层记忆、Action Contract | 公开游戏成绩≠企业泛化；语言认知难回归 |
| Tycho | 主动抽象、程序模型、历史回放、按需 Builder | Meta Controller、Partial World Model | 确定性游戏假设不适用所有现实环境 |
| Schema | 状态落地与机制发现一体化、回测 | 状态抽取插件、模型验证流水线 | 高维开放环境程序合成成本过高 |
| AVO | 持久状态、长程运行、监督恢复 | Checkpoint、Supervisor、预算恢复 | 研究 Harness ≠ 企业控制面 |
| Agent Memory / RPA | 摘要检索、确定性事务 | 派生索引（始终可回链）、工具事务语义 | 过早压缩；对变化环境脆弱 |

## 3. 已收敛的产品决策（plan.md §38.1，简报引用的依据）

- 定位"认知与执行可靠性平台"；完整产品含七个产品面（Open Core SDK、Runtime 数据面、证据认知面、世界模型实验室、控制治理面、回放评测、扩展生态）。
- 五级渐进自治（L0 Observe-only → L4 Adaptive），任何项目从 L0/L1 起步，按"环境×工具×操作×数据范围"逐格授权。
- 证据为事实源（不可原地修改），认知为可修订资产（被推翻不删除，改失效/缩范围）。
- 世界模型按需触发且必须允许 Unknown（防过早结构化与虚假完整性）；Meta Controller 第一阶段用可解释规则。
- GUI 为首选商业楔子；垂直差异放解决方案包，核心平台领域无关。
- 0–36 个月 = Stage 0 验证起步 + 六个交付阶段（1 Foundation → 2 Developer Preview → 3 Team Beta → 4 Enterprise 1.0 → 5 Platform 2.0 → 6 Ecosystem 3.0），阶段由进入门驱动而非日期。

## 4. 关键系统不变量（INV-01～16，架构文档必须逐条落实；全文见 plan.md §4）

- **证据（INV-01～04）**：原始证据只追加不改写；一切派生物可回链源证据；载荷/派生物/认知/指令分层防注入；决策/过渡/终局/重置/外部观察为不同事件类型。
- **行动与核验（INV-05～06）**：每个写动作绑定前后状态 + 契约 + 核验；核验优先独立确定性来源，模型不做自己的裁判。
- **认知（INV-07～08）**：稳定知识/工作状态/假设/反例分开管理；被推翻的认知不删除，改失效或缩范围并保留影响链。
- **世界模型（INV-09～10）**：必须声明适用范围、未知项与覆盖率；新证据与依赖假设冲突时，未执行依赖动作默认失效。
- **沙箱与权限（INV-11～12）**：生成代码默认不可信只在沙箱运行；平台不得绕过业务权限与外部安全控制。
- **恢复与评测（INV-13～14）**：自动恢复有预算和副作用上限；评测结果可完全还原配置与版本。
- **治理（INV-15～16）**：自治权随可验证表现动态升降；保留/归档/删除是证据设计的一部分。

## 5. Epic 骨架与关键路径（epics-and-stories 的输入）

E0 协议基础 → E1 证据平台 → E2 认知图 → E3 Runtime/Supervisor → E4 可信执行 → E5 世界模型实验室 → E6 评测 CI/CD → E7 Replay Console → E8 Domain Studio → E9 Team 控制面 → E10 Enterprise 保障 → E11 多 Agent → E12 垂直包 → E13 生态。
关键路径：`E0 → E1/E3 → E2/E4 → E5/E6 → E7/E8/E9 → E10/E11/E12 → E13`。

## 6. 技术选型基线（架构文档起点，plan.md §19）

Python 3.12+ / Pydantic / SQLite（本地）→ PostgreSQL + S3（团队）/ Typer CLI / FastAPI / pytest + Hypothesis + Playwright / OpenTelemetry。明确不提前引入：Kafka、独立向量库、学习型 Meta Controller、公开插件市场（各需先证明收益/需求）。

## 7. 首个 90 天计划（Stage 0–1 执行输入，plan.md §39）

- 第 1–30 天：10–15 个访谈收集失败轨迹；冻结 v0 事件/Artifact/Observation/Action Contract Schema；20 个 VastaLab 任务；monorepo + CI；Local CAS + SQLite Event Store。
- 第 31–60 天：证据 inspect/Diff/血缘；四类记忆初版；Observe–Contract–Policy–Act–Verify 闭环；核验器；偏差注入；Replay 报告。
- 第 61–90 天：规则式 Meta Controller；DSL/Python 世界模型 + 沙箱；六组消融；Tool Proxy/Playwright 适配器；至少一个外部团队 L0 接入；据数据决定继续/收缩/调整。

## 8. 待用户确认的开放问题（沿 plan.md §38.2–38.3）

- [A5]（plan.md §38.2 假设集）企业付费意愿完全未验证，Stage 0 访谈是硬前提。
- 开源范围与许可证：Developer Preview 前必须定（默认建议：协议/SDK/本地运行/基础回放开放）。
- 首个真实 GUI 场景：需"有历史失败、可读回、非安全关键的后台流程"，Stage 0 选定。
- 首批模型支持：默认一个 OpenAI 兼容接口 + 一个独立适配器。
- 品牌名称/商标核查：Developer Preview 前完成。
- 简报口径（内部对齐 vs 融资叙事）：当前按内部对齐书写，标记见 brief.md 文首。
- 团队规模与资源约束未在本简报声明——plan.md §34.1 按阶段假设（0–5 月 2–4 人起步），若实际资源不同，Stage 排期需要重排。
- §38.3 其余待确认项（SaaS 与私有化优先级、默认保留期、规则 DSL 边界、公共插件市场）未摘录，见原文。
