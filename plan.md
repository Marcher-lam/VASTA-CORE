# VastaCore 完整产品与实施方案

> 文档版本：v2.0（完整产品蓝图）  
> 文档状态：可用于产品决策、系统设计、研发拆解和阶段评审  
> 更新日期：2026-09-06  
> 规划周期：0–36 个月  
> 输入来源：[`VASTA-BRAINSTORM.md`](./VASTA-BRAINSTORM.md)、上一版方案及本轮系统性再头脑风暴  
> 名称说明：VastaCore 是拟议产品名称；VISTA 是外部研究项目，两者无隶属关系

---

## 0. 文档定位

本方案描述的是 VastaCore 从技术原型、开发者产品、企业级平台到开放生态的**完整终局蓝图**。MVP 只是验证这张蓝图的第一阶段，不是方案的边界。

本文回答九个问题：

1. VastaCore 最终是什么、不是什么；
2. 它解决哪些真实问题，面向哪些角色；
3. 完整产品应具备哪些能力；
4. 证据、记忆、假设、行动和世界模型如何协同；
5. 生产级系统如何部署、扩展、治理和运维；
6. 如何支持 GUI、视频、游戏、工业和其他交互环境；
7. 如何形成 SDK、控制台、插件和认知资产生态；
8. 如何用 0–36 个月路线图逐步交付，而不是一次性建设；
9. 如何用量化门槛证明产品有效，并在无效时及时停止或转向。

---

# 第一部分：战略与产品定义

## 1. 执行摘要

### 1.1 一句话定义

> **VastaCore 是面向长程、多模态、工具调用型 Agent 的认知与执行可靠性平台：保留原始证据、管理可修订认知、约束并核验行动、按需构建可执行世界模型，并把每次成功与失败沉淀为可测试资产。**

### 1.2 产品终局

成熟的 VastaCore 由七个相互独立但语义一致的产品面构成：

| 产品面 | 面向对象 | 核心职责 |
|---|---|---|
| Open Core SDK | Agent 开发者 | 环境、模型、工具、证据、记忆、契约和事件协议 |
| Runtime Data Plane | 运行与平台团队 | 执行 Agent 循环、状态管理、预算、恢复、模型路由 |
| Evidence & Cognition Plane | Agent 与领域专家 | 原始证据、派生索引、记忆、假设、反例、技能和知识版本 |
| World Model Lab | 研究/高级工程团队 | 局部模型生成、验证、组合、仿真、规划、漂移与退役 |
| Control & Governance Plane | 管理员、安全、审计 | 策略、自治等级、审批、租户、身份、保留、发布和合规 |
| Replay & Evaluation Platform | 开发、测试、运营 | 时间线、Diff、复现、评测、消融、回归、事故分析 |
| Extension Ecosystem | 集成商与合作伙伴 | 适配器、核验器、策略包、模型包、任务集及签名注册表 |

### 1.3 核心价值链

```text
原始多模态证据
  → 可寻址、可校验、可治理的证据库
  → 有来源、可修订、可失效的认知资产
  → 动作前预测、风险检查与批准
  → 动作执行、状态读回与独立核验
  → 偏差发现、计划失效、恢复或人工接管
  → 高价值机制按需形成可执行局部模型
  → 成功/失败轨迹沉淀为测试、规则、技能和评测资产
```

### 1.4 关键产品判断

1. **采用入口不是“万能世界模型”**，而是 Agent 调试回放、原始证据链和可信执行。
2. **长期差异化来自认知资产生命周期**：证据、规则、反例、核验器、技能和局部模型都能版本化、测试和复用。
3. **世界模型是按需能力**：只有当内部建模的预期收益高于成本时才触发。
4. **自治必须渐进获得**：先观察，再建议，再强制核验，最终只在有持续证据的有限范围内自治。
5. **场景差异由解决方案包承载**：核心平台保持领域无关，GUI、视频、游戏、工业各自提供状态抽取、核验和策略插件。
6. **公开基准只用于研究校准**：产品价值必须由私有变体、真实影子运行和生产指标证明。

---

## 2. 研究启发与需求再梳理

### 2.1 从研究路线提炼出的可复用能力

| 路线 | 有价值的机制 | 不能直接照搬的部分 | VastaCore 的吸收方式 |
|---|---|---|---|
| VISTA | 原始视觉、无损历史、自由语言认知、行动前预测 | 公开游戏结果不能代表企业泛化；自然语言认知难以严格回归 | Evidence Store、分层记忆、Action Contract |
| Tycho | 主动抽象、程序模型、历史回放、按需 Builder | 确定性游戏假设不适用于所有现实环境 | Meta Controller、Partial World Model、Unknown/coverage |
| Schema | 状态落地与机制发现一体化、回测与内部搜索 | 高维开放环境中程序合成成本可能过高 | 状态抽取插件、模型验证流水线、领域规划器 |
| AVO | 持久状态、长程运行、监督与恢复 | 单一研究 Harness 不是企业控制面 | Checkpoint、Supervisor、预算和恢复编排 |
| 普通 Agent Memory | 摘要、向量检索、用户偏好 | 容易过早压缩且缺少证据/反例语义 | 派生索引保留，但原始证据始终可回链 |
| RPA/工作流 | 确定性、权限、审计、事务流程 | 对未知界面和变化环境脆弱 | 工具事务语义与 Agent 自适应结合 |

### 2.2 重新定义问题

VastaCore 不把问题定义为“让 Agent 记得更多”，而定义为：

> 在动态、多模态、部分可观测并具有真实副作用的环境中，如何让 Agent 的观察、认知、行动、验证和学习形成一条完整、可审计、可恢复、可持续改进的工程闭环？

由此产生八个产品域：

1. 证据底座；
2. 派生理解与索引；
3. 认知资产与记忆；
4. 可信行动与恢复；
5. 世界模型与规划；
6. 生产运行与治理；
7. 开发、回放与评测；
8. 垂直方案与开放生态。

### 2.3 原始头脑风暴中的事实边界

- VISTA 官方页面显示该项目作者来自 MIT，而非原始材料开头所写的“斯坦福/伯克利团队”。
- VISTA、Tycho、Schema、AVO 的公开集成绩支持 Harness 工程具有重要杠杆作用，但不构成私有任务泛化或商业价值证明。
- “纯视觉优于结构化输入”“程序模型优于自然语言推理”都不应成为预设结论；生产系统应按证据质量、风险、成本和环境性质选择组合。
- 原始材料中的市场比例、产品成熟度和未来预测不作为本方案的硬性商业依据，商业判断需要重新访谈和验证。

---

## 3. 愿景、使命与长期目标

### 3.1 愿景

让任何具有外部行动能力的 Agent 都能回答并证明：

- 我看到了什么；
- 我为什么相信某件事；
- 我准备做什么以及预期结果；
- 实际发生了什么；
- 哪个证据推翻了原计划；
- 我学到的规则在哪些范围内有效；
- 人类如何暂停、纠正、审计或撤销我的自治。

### 3.2 使命

把 Agent 的“认知过程”从不可复现的上下文和日志，转化为有来源、有版本、有测试、有权限、有生命周期的工程资产。

### 3.3 36 个月目标

1. 形成稳定的开放核心协议和多框架 SDK。
2. 形成可用于真实生产的运行数据面与企业控制面。
3. 支持至少三类垂直解决方案，并有量化的生产收益。
4. 建立认知资产 CI/CD：规则、核验器、策略、技能和世界模型可测试、灰度、回滚。
5. 建立安全的扩展包注册、签名、兼容和分发机制。
6. 推动执行契约、观察事件和认知资产格式成为可互操作接口。

### 3.4 不追求的目标

- 不训练通用基础模型；
- 不替代 LangGraph、模型 SDK、RPA、对象存储、IAM 或监控平台；
- 不承诺构建现实世界的完整数字孪生；
- 不把自然语言解释包装为形式化证明；
- 不默认允许 Agent 自动执行高风险或不可逆操作；
- 不在同一阶段同时成为 GUI、视频、游戏、机器人四个垂直产品；
- 不以单个排行榜或单次最佳结果定义成功。

---

## 4. 产品原则与系统不变量

| ID | 不变量 |
|---|---|
| INV-01 | 原始证据一旦写入即不可原地修改；修正通过新版本或新事件表达。 |
| INV-02 | 摘要、OCR、ASR、embedding、对象抽取和状态解析都是派生物，必须可回链原始证据。 |
| INV-03 | 原始载荷、派生物、认知主张与系统指令必须明确分层，观察内容永远不能自行提升为指令。 |
| INV-04 | 决策观察、过渡观察、终局观察、重置和外部事件必须有不同事件类型。 |
| INV-05 | 每个状态改变型动作必须绑定动作前状态、预期、不变量、风险、批准、结果和动作后状态。 |
| INV-06 | 关键核验优先使用独立确定性来源；执行模型不能默认成为自己的唯一裁判。 |
| INV-07 | 稳定知识、当前工作状态、假设、反例、偏好和程序技能分开管理。 |
| INV-08 | 被推翻的认知不删除，改为失效或缩小范围，并保留影响链。 |
| INV-09 | 世界模型必须声明适用范围、未知项、假设、覆盖率、验证结果和版本。 |
| INV-10 | 新证据与依赖假设冲突时，所有尚未执行的依赖动作默认失效。 |
| INV-11 | Agent 生成的代码和扩展包默认不可信，只能在受限环境中运行。 |
| INV-12 | VastaCore 不能绕过业务权限、人工审批、数据库事务或外部安全控制。 |
| INV-13 | 所有自动恢复均有重试、预算、时间和副作用上限。 |
| INV-14 | 每个评测结果必须能还原任务、模型、提示、配置、策略、预算、数据和代码版本。 |
| INV-15 | 自治权依据可验证表现和风险动态升降，不是一次授予、永久有效。 |
| INV-16 | 数据保留、归档和删除是无损证据设计的一部分，而不是事后补丁。 |

---

## 5. 目标用户、角色与完整旅程

### 5.1 用户角色

| 角色 | 主要任务 | 核心诉求 |
|---|---|---|
| Agent 开发者 | 接入、调试、评测、修复 | 快速接入、一眼定位失败、可复现 |
| AI 平台工程师 | 部署、模型路由、资源与版本 | 统一运行面、可扩展、成本可控 |
| 领域专家 | 定义成功条件、规则和禁区 | 使用业务语言、可纠正、无需写底层代码 |
| 安全与治理人员 | 权限、风险、审批、审计 | 默认安全、证据充分、策略可执行 |
| QA/评测工程师 | 任务集、消融、回归和门禁 | 可重复、可比较、避免数据泄漏 |
| 运营/SRE | 监控、告警、事故与容量 | SLO、漂移、恢复、成本可见 |
| 审计/合规人员 | 调查具体运行和策略 | 只读可信证据、导出、保留证明 |
| 终端用户 | 委派、监督、更正、接管 | 知情、可控、可解释、可撤销 |
| 插件/集成开发者 | 扩展适配器与领域能力 | 稳定协议、测试工具、签名分发 |

### 5.2 开发者完整旅程

```text
安装 SDK
  → 为现有环境实现 observe/execute/status
  → 包装工具并声明风险、幂等、读回和补偿能力
  → 运行 Baseline 与 observe-only 模式
  → 在 Replay 中检查证据、动作与失败
  → 添加领域状态抽取器和核验器
  → 启用 recommend/enforce
  → 建立私有评测与发布门
  → 对稳定范围开放 autonomous
  → 持续监控漂移、成本和事故
```

### 5.3 领域专家旅程

1. 在 Domain Studio 中选择业务对象和关键状态；
2. 用结构化表单或受限 DSL 定义成功条件、不变量和禁止条件；
3. 标注历史运行中的正确变化、异常变化和不确定情况；
4. 审核由系统提出的规则/记忆晋升；
5. 查看新规则在历史任务上的离线影响；
6. 批准影子运行、灰度范围或撤回规则。

### 5.4 审计与事故旅程

1. 通过用户、时间、工具、业务对象或事件定位 Run；
2. 查看动作前后原始证据与哈希；
3. 查看当时生效的模型、提示、记忆、策略与批准；
4. 确认首个偏差发生时刻及后续恢复；
5. 导出签名证据包和最小复现包；
6. 将事故转化为评测任务、策略变更或核验器用例。

---

## 6. 自治等级与采用路径

| 等级 | 系统行为 | 适用阶段 | 退出条件 |
|---|---|---|---|
| L0 Observe-only | 只记录、回放和离线核验，不改变现有行为 | 初次接入、生产影子 | 证据链完整且无性能阻塞 |
| L1 Recommend | 提供预测、风险、核验建议，人类/原系统执行 | 高风险试点 | 建议质量与成本达到门槛 |
| L2 Enforce | 执行前强制契约和策略，执行后强制核验 | 稳定工具和流程 | 漏检、误阻断和恢复达标 |
| L3 Bounded Autonomous | 在明确环境、工具、预算和风险范围内自治 | 成熟生产范围 | 持续表现稳定，无高严重度事故 |
| L4 Adaptive Autonomous | 自治范围根据近期证据动态升降 | 长期目标 | 需企业策略、成熟评测和监管认可 |

任何项目都必须从 L0/L1 开始。自治按“环境 × 工具 × 操作 × 数据范围”授予，而不是按整个 Agent 一次授权。

---

## 7. 产品版本与部署形态

### 7.1 产品版本

| 版本 | 面向用户 | 能力范围 |
|---|---|---|
| Community | 个人开发者、研究者 | SDK、本地 Runtime、本地证据库、基础回放、评测和适配器协议 |
| Team | 小型产品团队 | 共享项目、集中存储、团队 Console、策略、审批、评测门禁、SSO 基础能力 |
| Enterprise | 大中型组织 | 多租户、ABAC、SCIM、数据驻留、BYOK、审计、SLO、灾备、私有数据面 |
| Research | 实验室与评测团队 | 环境生成、消融、轨迹分析、世界模型研究接口、大规模实验编排 |

### 7.2 部署形态

- **Local**：单机进程 + SQLite + 内容寻址文件存储；
- **Single-tenant**：客户 VPC 内 API、worker、Postgres、S3 和沙箱；
- **Managed SaaS**：共享控制面、租户隔离数据面；
- **Hybrid**：SaaS 控制面 + 客户私有证据/执行数据面；
- **Air-gapped**：离线镜像、本地模型、本地依赖和离线许可证；
- **Edge**：靠近摄像头、设备或桌面环境做采集、脱敏与低延迟核验。

---

# 第二部分：完整能力体系

## 8. 能力地图

| 能力域 | 核心能力 | 成熟形态 |
|---|---|---|
| C1 接入 | 模型、环境、工具、存储、身份适配 | 多框架、能力探测、兼容测试 |
| C2 证据 | 多模态采集、哈希、因果时间线、时空寻址 | 数据分层、签名、驻留与删除证明 |
| C3 派生理解 | OCR/ASR、摘要、对象、状态、embedding | 按需处理、版本血缘、质量评测 |
| C4 认知资产 | Working、事实、假设、反例、偏好、程序、技能 | 主张图、晋升、冲突、衰减、发布 |
| C5 可信执行 | 预测、不变量、风险、批准、读回、补偿 | 事务化工具语义、自治等级 |
| C6 世界模型 | 生成、导入、回放、仿真、组合、规划 | 模型注册表、信任分、漂移与复用 |
| C7 监督恢复 | 偏差、计划失效、重试、检查点、接管 | 长程任务恢复和跨会话运行 |
| C8 多 Agent/人机 | 委派、共享证据、知识发布、审批 | 有边界的协作认知空间 |
| C9 评测学习 | 私有任务、消融、回归、影子、灰度 | 认知资产 CI/CD 与反馈飞轮 |
| C10 控制治理 | 租户、身份、策略、配额、保留、审计 | 企业控制面和合规证据 |
| C11 体验 | SDK、CLI、Console、Domain Studio | 从调试到运营的一体化工作台 |
| C12 生态 | 插件、清单、签名、注册、分发 | 开放协议和可信扩展市场 |

---

## 9. 端到端运行流程

### 9.1 单步闭环

```text
OBSERVE
  → CLASSIFY（决策/过渡/终局/外部事件）
  → STORE（原始证据与事件）
  → DERIVE（按需 OCR/摘要/状态/索引）
  → RECALL（记忆与历史证据）
  → REASON（主张、假设、目标与候选计划）
  → DECIDE（直接推理 / 探测 / 世界模型 / 人工）
  → CONTRACT（预期、成功条件、不变量、风险、核验器）
  → POLICY（允许 / 拒绝 / 批准 / 降级）
  → EXECUTE
  → REOBSERVE
  → VERIFY（通过 / 偏差 / 不确定）
  → COMMIT 或 INVALIDATE
  → LEARN（记忆修订、反例、测试和模型漂移）
```

### 9.2 长程任务生命周期

| 阶段 | 系统职责 |
|---|---|
| Intake | 解析目标、禁止条件、完成定义、预算、时限和授权范围 |
| Bootstrap | 环境能力探测、初始观察、记忆检索、风险基线 |
| Explore | 低风险探测、假设形成、信息增益评估 |
| Plan | 直接语言规划或按需建立局部世界模型 |
| Execute | 单步契约、策略检查、执行、核验和检查点 |
| Recover | 分类故障、取消依赖计划、回看、重试、补偿或接管 |
| Complete | 验证目标和不变量、封存运行证据、生成报告 |
| Consolidate | 将候选知识转为经审核资产和回归任务 |
| Retain/Delete | 按策略归档、保留、匿名化或可验证删除 |

### 9.3 检查点与恢复

检查点必须包含：

- 当前环境标识与可验证状态摘要；
- 最后一个已提交动作；
- 活跃目标、计划和依赖图；
- 当前 Working Memory；
- 生效的 Guide、策略、模型和版本；
- 未解决假设、偏差和批准请求；
- 剩余预算与恢复次数。

恢复时先重新观察真实环境，再与检查点比较；不得假设外部世界在暂停期间未变化。

---

## 10. 无损证据平台

### 10.1 支持的证据

- 图像：全帧、局部区域、多视角、深度图；
- 视频：原始片段、关键帧、时间窗、动作前后片段；
- 音频：原始音轨、分段、声纹/事件派生物；
- 界面：截图、DOM、Accessibility Tree、Canvas、窗口元数据；
- 文档：原文件、页图、布局、表格和引用位置；
- 工具：请求、响应、状态码、流式事件和副作用标识；
- 系统：日志、指标、trace、传感器、数据库读回；
- 人工：批准、纠正、标注、接管和事故说明。

### 10.2 存储原则

1. Artifact 使用内容哈希寻址，元数据与大对象分离。
2. 每个派生物记录源 Artifact、变换参数、代码/模型版本和质量。
3. 事件为追加式事实，当前状态由投影生成。
4. 支持时间、空间区域、对象、动作、业务实体、来源和语义多维索引。
5. 热、温、冷、法律保留和删除队列是统一生命周期状态。
6. “无损”不等于“永不删除”；删除必须经过授权并留下不含内容的证明事件。

### 10.3 检索流程

```text
结构化过滤/关键词/向量检索
  → 候选派生物
  → 获取原始证据或精确区域/时间片
  → 并排比较/像素或时序读取
  → 产生新的主张或修订
  → 记录本次证据使用关系
```

### 10.4 数据生命周期

| 状态 | 行为 |
|---|---|
| Captured | 原始载荷已校验写入，尚未派生 |
| Derived | 已生成一个或多个可重建派生物 |
| Active | 当前任务或近期评测频繁使用 |
| Warm | 低频访问，可延迟取回 |
| Archived | 冷存储，仅保留索引与取回信息 |
| Legal Hold | 禁止自动删除，受专门权限管理 |
| Pending Deletion | 已授权，等待依赖与保留检查 |
| Deleted | 内容已删除，保留最小证明和审计事件 |

### 10.5 成本控制

- 感知到变化时优先保留变化片段，但仍可根据政策保留原始母体；
- 派生处理按任务需要触发，不默认对所有内容做 OCR/embedding；
- 相同内容哈希去重，但租户计费和权限仍独立；
- 为 Run、项目和租户设置存储、派生计算和读取预算；
- 在删除或冷归档前检查活跃认知、评测和法律保留依赖。

---

## 11. 认知资产与长期记忆

### 11.1 认知类型

| 类型 | 含义 | 示例 |
|---|---|---|
| Working | 当前任务的临时状态与计划 | 当前页面、候选路线、待确认字段 |
| Episodic | 某次运行中发生的情境 | 某按钮点击后出现二次确认 |
| Fact | 有证据支持的事实 | 订单 A102 当前为 pending |
| Hypothesis | 待验证的机制或解释 | 蓝色边框可能表示已选中 |
| Counterexample | 推翻或限制主张的证据 | 同样蓝框在只读页不表示选中 |
| Procedural | 可复用步骤或技能 | 审批前先核对金额与币种 |
| Preference | 用户/项目偏好 | 默认不发送外部邮件 |
| Policy | 强制约束 | 金额超过阈值必须双人批准 |
| Guide | 跨任务稳定领域知识 | 页面导航、对象作用、规则 |
| World Model | 可执行局部机制 | 状态转移、观察、终局和规划接口 |

### 11.2 主张图

每条认知不是孤立文本，而是一个 `Claim`：

```text
Claim
├── scope：租户/项目/环境/版本/对象/时间
├── statement：自然语言与可选结构化表达
├── evidence：支持证据
├── counterevidence：反例
├── depends_on：依赖主张
├── confidence：校准置信度
├── status：proposed/supported/accepted/disputed/refuted/retired
├── owner/reviewer
└── version lineage
```

### 11.3 晋升流程

```text
Observation
  → Candidate Fact/Hypothesis
  → Evidence accumulation
  → Conflict & scope check
  → Shadow use
  → Human/Policy review（按风险）
  → Accepted Guide/Procedure/Model
  → Runtime monitoring
  → Revise / Narrow / Refute / Retire
```

### 11.4 冲突、衰减与遗忘

- 同一范围内互斥主张创建显式 Conflict，不由模型静默覆盖。
- 依赖环境版本的知识在环境升级后自动降级为 `needs_revalidation`。
- 长期未验证、低价值或来源质量差的主张降低检索权重，但不自动删除审计历史。
- 用户偏好可随用户请求更正或删除；组织政策不能被 Agent 自行修改。
- 删除原始证据时，依赖主张必须标记来源不可再验证，或同步撤销。

### 11.5 跨 Agent 与跨项目共享

- Agent 可共享只读证据引用，但 Working Memory 默认隔离。
- 从项目知识发布到组织知识必须经过显式审核和范围检查。
- 共享资产带发布者、签名、许可证、数据来源和适用版本。
- 被污染或失效的资产可全局撤回，并查询影响过的 Run。
- 禁止把一个客户的原始证据或可识别记忆迁移到另一客户。

---

## 12. 可信执行、策略与恢复

### 12.1 Action Contract

每个有副作用的动作应具备：

```json
{
  "goal": "批准已核验订单 A102",
  "action": {"tool": "set_order_status", "args": {"id": "A102", "status": "approved"}},
  "risk": "R3",
  "preconditions": ["status=pending", "amount and currency verified"],
  "prediction": {
    "changes": ["A102.status=approved"],
    "invariants": ["amount unchanged", "other orders unchanged"]
  },
  "success_criteria": ["write accepted", "read-back status=approved"],
  "failure_criteria": ["duplicate side effect", "unexpected dialog", "amount changed"],
  "verify_with": ["response_schema", "read_after_write", "visual_diff"],
  "approval_scope": "this exact action and arguments",
  "idempotency_key": "...",
  "timeout_ms": 10000,
  "compensation": "return to pending if business system supports it"
}
```

### 12.2 核验器体系

| 核验器 | 适用对象 | 可信度 |
|---|---|---|
| Schema/类型 | API 响应和结构化状态 | 高但只验证格式 |
| Read-after-write | 数据库/API/业务对象 | 高，优先使用 |
| 不变量规则 | 金额、数量、权限、范围 | 高，领域定义 |
| 视觉 Diff | UI 局部变化 | 中，需屏蔽噪声 |
| DOM/A11y Diff | Web/桌面界面 | 中高，依赖可用性 |
| 时序核验 | 动画、流程、异步状态 | 中高，需观察窗口 |
| 语义模型 | 非结构化结果 | 中，必须允许不确定 |
| 交叉模型 | 高价值语义复核 | 中，不能视为独立事实源 |
| 人工确认 | 模糊或高风险结果 | 高但成本高 |

核验结果至少包括 `pass`、`deviation`、`inconclusive`、`system_error`，禁止把观察不足自动归为成功。

### 12.3 工具事务语义

每个 Tool Manifest 应声明：

- 风险级别与数据敏感级别；
- 是否只读、幂等、可撤销、可补偿；
- 是否支持 dry-run 和 read-back；
- 副作用边界和可能的延迟；
- 速率、成本和权限；
- 必须使用的核验器；
- 可执行环境与出站网络需求。

### 12.4 风险分级

| 级别 | 示例 | 默认控制 |
|---|---|---|
| R0 | 查看、搜索、inspect | 自动执行并记录 |
| R1 | 沙箱草稿、临时本地变更 | 精简契约，自动执行 |
| R2 | 可读回、可补偿的有限业务写入 | 完整契约 + 策略 + 自动读回 |
| R3 | 外部通信、审批、批量变更、下单 | 具体参数级批准 + 强核验 |
| R4 | 删除、转账、权限变更、不可逆操作 | 默认禁止，由外部控制面显式授权 |

### 12.5 偏差后的恢复顺序

1. 等待配置的稳定窗口并重新观察；
2. 核对工具返回与实际读回；
3. 回看动作前后原始证据和过渡事件；
4. 分类为环境延迟、工具错误、权限拒绝、模型误解或真实外部变化；
5. 使依赖计划失效；
6. 缩小或推翻相关主张；
7. 选择重试、补偿、重新规划、修复模型、请求批准或接管；
8. 达到预算/重试上限后安全停止并导出复现包。

---

## 13. 按需世界模型体系

### 13.1 定义

世界模型是对某个明确范围内环境状态、动作、观察和目标的可执行或可计算假设。它是认知资产的一种，不是 Agent 必须维护的完整现实副本。

### 13.2 支持的模型形态

| 形态 | 适用环境 | 输出 |
|---|---|---|
| 确定性状态机 | 规则明确的 UI/游戏/流程 | 精确状态转移 |
| 规则 DSL | 高安全、禁止任意代码 | 受限条件与效果 |
| Python 局部模型 | 复杂但可离散机制 | 自由结构、可测试代码 |
| 概率场景树 | 隐信息、延迟、随机结果 | 概率分支与风险界 |
| 因果图 | 干预与机制发现 | 变量、关系与反事实 |
| 约束模型 | 排程、资源、合规 | 可行域与违规解释 |
| 混合组合模型 | 复杂生产环境 | 多模型按边界组合 |

### 13.3 最小接口

```python
class PartialWorldModel(Protocol):
    manifest: WorldModelManifest

    def init_state(self, observation: Observation) -> State: ...
    def transition(self, state: State, action: Action) -> StateDistribution: ...
    def observe(self, state: State) -> PredictedObservation: ...
    def outcome(self, state: State) -> Outcome: ...

    def allowed_actions(self, state: State) -> list[Action]: ...
    def state_hash(self, state: State) -> str: ...
    def heuristic(self, state: State, goal: Goal) -> float: ...
```

`StateDistribution` 和 `PredictedObservation` 必须允许 Unknown、区间或概率；只有确定性环境才要求单一结果。

### 13.4 触发策略

Meta Controller 计算建模收益：

```text
benefit =
  planning_horizon
  + real_action_risk
  + branching_factor
  + mechanism_reuse
  + repeated_prediction_failure
  + hypothesis_conflict
  + observability_and_determinism
  - generation_cost
  - validation_cost
  - expected_model_staleness
```

第一阶段采用可解释规则；积累足够真实数据后，可训练一个只决定 `build/repair/use/bypass/probe/stop` 的策略模型，但其上线仍受离线门禁约束。

### 13.5 模型生命周期

```text
Requested
  → Drafted/Imported
  → Static Checked
  → Replay Tested
  → Property Tested
  → Shadow Predicting
  → Approved/Activated
  → Monitored
  → Repaired / Scope-Narrowed / Suspended
  → Retired / Revoked
```

### 13.6 验证要求

- 静态检查：接口、禁止依赖、复杂度、系统调用；
- 历史回放：真实动作序列、状态、观察和终局；
- 性质测试：领域不变量和边界；
- 变形测试：布局、顺序、非关键视觉变化；
- 反事实测试：未执行动作的合理性与越界检查；
- 影子预测：不参与控制，仅比较未来真实结果；
- 漂移监控：按时间、环境版本和数据切片统计。

历史匹配不是充分条件。激活还要求模型覆盖当前动作、适用范围匹配、无严重不变量违规，并通过影子期或人工批准。

### 13.7 分层组合

复杂环境不由单个巨型模型承担：

```text
UI Navigation Model
  + Business State Model
  + Permission Model
  + Resource/Cost Model
  + Risk Model
  → Composite Planner View
```

组合器必须解决状态映射、版本兼容、冲突优先级和不确定性传播。任一关键子模型失效时，组合计划同步失效。

### 13.8 规划

按模型类型插件化支持 BFS、A*、束搜索、MCTS、约束求解、工作流规划和模型预测控制。规划必须受以下约束：

- 最大深度、展开节点、时间和成本；
- 风险动作不能在仿真通过后跳过现实批准；
- 计划每一步绑定模型版本与依赖主张；
- 现实执行逐步核验，禁止因内部模拟成功而批量盲执行。

### 13.9 沙箱

- 默认无网络、无业务凭证、无宿主目录；
- 根文件系统只读，仅提供每次运行独立的临时目录；
- 限制 CPU、内存、进程、文件、输出和墙钟时间；
- 模块、系统调用和数据输入 allowlist；
- 代码哈希、运行日志、资源消耗和异常全部入审计；
- 生产使用 rootless 容器、microVM 或等价强隔离；开发子进程不得视为生产安全边界。

---

## 14. 多 Agent 与人机协作

### 14.1 原则

VastaCore 不把多 Agent 当作默认答案。只有当角色隔离、并行探索或独立复核带来明确收益时才启用。

### 14.2 共享边界

| 资产 | 默认共享范围 |
|---|---|
| 原始证据 | 项目内按权限只读共享 |
| Working Memory | 单 Agent/单任务私有 |
| 假设 | 可订阅，但需保留提出者和证据 |
| Guide/Procedure | 经审核后发布到项目/组织 |
| Policy | 由控制面管理，Agent 只读 |
| World Model | 经验证、签名和范围授权后共享 |
| 用户偏好 | 仅用户授权的 Agent 可用 |

### 14.3 角色协作

- Actor：提出并执行动作；
- Observer：独立采集或确认环境状态；
- Verifier：执行核验，不应默认与 Actor 共用同一自由判断；
- Builder：构建或修复局部世界模型；
- Supervisor：管理预算、循环、偏差升级和安全停止；
- Human Approver：批准明确范围内的高风险动作；
- Curator：审核知识和认知资产发布。

所有委派都生成父子任务关系、输入证据范围、预算和输出契约，不能通过共享工作区隐式获得无限权限。

---

## 15. 评测、持续学习与认知资产 CI/CD

### 15.1 评测层级

1. 单元测试：数据模型、状态机、存储、核验器、策略；
2. 协议测试：模型/工具/环境/存储适配器；
3. 轨迹回放：不执行真实副作用的离线重放；
4. VastaLab：隐藏规则、布局、噪声和偏差的可控任务；
5. 场景基准：GUI、视频、游戏或工业解决方案包；
6. 影子生产：观察真实流量但不控制；
7. 小流量灰度：有限用户、工具和风险等级；
8. 全量生产：持续漂移和事故监控。

### 15.2 消融设计

| 组别 | 证据 | 分层认知 | 执行契约 | 世界模型 | 用途 |
|---|---:|---:|---:|---:|---|
| A Baseline | 当前观察 | 普通摘要 | 否 | 否 | 对照 |
| B Evidence | 无损 | 普通摘要 | 否 | 否 | 测证据价值 |
| C Cognition | 无损 | 是 | 否 | 否 | 测认知生命周期 |
| D Contract | 无损 | 是 | 是 | 否 | 测可信执行 |
| E Model | 无损 | 是 | 否 | 始终/按需 | 测模型净收益 |
| F Full | 无损 | 是 | 是 | 按需 | 测完整系统 |

固定模型、推理档、任务版本、预算和种子；报告均值、方差、置信区间、成本和失败分类，禁止只展示最佳一次。

### 15.3 反馈飞轮

```text
生产/评测轨迹
  → 失败聚类
  → 最小复现任务
  → 新核验器/策略/主张/世界模型候选
  → 离线回放
  → 私有任务评测
  → 影子运行
  → 灰度发布
  → 指标与漂移监控
  → 保留、修订或回滚
```

### 15.4 资产发布门

每个 Prompt、Verifier、Policy、Procedure 和 World Model 都要有：

- 版本、所有者、变更原因；
- 输入/输出 Schema 和适用范围；
- 测试集与结果；
- 安全影响和数据依赖；
- 兼容版本；
- 影子/灰度状态；
- 回滚版本和退役条件。

这形成 VastaCore 的“认知资产 CI/CD”。

---

# 第三部分：生产级系统设计

## 16. 总体技术架构

### 16.1 逻辑架构

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Clients: Host Agents / Apps / Operators / Auditors / Domain Experts     │
└───────────────────────────────────┬──────────────────────────────────────┘
                                    │ SDK / API / Proxy / Event
┌───────────────────────────────────▼──────────────────────────────────────┐
│                         CONTROL PLANE                                   │
│ Tenant · Identity · Policy · Autonomy · Registry · Release · Quota     │
│ Approval · Retention · Billing Meter · Fleet · Configuration            │
└───────────────────────────┬──────────────────────┬───────────────────────┘
                            │ desired state         │ signed assets
┌───────────────────────────▼──────────────────────▼───────────────────────┐
│                          RUNTIME DATA PLANE                              │
│                                                                          │
│ API Gateway / SDK Runtime                                                │
│       ↓                                                                  │
│ Run Coordinator → Context Builder → Model Router → Decision Engine       │
│       ↓                                  ↓                               │
│ Supervisor / Budget / Checkpoint      Meta Controller                    │
│       ↓                                  ↓ optional                      │
│ Contract → Policy → Approval → Tool Gateway    World Model Lab Client    │
│       ↓                                                                  │
│ Environment / Business Tools / GUI / Device                              │
└──────────────┬──────────────────────────┬────────────────────────────────┘
               │ events/artifacts          │ model jobs
┌──────────────▼──────────────────┐  ┌────▼───────────────────────────────┐
│ EVIDENCE & COGNITION PLANE      │  │ WORLD MODEL EXECUTION PLANE       │
│ Event Store · Artifact CAS      │  │ Build · Static Check · Sandbox    │
│ Derived Index · Claim Graph     │  │ Replay · Property Test · Plan     │
│ Memory/Skill/Model Registry     │  │ Shadow · Drift · Version          │
└──────────────┬──────────────────┘  └────────────────────────────────────┘
               │
┌──────────────▼───────────────────────────────────────────────────────────┐
│ EXPERIENCE & ASSURANCE                                                  │
│ Replay Console · Domain Studio · Evaluation · Audit · OTel · Reporting  │
└──────────────────────────────────────────────────────────────────────────┘
```

### 16.2 控制面与数据面边界

**控制面保存：**

- 租户、项目、环境和用户配置；
- 策略、自治等级、审批路由和配额；
- 插件、提示、核验器、世界模型的元数据和发布状态；
- 集群与数据面的健康、版本及聚合指标。

**数据面处理：**

- 原始观察、任务上下文和模型请求；
- 实际工具调用和环境状态；
- 客户原始证据、记忆和认知资产；
- 世界模型的输入与运行结果。

Hybrid 部署允许控制面不接触客户原始证据，只接收签名版本、策略状态和去标识聚合指标。

### 16.3 核心组件

| 组件 | 职责 |
|---|---|
| API Gateway | 身份、限流、版本、租户路由、请求审计 |
| Run Coordinator | 任务生命周期、状态机、事件顺序和取消 |
| Supervisor | 预算、循环检测、检查点、故障分类和升级 |
| Context Builder | 按预算选择目标、记忆、证据和策略上下文 |
| Model Router | 模型能力探测、路由、重试、降级和成本记录 |
| Evidence Service | Artifact、派生物、时空索引和完整性 |
| Cognition Service | Claim 图、记忆、冲突、晋升和共享 |
| Contract Engine | 生成/模板化动作预期与核验计划 |
| Policy Engine | 风险、授权、自治等级和禁止条件 |
| Approval Service | 参数级批准、过期、撤回和双人审批 |
| Tool Gateway | 工具清单、幂等、读回、补偿和凭证代理 |
| Meta Controller | 决定直接推理、探测、建模、修复或停止 |
| Model Lab | 世界模型构建、回放、性质测试、规划和漂移 |
| Evaluation Service | 任务、运行矩阵、指标、门禁和报告 |
| Replay Console | 证据时间线、Diff、依赖、复现和事故调查 |
| Domain Studio | 状态 Schema、不变量、核验器和知识审核 |

### 16.4 建议仓库结构

```text
VastaCore/
├── packages/
│   ├── vastacore-sdk/
│   ├── vasta-runtime/
│   ├── vasta-protocols/
│   ├── vasta-storage/
│   ├── vasta-cognition/
│   ├── vasta-contracts/
│   ├── vasta-policy/
│   ├── vasta-model-lab/
│   ├── vasta-eval/
│   └── vasta-adapters/
├── services/
│   ├── control-plane/
│   ├── runtime-api/
│   ├── artifact-worker/
│   ├── model-lab-worker/
│   └── audit-exporter/
├── apps/
│   ├── console/
│   └── domain-studio/
├── solutions/
│   ├── vastalab/
│   ├── gui/
│   ├── video/
│   └── game/
├── schemas/
├── plugins/
├── examples/
├── tests/
├── docs/
└── deploy/
```

---

## 17. 数据模型与事件语义

### 17.1 核心实体

| 实体 | 关键字段 | 说明 |
|---|---|---|
| Tenant/Project | 身份、区域、策略、密钥、配额 | 隔离与治理边界 |
| AgentDefinition | 模型、提示、工具、记忆和版本 | 可部署的 Agent 定义 |
| Environment | 类型、版本、能力、风险 | 运行环境声明 |
| Run/Episode | 任务、状态、预算、配置快照 | 完整运行与可重置单元 |
| Event | 类型、序号、因果父项、时间、签名 | 追加式事实 |
| Observation | 类型、Artifact、可用动作、环境状态 | 决策/过渡/终局等观察 |
| Artifact | URI、哈希、MIME、大小、分类、保留 | 原始载荷 |
| DerivedAsset | 源、变换、模型版本、质量 | OCR/摘要/状态/embedding |
| Claim | 内容、范围、证据、反例、依赖、状态 | 认知图节点 |
| Plan/PlanStep | 目标、动作、依赖、状态 | 可失效计划 |
| ActionContract | 预期、不变量、风险、核验 | 行动契约 |
| Execution | 请求、响应、凭证范围、副作用 | 实际动作 |
| Verification | 检查、Diff、判定、置信度 | 动作对账 |
| Approval | 策略、请求、决策、人/系统 | 授权记录 |
| WorldModel | 清单、代码/DSL、范围、信任分 | 局部机制资产 |
| Evaluation | 任务矩阵、配置、指标、结论 | 评测记录 |
| Release | 资产版本、环境、门禁、灰度 | 发布状态 |

### 17.2 关键事件

```text
run.created / started / paused / resumed / completed / failed / cancelled
episode.started / reset / completed
observation.decision / transition / terminal / external
artifact.captured / derived / archived / deletion_requested / deleted
claim.proposed / supported / accepted / disputed / refuted / retired
memory.published / revoked
plan.created / step_ready / invalidated / replanned
action.proposed / contracted / policy_denied / approval_requested
action.approved / executed / failed / compensated
verification.passed / deviated / inconclusive / errored
world_model.requested / drafted / validated / shadowed / activated
world_model.suspended / repaired / scope_narrowed / retired / revoked
evaluation.started / completed / gate_passed / gate_failed
release.created / promoted / rolled_back
incident.opened / mitigated / closed
```

### 17.3 一致性与幂等

- 每个 Run 内事件具有单调序号和稳定事件 ID。
- 动作执行使用幂等键；重复请求必须返回原执行结果或明确拒绝。
- Artifact 在事件引用前完成持久写入与哈希校验。
- 元数据采用事务写；大对象写入失败不得产生“已捕获”事件。
- 异步派生使用至少一次投递，因此 worker 必须幂等。
- 事件消费者保存 checkpoint，并能从历史重建投影。
- 跨服务不追求分布式强事务，使用 outbox/inbox 和补偿流程。

### 17.4 Schema 版本

- 所有 API、事件、插件和 Artifact Manifest 均含版本。
- 小版本只增加可选字段；破坏性变更进入新主版本。
- 提供事件投影迁移器，不原地重写历史事实。
- 支持 N-1 客户端兼容窗口；弃用至少经历告警、迁移、只读和移除四阶段。

---

## 18. API、SDK 与扩展协议

### 18.1 基础协议

```python
class EnvironmentAdapter(Protocol):
    async def reset(self, seed: int | None = None) -> Observation: ...
    async def observe(self) -> Observation: ...
    async def execute(self, action: Action) -> list[Observation]: ...
    async def status(self) -> EnvironmentStatus: ...

class ModelAdapter(Protocol):
    capabilities: ModelCapabilities
    async def generate(self, request: ModelRequest) -> ModelResponse: ...

class ToolAdapter(Protocol):
    manifest: ToolManifest
    async def dry_run(self, action: Action) -> DryRunResult: ...
    async def execute(self, action: Action, idempotency_key: str) -> ToolResult: ...
    async def read_back(self, action: Action) -> Observation: ...
    async def compensate(self, execution: Execution) -> CompensationResult: ...

class Verifier(Protocol):
    manifest: VerifierManifest
    async def verify(self, contract: ActionContract, evidence: EvidenceSet) -> Verification: ...
```

### 18.2 插件类型

- Model Adapter；
- Environment Adapter；
- Tool Adapter；
- Artifact Processor；
- State Extractor；
- Context Selector；
- Verifier；
- Policy Pack；
- Planner；
- World Model Runtime；
- Evaluation Pack；
- Storage Backend；
- Approval Provider；
- Exporter。

### 18.3 插件清单

每个插件声明：名称、版本、协议版本、权限、网络、文件、密钥、资源、数据分类、输入输出 Schema、兼容环境、签名、许可证、测试结果和维护者。

### 18.4 服务 API

```text
POST   /v1/runs
GET    /v1/runs/{id}
POST   /v1/runs/{id}/pause|resume|cancel
GET    /v1/runs/{id}/timeline
GET    /v1/runs/{id}/checkpoint
GET    /v1/artifacts/{id}
POST   /v1/artifacts/{id}/inspect
POST   /v1/artifacts/{id}/derive
GET    /v1/claims
POST   /v1/claims/{id}/review|revise|retire
GET    /v1/actions/{id}/contract
POST   /v1/approvals/{id}/decision
GET    /v1/world-models/{id}
POST   /v1/world-models/{id}/validate|shadow|activate|suspend
POST   /v1/evaluations
GET    /v1/evaluations/{id}/report
POST   /v1/releases
POST   /v1/releases/{id}/promote|rollback
GET    /v1/audit/exports/{id}
```

### 18.5 渐进接入方式

1. SDK 原生接入；
2. 现有编排器 middleware/hook；
3. Tool/API Proxy，无需修改 Agent 主循环；
4. Sidecar，与单个 Agent 进程同部署；
5. 集中 Runtime，托管完整运行循环；
6. 只导入现有轨迹，先使用 Replay/Evaluation。

---

## 19. 技术选型与演进

### 19.1 Foundation/Community

| 区域 | 推荐 |
|---|---|
| 语言 | Python 3.12+，类型检查 |
| Schema | Pydantic + JSON Schema + OpenAPI |
| 本地元数据 | SQLite |
| 本地 Artifact | 内容寻址文件存储 |
| CLI | Typer |
| API | FastAPI |
| 测试 | pytest + Hypothesis + Playwright |
| 回放 | 自包含 HTML + 轻量 Web Console |
| 可观察性 | 结构化日志 + OpenTelemetry SDK |

### 19.2 Team/Enterprise

| 区域 | 推荐 |
|---|---|
| 元数据 | PostgreSQL，JSONB，行级/应用层租户隔离 |
| Artifact | S3 兼容对象存储，版本和生命周期策略 |
| 向量 | pgvector 起步，规模证明后再独立 |
| 队列 | 先使用成熟托管队列/数据库队列，吞吐证明后再引入 Kafka |
| 缓存 | Redis 类缓存，仅用于可重建状态，不存唯一事实 |
| 身份 | OIDC/SAML，SCIM，工作负载身份 |
| 策略 | 内置规则引擎；企业可对接 OPA 类外部策略 |
| 沙箱 | rootless 容器或 microVM，独立 worker 池 |
| 部署 | 容器化；Kubernetes 只在团队规模和隔离需求成立后采用 |

### 19.3 明确不提前引入

- 未证明吞吐前不引入 Kafka 与复杂微服务；
- 未证明检索瓶颈前不引入独立向量数据库；
- 未证明多 Agent 收益前不把固定角色团队写死在架构；
- 未证明学习收益前不训练 Meta Controller；
- 未证明市场需求前不建设公开插件交易市场。

---

## 20. 部署、扩展与容量设计

### 20.1 工作负载分类

| 工作负载 | 特征 | 调度策略 |
|---|---|---|
| 交互 Runtime | 低延迟、有状态、等待外部环境 | Run 亲和、检查点、优先级 |
| Artifact 处理 | CPU/GPU、可异步、可重试 | 队列、批处理、内容哈希去重 |
| 模型调用 | 外部延迟、成本和限流 | 路由、预算、熔断、缓存 |
| 世界模型验证 | 不可信代码、资源波动 | 隔离池、严格配额、短生命周期 |
| 评测 | 批量、可重复、成本高 | 独立队列、预算窗口、可抢占 |
| Replay/Audit | 读取密集、权限敏感 | 只读投影、按需取回、审计 |

### 20.2 初始容量目标

Team Beta 的建议设计目标：

- 单租户同时运行 100 个活跃 Run；
- 单 Run 100,000 个事件、10,000 个 Artifact；
- 每日百万级事件写入；
- Artifact 大小由策略限制，视频采用分段和清单；
- 历史时间线按 Run/序号分页，避免全量加载；
- 派生 worker 可水平扩展；
- 沙箱和交互 Runtime 使用不同资源池。

这些是容量设计目标，不是发布即承诺；实际 SLO 需通过负载测试校准。

### 20.3 多区域与边缘

- Tenant 固定主数据区域，原始证据默认不跨区复制。
- 控制面使用去标识元数据管理多个区域数据面。
- 边缘节点负责采集、初筛、脱敏和低延迟核验。
- 中央侧只获取允许上传的派生物、策略和汇总指标。
- 跨区域资产发布必须检查数据来源、许可证和驻留约束。

---

## 21. 可靠性、SLO 与灾难恢复

### 21.1 服务等级目标

| 能力 | Team Beta | Enterprise 目标 |
|---|---:|---:|
| 控制面 API 月可用性 | 99.5% | 99.9% |
| Runtime API 月可用性 | 99.5% | 99.9% |
| 事件持久化成功率 | 99.99% | 99.999% |
| 写动作审计链完整率 | 100% | 100% |
| 策略/审批绕过 | 0 | 0 |
| 元数据写入 P95 | <200ms | <100ms（同区域） |
| 非模型编排开销 P95 | <500ms | <300ms |
| Console 时间线首屏 P95 | <3s | <2s |

模型和外部工具时延单独统计，不隐藏在平台 SLO 中。

### 21.2 故障策略

- Evidence Store 不可用：禁止执行新的写动作；可按策略允许只读观察。
- Policy/Approval 不可用：高风险动作 fail closed。
- 模型供应商不可用：切换兼容模型、降级规则路径或暂停。
- 派生服务不可用：原始证据仍入库，延后处理。
- Console 不可用：Runtime 继续记录，不影响核心执行。
- 世界模型沙箱不可用：绕过模型直接推理或暂停，不自动放宽安全。

### 21.3 备份与恢复

- PostgreSQL 连续备份与定期恢复演练；
- Artifact 跨可用区冗余，按数据驻留决定是否跨区域；
- 控制面配置、策略和资产注册表版本化；
- Enterprise 初始目标：元数据 RPO ≤ 5 分钟、RTO ≤ 1 小时；
- Artifact 的 RPO/RTO 按数据等级设置；
- 每季度执行恢复演练并记录实际恢复时间。

---

## 22. 安全、隐私与合规

### 22.1 威胁模型

- 页面、文档、图像 OCR 或工具返回中的提示注入；
- Agent 生成代码、第三方插件或模型包供应链攻击；
- 原始证据中的个人、财务、医疗或商业机密泄漏；
- 跨租户索引、缓存、日志或对象存储泄漏；
- 伪造核验结果、审批重放或审计事件篡改；
- 真实工具被 Replay/评测误调用；
- 错误认知晋升为组织知识并被大规模复用；
- 自动恢复循环放大成本或副作用；
- 控制面被攻破后下发恶意策略或插件。

### 22.2 身份与权限

- 人类用户：OIDC/SAML、MFA、SCIM 和会话策略；
- 工作负载：短期身份、最小权限、可轮换凭证；
- 授权：RBAC 管角色，ABAC 管租户、项目、数据分类、环境和操作；
- 原始证据、派生物、认知资产和聚合指标可使用不同权限；
- Break-glass 操作双人批准、限时并强审计；
- 服务间使用双向认证和明确受众 token。

### 22.3 数据保护

- 传输与静态加密；Enterprise 支持 BYOK/客户管理密钥；
- 字段、区域和 Artifact 级敏感分类；
- 边缘/客户 VPC 内脱敏，云侧最小上下文；
- 日志默认不记录模型密钥和原始敏感内容；
- 保留策略、法律保留、用户访问/删除请求和删除证明；
- 备份与向量索引同步执行删除策略。

### 22.4 提示注入防护

- 指令、可信配置、观察和不可信内容使用不同消息/数据通道；
- OCR/网页/文档中的“指令”只作为观察，不自动写入 Policy/Guide；
- 工具授权独立于模型文本；
- 记忆晋升需要证据、范围和审核；
- 高风险动作检查目标一致性与数据外泄模式；
- 使用攻击任务集持续回归，而非宣称彻底解决提示注入。

### 22.5 软件供应链与沙箱

- SBOM、锁定依赖、漏洞扫描、签名构建和可复现发布；
- 插件/模型包签名、权限清单、来源和撤销列表；
- 沙箱无业务凭证，网络默认关闭，资源硬限制；
- Replay 默认接 mock/deterministic adapter；连接真实工具需单独授权；
- 安全事件可按插件/资产版本查询影响范围并一键撤销。

### 22.6 合规路线

方案目标是提供合规所需控制与证据，不在未审计前宣称认证：

1. 数据盘点、分类、保留、访问和删除；
2. 变更管理、访问审查、日志和事故响应；
3. 供应商、模型和子处理方管理；
4. 安全开发生命周期、渗透测试和恢复演练；
5. 根据目标市场准备 SOC 2/ISO 27001 等审计；
6. 垂直行业再增加相应法律与监管评估。

---

## 23. 可观察性、运营与事故响应

### 23.1 三类遥测

- **系统遥测**：请求、队列、数据库、对象存储、沙箱、错误和资源；
- **Agent 遥测**：模型调用、token、上下文、动作、核验、重试、循环和成本；
- **认知遥测**：证据回看、主张晋升/推翻、世界模型覆盖、漂移和资产影响。

### 23.2 核心运营指标

- 活跃 Run、成功率、暂停和接管率；
- 动作数、重复动作、偏差、误阻断、漏检；
- 模型和工具 P50/P95/P99 延迟、错误率与成本；
- Artifact 增长、派生 backlog、冷存储和删除 backlog；
- 错误 Guide 存活时长、冲突未处理时长；
- 世界模型 build/repair/use/bypass 及净收益；
- 每个自治等级的事故率；
- 插件和资产版本的异常关联。

### 23.3 告警与运行手册

至少建立：

- Evidence 写入或哈希失败；
- 高风险动作缺失契约/批准；
- 偏差率、核验不确定率或循环次数异常；
- 特定模型/工具/插件错误突增；
- 沙箱越权、资源异常和网络尝试；
- 存储/队列容量和删除积压；
- 认知资产发布后任务质量下降；
- 租户隔离和权限拒绝异常。

每项告警必须有严重级别、值班责任、止损动作、调查查询和恢复验证。

### 23.4 事故闭环

```text
Detect
  → Freeze affected autonomy/assets
  → Preserve evidence
  → Identify first deviation and blast radius
  → Mitigate/rollback
  → Reproduce
  → Add regression task/policy/verifier
  → Validate and gradually restore
  → Postmortem and customer notice
```

---

# 第四部分：产品体验、垂直方案与生态

## 24. 开发者体验

### 24.1 十分钟首跑

```python
from vastacore import VastaRuntime, LocalProfile

runtime = VastaRuntime(
    profile=LocalProfile(root=".vasta"),
    model=model_adapter,
    environment=environment_adapter,
    policy=policy_pack,
)

result = await runtime.run(
    task="完成订单核验；任何金额或币种异常都停止",
    budget={"max_actions": 50, "max_model_calls": 100},
    autonomy="observe",
)
```

### 24.2 CLI

```text
vasta init
vasta run --task task.yaml
vasta inspect RUN_ID
vasta replay RUN_ID --offline
vasta eval eval-pack.yaml
vasta diff RUN_A RUN_B
vasta artifact verify ARTIFACT_ID
vasta model validate MODEL_ID
vasta release promote RELEASE_ID --to shadow
vasta audit export RUN_ID
```

### 24.3 文档体系

- 15 分钟 Quickstart；
- 从现有 Agent middleware 接入；
- 环境与工具适配教程；
- Action Contract 和 Verifier 指南；
- 世界模型安全与验证指南；
- 私有评测设计手册；
- 部署、升级、备份和事故手册；
- 端到端示例和反模式库。

### 24.4 开发者成功指标

- 首次本地运行 ≤ 15 分钟；
- 基础工具代理接入 ≤ 1 工程日；
- 完整环境适配器 ≤ 1–3 工程日；
- 一个失败 Run 定位首个偏差 ≤ 10 分钟；
- 示例与 API 版本同步率 100%。

---

## 25. Console 与 Domain Studio

### 25.1 Console 信息架构

| 模块 | 关键视图 |
|---|---|
| Overview | 成功、风险、成本、延迟、自治与趋势 |
| Runs | 列表、筛选、实时状态、暂停/接管 |
| Replay | 事件时间线、动作五段链、证据、Diff |
| Cognition | 主张图、证据、反例、冲突、版本、影响 |
| World Models | 范围、代码/DSL、回放、覆盖、漂移、版本 |
| Evaluations | 任务集、消融、切片、回归和发布门 |
| Policies | 风险、自治、审批、工具和数据策略 |
| Assets | 提示、核验器、技能、插件和发布状态 |
| Audit | 搜索、访问、导出、保留和签名校验 |
| Operations | 服务、队列、存储、成本、告警和事故 |

### 25.2 Replay 核心体验

- 左侧按因果而非纯时间展示事件；
- 中间显示动作前后原始观察和过渡帧；
- 右侧显示当时目标、记忆、假设、计划、契约和策略；
- 一键跳转首个偏差、首次错误认知和审批点；
- 任意派生结果可回到原始证据；
- 失败可一键复制为回归任务或最小复现包。

### 25.3 Domain Studio

领域专家可通过表单、示例和受限 DSL 定义：

- 业务实体与状态字段；
- 允许/禁止状态转移；
- 成功条件和不变量；
- 风险动作和批准路由；
- 核验读回与观察窗口；
- 知识晋升证据门槛；
- 世界模型可覆盖的确定性边界。

所有变更先运行历史回放和私有评测，再进入影子或灰度。

---

## 26. 垂直解决方案包

### 26.1 GUI/Computer Use Pack（首选商业楔子）

| 项目 | 内容 |
|---|---|
| 输入 | 截图、DOM/A11y、窗口、键鼠动作、网络/API 读回 |
| 关键能力 | 跨页面记忆、区域回看、弹窗/延迟识别、表单事务 |
| 核验 | DOM + API 读回 + 视觉 Diff + 不变量 |
| 世界模型 | 页面状态机、导航图、表单依赖、业务流程 |
| 价值 | 降低重复操作、误提交和长任务排障成本 |
| 边界 | 不把纯视觉作为唯一信号；生产写操作需外部权限 |

### 26.2 Video/Industrial Pack

| 项目 | 内容 |
|---|---|
| 输入 | 视频、音频、传感器、事件和设备日志 |
| 关键能力 | 时间片寻址、异常前后窗口、多模态对齐 |
| 核验 | 规则阈值、时序事件、交叉传感器、人工复核 |
| 世界模型 | 工序状态、设备模式、因果/约束模型 |
| 价值 | 异常复核、根因追溯、可审计处置建议 |
| 边界 | 首期仅建议/影子，不直接控制安全关键设备 |

### 26.3 Game/Simulation Pack

| 项目 | 内容 |
|---|---|
| 输入 | 截图、游戏事件、可用动作、回合/动画状态 |
| 关键能力 | 规则发现、跨关卡记忆、隐藏信息假设 |
| 核验 | 历史回放、终局、资源与合法动作 |
| 世界模型 | 确定性规则、概率对手模型、搜索 |
| 价值 | 研究、评测、训练辅助和策略解释 |
| 边界 | 隐信息与对抗策略不能强行确定性化 |

### 26.4 Embodied/Robotics Pack（长期）

| 项目 | 内容 |
|---|---|
| 输入 | 相机、深度、位置、力觉、设备状态 |
| 关键能力 | 时空证据、动作安全域、实时中止 |
| 核验 | 传感器、不变量、控制器反馈、数字孪生 |
| 世界模型 | 动力学局部模型、约束、概率状态估计 |
| 价值 | 高成本试错前的模拟和审计 |
| 边界 | 必须与认证控制器和硬件安全回路分离 |

### 26.5 垂直包选择门槛

一个新垂直包只有同时满足以下条件才进入产品路线：

- 有 3 个以上同类设计伙伴；
- 核心平台能力能覆盖 70% 以上需求；
- 能定义可靠的状态读回或核验信号；
- 有可量化的错误成本或效率价值；
- 不要求重写核心数据和执行语义；
- 有明确的数据授权和安全边界。

---

## 27. 扩展生态与开放标准

### 27.1 扩展生命周期

```text
Scaffold
  → Local Contract Tests
  → Permission Review
  → Compatibility Matrix
  → Signature
  → Private Registry
  → Verified Publisher
  → Optional Public Distribution
  → Monitor / Revoke / Deprecate
```

### 27.2 可信注册表

注册表不是简单插件列表。每个资产应展示：

- 来源与维护者；
- 权限和数据访问；
- 支持协议/环境/模型版本；
- 测试与安全扫描；
- 真实运行统计和已知限制；
- 撤销和最后维护时间；
- 许可证及训练/生成数据声明。

### 27.3 开放协议候选

- Observation/Event Envelope；
- Artifact Provenance Manifest；
- Action Contract；
- Tool Transaction Manifest；
- Claim/Cognitive Asset Manifest；
- Partial World Model Manifest；
- Evaluation Pack；
- Autonomy Grant。

协议先在 VastaCore 内稳定，再考虑独立规范；不应在实现证据不足时过早标准化。

### 27.4 生态壁垒

长期壁垒不是代码数量，而是：

1. 跨模型、环境和工具的可靠性数据；
2. 失败到回归资产的闭环；
3. 经验证的领域核验器和局部模型；
4. 与 IAM、存储、监控、审批和工具生态的深度集成；
5. 开放协议带来的互操作和分发网络效应；
6. 客户积累的私有认知资产及其治理体系。

---

## 28. 商业定位与市场验证

### 28.1 首要定位

> “为生产 Agent 提供可回放证据链、可信执行和可测试认知资产的可靠性平台。”

避免用“AGI 世界模型操作系统”作为早期主叙事，因为它难以验证、客户理解成本高且容易扩大承诺。

### 28.2 理想客户画像

- 已有 Agent PoC 或内部上线计划；
- 工作流超过 10 步，涉及多页面、多工具或异步状态；
- 错误具有真实成本，需要审计或人工批准；
- 团队已有模型/编排能力，但缺少排障、核验和治理；
- 愿意提供历史失败轨迹或影子环境进行量化验证。

### 28.3 Land-and-expand

```text
免费/开源本地 Replay
  → 团队共享评测与故障分析
  → 高风险工具的 Contract/Policy
  → 集中 Runtime 与企业治理
  → 私有数据面和合规
  → 领域认知资产与世界模型
  → 跨团队标准和生态
```

### 28.4 定价假设

正式价格需用户研究；可测试的计量维度包括：

- Team 按席位 + 活跃项目；
- Runtime 按受管 Run/动作或计算量；
- Evidence 按存储与派生处理；
- Enterprise 按年度平台许可、数据面和支持等级；
- Evaluation/Model Lab 按批量作业计算；
- 垂直解决方案与专业服务单独计价。

定价不能鼓励客户关闭安全记录或核验，因此必要审计链不应按事件逐条高价收费。

### 28.5 商业验证指标

- 设计伙伴数与活跃率；
- 接入时间和首个价值时间；
- 排障平均时间降低；
- 重复/错误动作减少；
- 高风险偏差发现率；
- 从 observe-only 升级到 enforce 的比例；
- 试点转付费率、扩展团队数和净收入留存；
- 单客户推理/存储/支持成本和毛利。

---

# 第五部分：完整需求、交付与治理

## 29. 功能需求清单

优先级定义：Must = 完整产品必备；Should = 生产成熟度重要；Could = 生态/高级增强。路线图中的阶段决定实现时间，不能把 Must 误解为一次性全部开发。

### 29.1 接入与运行

| ID | 级别 | 需求 |
|---|---|---|
| FR-001 | Must | 提供版本化 Model、Environment、Tool、Storage、Verifier 协议。 |
| FR-002 | Must | 支持 SDK、HTTP、middleware、proxy 和 sidecar 接入。 |
| FR-003 | Must | 自动探测模型视觉、结构化输出、工具、上下文和流式能力。 |
| FR-004 | Must | Run 支持启动、暂停、恢复、取消、检查点和预算。 |
| FR-005 | Must | 支持决策、过渡、终局、重置和外部观察。 |
| FR-006 | Must | 支持模型路由、超时、重试、熔断、降级和成本记录。 |
| FR-007 | Should | 支持长任务跨进程/节点恢复。 |
| FR-008 | Should | 支持定时、事件触发和批量 Run。 |
| FR-009 | Could | 支持实时流式环境和边缘节点协同。 |

### 29.2 证据与派生

| ID | 级别 | 需求 |
|---|---|---|
| FR-010 | Must | 保存全部关键原始观察和工具原始响应。 |
| FR-011 | Must | Artifact 具有哈希、来源、类型、大小、时间、分类和保留策略。 |
| FR-012 | Must | 派生物可回链源 Artifact、变换和版本。 |
| FR-013 | Must | 支持时间、动作、事件、区域、对象和业务实体检索。 |
| FR-014 | Must | 支持图像 inspect、crop、pixel/color read 和并排 Diff。 |
| FR-015 | Should | 支持视频时间窗、音频片段和多模态对齐。 |
| FR-016 | Should | 支持按需 OCR、ASR、摘要、状态抽取和 embedding。 |
| FR-017 | Must | 支持热温冷、法律保留、删除请求和删除证明。 |
| FR-018 | Must | 原始证据权限可独立于派生物和聚合指标。 |
| FR-019 | Could | 支持证据签名和第三方独立验证。 |

### 29.3 认知资产

| ID | 级别 | 需求 |
|---|---|---|
| FR-020 | Must | 支持 Working、Episodic、Fact、Hypothesis、Counterexample、Guide、Procedure、Preference 和 Policy。 |
| FR-021 | Must | 每条主张含范围、证据、反例、依赖、置信度、版本和状态。 |
| FR-022 | Must | 支持创建、修订、晋升、争议、缩小范围、推翻和退役。 |
| FR-023 | Must | 互斥主张生成显式冲突，不静默覆盖。 |
| FR-024 | Must | 依赖主张失效时标记受影响计划和资产。 |
| FR-025 | Must | Context Builder 按目标、相关性、风险和预算装配上下文。 |
| FR-026 | Should | 支持环境升级后的批量重新验证和认知衰减。 |
| FR-027 | Must | 跨 Agent/项目/组织共享需要显式发布与权限。 |
| FR-028 | Should | 支持领域专家审核和批量影响分析。 |
| FR-029 | Could | 支持认知图查询与可视化分析。 |

### 29.4 可信执行

| ID | 级别 | 需求 |
|---|---|---|
| FR-030 | Must | 所有状态改变型动作在执行前形成 Action Contract。 |
| FR-031 | Must | 契约含前置、预期变化、不变量、成功/失败条件、核验器和超时。 |
| FR-032 | Must | 工具清单声明风险、幂等、读回、补偿、权限和副作用。 |
| FR-033 | Must | 策略结果支持允许、拒绝、请求批准和降级。 |
| FR-034 | Must | 批准绑定动作、参数、范围、时限和批准者。 |
| FR-035 | Must | 执行后自动采集观察并运行组合核验器。 |
| FR-036 | Must | 核验支持 pass、deviation、inconclusive 和 system_error。 |
| FR-037 | Must | 偏差使依赖计划失效并进入有界恢复。 |
| FR-038 | Should | 支持 dry-run、幂等、补偿和事务批次。 |
| FR-039 | Should | 自治等级可按环境、工具、操作和数据范围动态调整。 |

### 29.5 世界模型与规划

| ID | 级别 | 需求 |
|---|---|---|
| FR-040 | Must | Meta Controller 记录 build/use/repair/bypass/probe/stop 决策及原因。 |
| FR-041 | Must | 支持规则 DSL 与受限 Python 局部模型。 |
| FR-042 | Should | 支持概率、因果、约束和组合模型。 |
| FR-043 | Must | 模型声明范围、假设、Unknown、覆盖、版本和依赖。 |
| FR-044 | Must | 执行静态、回放、性质和影子测试。 |
| FR-045 | Must | 模型有 candidate/shadow/active/suspended/retired/revoked 生命周期。 |
| FR-046 | Must | 生成代码在隔离、限时、限资源、默认无网络的沙箱运行。 |
| FR-047 | Must | 规划受深度、节点、时间、成本和风险约束。 |
| FR-048 | Must | 现实执行逐步核验，偏差立即暂停模型计划。 |
| FR-049 | Should | 支持模型组合、修复、版本比较、漂移与影响分析。 |

### 29.6 多 Agent 与人机

| ID | 级别 | 需求 |
|---|---|---|
| FR-050 | Must | 委派任务必须声明输入范围、权限、预算和输出契约。 |
| FR-051 | Must | Working Memory 默认私有，已验证知识显式发布。 |
| FR-052 | Must | 人类可暂停、接管、批准、更正和撤销。 |
| FR-053 | Must | Supervisor 检测循环、预算超限和持续偏差。 |
| FR-054 | Should | 支持 Actor、Observer、Verifier、Builder、Curator 等可配置角色。 |
| FR-055 | Should | 支持独立模型或人工复核，但保留各自证据来源。 |
| FR-056 | Could | 支持并行探索与候选世界模型竞赛。 |

### 29.7 回放、评测与发布

| ID | 级别 | 需求 |
|---|---|---|
| FR-060 | Must | 展示完整因果时间线和动作前后证据。 |
| FR-061 | Must | 派生物、记忆、模型和策略可回到当时版本。 |
| FR-062 | Must | 失败 Run 可导出为最小复现包和回归任务。 |
| FR-063 | Must | 评测固定任务、模型、提示、预算、策略、种子和代码。 |
| FR-064 | Must | 支持消融、数据切片、多种子、成本和失败分类。 |
| FR-065 | Must | 资产发布支持测试、影子、灰度、提升和回滚。 |
| FR-066 | Should | 支持历史轨迹离线评估新策略/核验器/模型。 |
| FR-067 | Should | 支持漂移、回归和资产影响告警。 |
| FR-068 | Must | 支持 JSON/HTML 和企业审计导出。 |
| FR-069 | Could | 支持跨模型/环境公开或私有排行榜。 |

### 29.8 企业控制面

| ID | 级别 | 需求 |
|---|---|---|
| FR-070 | Must | 支持租户、项目、环境、用户和服务身份隔离。 |
| FR-071 | Must | 支持 RBAC/ABAC、OIDC/SAML、SCIM 和审计日志。 |
| FR-072 | Must | 支持配额、预算、速率、并发和成本归集。 |
| FR-073 | Must | 支持数据分类、驻留、保留、法律保留和删除。 |
| FR-074 | Should | 支持 BYOK、客户自管数据面和 air-gapped 部署。 |
| FR-075 | Must | 策略、提示、插件和模型资产版本化并可回滚。 |
| FR-076 | Must | 支持健康、告警、备份、恢复和事故管理。 |
| FR-077 | Should | 支持组织级自治等级和风险预算。 |
| FR-078 | Should | 支持用量、计费和成本优化分析。 |
| FR-079 | Could | 支持跨区域数据面和边缘设备编排。 |

### 29.9 扩展生态

| ID | 级别 | 需求 |
|---|---|---|
| FR-080 | Must | 插件清单包含权限、数据、网络、资源、兼容和签名。 |
| FR-081 | Must | 提供脚手架、协议测试和本地开发工具。 |
| FR-082 | Must | 支持私有注册表、版本锁定、撤销和弃用。 |
| FR-083 | Should | 支持验证发布者、安全扫描和兼容矩阵。 |
| FR-084 | Could | 支持公开发现、评分和商业分发。 |
| FR-085 | Should | 开放核心事件与契约 Schema，提供迁移策略。 |

---

## 30. 非功能需求

| ID | 类别 | 目标 |
|---|---|---|
| NFR-001 | 完整性 | 写动作 before/contract/policy/execution/after/verification 链完整率 100%。 |
| NFR-002 | 可复现 | 确定性环境的非模型事件和核验结果可完全重放。 |
| NFR-003 | 安全 | 沙箱越权成功数、批准绕过数、跨租户访问数均为 0。 |
| NFR-004 | 可用性 | 按第 21 节分版本达成 SLO。 |
| NFR-005 | 性能 | 平台额外开销可单独测量，达到第 21 节目标。 |
| NFR-006 | 扩展性 | 无需改变事件语义即可从单机升级到分布式数据面。 |
| NFR-007 | 兼容性 | N-1 客户端兼容，破坏性 Schema 变更进入主版本。 |
| NFR-008 | 可移植 | Local、SaaS、客户 VPC、Hybrid 与 air-gapped 共享核心能力。 |
| NFR-009 | 隐私 | 原始证据最小访问、可驻留、可导出、可删除并有审计。 |
| NFR-010 | 可观察 | 请求、Agent、认知和成本全链路关联到 Run/Event。 |
| NFR-011 | 可维护 | 核心模块有契约边界；关键路径自动测试和迁移覆盖。 |
| NFR-012 | 无障碍 | Console 关键操作支持键盘、语义标签和可读对比。 |
| NFR-013 | 国际化 | UI、时间、数字和策略描述可本地化；事件语义保持稳定。 |
| NFR-014 | 数据耐久 | Artifact 和元数据达到定义的 RPO/RTO 并定期恢复演练。 |
| NFR-015 | 成本透明 | 每个 Run/项目/租户可归集模型、计算、动作和存储成本。 |

---

## 31. 0–36 个月路线图

路线图以能力和证据门驱动，不以日期强行推进。阶段可重叠，但不得跳过进入门。

### Stage 0：问题验证与基线（0–2 个月）

**目标：**证明问题真实存在并建立公平基线。

交付：

- 20–30 个客户/开发者访谈；
- 失败类型与成本模型；
- VastaLab 初版与本地 GUI 演示；
- Baseline 轨迹、事件 Schema 和系统不变量；
- 两个设计伙伴意向。

进入门：至少两个团队愿意提供失败轨迹或影子场景；可量化至少一个错误/排障成本。

### Stage 1：Foundation / 技术 MVP（2–5 个月）

**目标：**完成单机端到端可信循环。

交付：

- Python SDK、Local Runtime、SQLite/CAS；
- 原始证据、分层记忆、Action Contract；
- 基础策略、核验、计划失效、HTML Replay；
- 规则 DSL/Python 局部模型、历史回放和沙箱；
- 六组消融与安全测试。

进入门：完整链 100%；偏差注入能停止旧计划；Full 相对 Baseline 出现稳定净收益。

### Stage 2：Developer Preview（5–8 个月）

**目标：**证明外部团队能独立接入并获得价值。

交付：

- SDK/API 稳定候选、CLI、文档和示例；
- Tool Proxy、Playwright GUI Pack；
- Web Replay Console；
- 私有 Evaluation Pack；
- 3–5 个设计伙伴 observe-only 部署。

进入门：基础接入 ≤3 工程日；至少 3 个团队每周使用；失败定位时间有显著下降。

### Stage 3：Team Beta（8–12 个月）

**目标：**支持团队协作、集中评测和有限强制执行。

交付：

- Postgres/S3、API/worker、项目与角色；
- SSO 基础、策略/审批、资产版本和灰度；
- Domain Studio 初版；
- OpenTelemetry、队列、备份；
- 一个垂直包进入真实影子/小流量。

进入门：至少一个客户从 L0/L1 升至 L2；无严重安全事故；试点确认可付费价值。

### Stage 4：Production / Enterprise 1.0（12–18 个月）

**目标：**满足受控生产和企业采购要求。

交付：

- 多租户或强单租户、RBAC/ABAC、SAML/SCIM；
- 数据驻留、BYOK、保留/删除、审计导出；
- SLO、灾备、事故响应和支持体系；
- 认知资产 CI/CD；
- 世界模型影子、漂移、修复和回滚；
- GUI Pack 稳定版，第二个垂直包 Beta。

进入门：3 个以上生产客户；安全和恢复演练通过；单位经济与支持成本可控。

### Stage 5：Platform 2.0（18–24 个月）

**目标：**从单 Agent 可靠性工具升级为组织级认知平台。

交付：

- 控制面/客户数据面分离和 Hybrid；
- 多 Agent 有界共享与组织知识发布；
- 组合世界模型、概率模型和高级规划；
- 自治等级动态升降；
- 跨团队资产影响、合规和成本驾驶舱；
- 三个成熟垂直包。

进入门：跨团队扩张、资产复用和生产可靠性证明平台效应。

### Stage 6：Ecosystem 3.0（24–36 个月）

**目标：**形成可信扩展生态和互操作标准。

交付：

- 插件签名、验证发布者、私有/公开注册表；
- 标准化 Observation、Action Contract、Cognitive Asset、World Model Manifest；
- 认知资产迁移与第三方验证；
- 合作伙伴方案、认证与分发；
- 选择性公开市场和商业结算。

成功门：第三方扩展和资产带来可测的使用、收入或集成网络效应。

---

## 32. 阶段验收与产品指标

### 32.1 技术 MVP 验收

| ID | 标准 |
|---|---|
| AC-01 | 至少 40 个 VastaLab/GUI 任务可运行并生成完整回放。 |
| AC-02 | 100% 状态改变型动作具备动作前后、契约、策略和核验链。 |
| AC-03 | 任意派生物可回链并校验原始 Artifact。 |
| AC-04 | 偏差注入测试中旧计划 100% 失效，不继续批量执行。 |
| AC-05 | 至少 10 个确定性任务的激活模型通过声明范围内全部历史回放。 |
| AC-06 | 网络、密钥、宿主文件和资源越权测试全部失败并有审计。 |
| AC-07 | 自动产出六组消融、成本、置信区间和失败分类。 |
| AC-08 | 失败复现包可在干净环境离线重放非模型事件和 verifier。 |

### 32.2 生产级验收

| ID | 标准 |
|---|---|
| AC-20 | 核心服务达到目标 SLO，完成负载、故障注入和恢复演练。 |
| AC-21 | 租户隔离、权限、审批、保留、删除和 BYOK 测试通过。 |
| AC-22 | 资产发布、影子、灰度和回滚在真实场景完整演练。 |
| AC-23 | 高风险动作批准绕过和无审计执行均为 0。 |
| AC-24 | 至少一个场景在任务成功、错误动作、偏差漏检或排障时间上有稳定收益。 |
| AC-25 | 平台引入的延迟、模型成本、存储和人工负担在客户接受范围。 |
| AC-26 | 安全评审、隐私评估、事故流程和供应链控制完成。 |
| AC-27 | 文档支持新团队独立安装、接入、升级和恢复。 |

### 32.3 北极星与护栏指标

**北极星指标：**在既定风险和成本预算下完成且可验证的 Agent 任务数。

**结果指标：**

- 任务成功率、首次成功率；
- 严重错误和不可逆错误；
- 人工接管与恢复成功率；
- 每成功任务动作、时间和成本。

**可靠性指标：**

- 偏差检测 precision/recall；
- 错误认知存活时间；
- 计划失效及时率；
- 核验 inconclusive 和误阻断率；
- 世界模型触发净收益和错误模型拦截率。

**产品指标：**

- 首次价值时间、周活跃项目、外部接入时间；
- observe→recommend→enforce 转化；
- 失败回放使用率和 MTTR 降幅；
- 资产复用、试点转付费和团队扩展。

**护栏指标：**

- token、存储、端到端延迟；
- 不必要审批和假阳性；
- 隐私事件、越权、审计断链；
- 公共任务与私有变体之间的过拟合差距。

---

## 33. 测试策略

### 33.1 测试层次

- 单元：Schema、状态机、选择器、策略、核验器；
- 性质：事件顺序、资源不为负、终局后不行动、失效传播；
- 契约：每个适配器和插件的兼容套件；
- 集成：数据库、对象存储、队列、身份和模型适配；
- E2E：VastaLab、本地 GUI 和垂直包；
- Replay：历史轨迹的离线确定性重放；
- 安全：提示注入、越权、沙箱、租户隔离、供应链；
- 性能：事件、Artifact、时间线、并发 Run、沙箱和批量评测；
- 混沌：模型、工具、队列、数据库、对象存储和控制面故障；
- 灾备：备份恢复、区域/节点故障、密钥轮换。

### 33.2 发布门禁

每次发布至少检查：

1. Schema 兼容；
2. 单元/契约/回放通过；
3. 私有任务无显著回归；
4. 成本和延迟未超过阈值；
5. 安全扫描与权限变更评审；
6. 数据迁移和回滚演练；
7. 影子或灰度结果；
8. 变更说明、值班和回滚责任人。

---

## 34. 组织、团队与职责

### 34.1 团队演进

| 阶段 | 建议团队 | 重点 |
|---|---|---|
| 0–5 月 | 2–4 人 | 核心协议、证据、Runtime、评测、Replay |
| 5–12 月 | 5–8 人 | 开发者体验、Team 平台、GUI 包、安全 |
| 12–18 月 | 10–16 人 | Enterprise、SRE、合规、第二垂直、客户成功 |
| 18–36 月 | 18–30+ 人 | 控制面、多区域、生态、多个解决方案和标准 |

### 34.2 稳定职能

- Core Runtime & Protocols；
- Evidence & Cognition；
- World Model & Evaluation；
- Control Plane & Enterprise；
- Developer Experience & Console；
- Solutions & Integrations；
- Security, Privacy & SRE；
- Product, Design & Customer Success。

### 34.3 关键所有权

| 领域 | 最终负责 |
|---|---|
| 系统不变量与协议 | 首席架构/技术负责人 |
| 产品范围与阶段门 | 产品负责人 |
| 证据完整性 | Evidence 团队 |
| 动作安全与自治 | Security + Runtime 联合 |
| 评测真实性 | Evaluation 负责人，独立于功能作者 |
| 世界模型激活标准 | Model Lab + 场景负责人 |
| 生产 SLO 和事故 | SRE/平台负责人 |
| 领域规则与核验 | 领域所有者 |
| 合规声明 | 法务/安全，不由营销单独决定 |

### 34.4 成本类别

- 人员研发与安全评审；
- 模型推理、批量评测和多模型复核；
- Artifact 存储、网络、派生计算和冷归档；
- 沙箱与隔离计算；
- 企业身份、监控、审计和支持；
- 合规、渗透测试、法律和保险；
- 设计伙伴集成和垂直数据标注。

每阶段都必须测量单位成本，不能用无限 token 和存储换取表面成功率。

---

## 35. Epic 级实施拆解

| Epic | 范围 | 主要依赖 |
|---|---|---|
| E0 Protocol Foundation | Schema、事件、版本、配置与 contract test | 无 |
| E1 Evidence Platform | CAS、事件库、派生、索引、生命周期 | E0 |
| E2 Cognition Graph | 记忆、主张、冲突、晋升、影响 | E0/E1 |
| E3 Runtime & Supervisor | 运行循环、预算、检查点、恢复 | E0/E1 |
| E4 Trusted Action | Contract、Policy、Approval、Tool Gateway | E3 |
| E5 World Model Lab | 模型协议、沙箱、回放、规划、漂移 | E1/E2/E3 |
| E6 Evaluation & CI/CD | 任务、消融、门禁、影子、灰度 | E3/E4/E5 |
| E7 Replay Console | 时间线、Diff、复现、事故 | E1/E2/E3/E4 |
| E8 Domain Studio | 状态、不变量、核验和知识审核 | E2/E4/E6 |
| E9 Team Control Plane | 项目、身份、策略、配额、资产 | E0/E3 |
| E10 Enterprise Assurance | 多租户、驻留、BYOK、审计、DR | E9 |
| E11 Multi-Agent | 委派、共享边界、Curator/Supervisor | E2/E3/E9 |
| E12 Solution Packs | GUI、视频、游戏、工业适配 | E1–E8 |
| E13 Ecosystem | 插件 SDK、签名、注册表、撤销 | E0/E6/E9 |

关键路径：`E0 → E1/E3 → E2/E4 → E5/E6 → E7/E8/E9 → E10/E11/E12 → E13`。

---

## 36. 主要风险与应对

| 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|
| 产品膨胀为另一个通用 Agent 平台 | 高 | 高 | 守住证据、认知、执行、模型、评测五条主线；优先集成 |
| 原始证据成本/隐私大于价值 | 中高 | 高 | 按需派生、分层存储、驻留、脱敏、保留和价值指标 |
| 执行契约增加过多延迟 | 高 | 中 | 按风险模板化；低风险精简；确定性核验优先 |
| 核验模型产生虚假安全感 | 中 | 极高 | 独立读回、组合核验、允许不确定、测漏检 |
| 错误记忆长期污染 | 中 | 高 | 证据门槛、冲突、版本、影响查询和撤回 |
| 世界模型过拟合历史 | 高 | 高 | Unknown、范围、影子、私有变体、逐步现实核验 |
| 自动建模成本无净收益 | 中高 | 高 | 记录 build/use/bypass 收益；规则门槛；及时停用 |
| 高随机环境不适合精确模型 | 高 | 中 | 概率/约束模型，或限定到确定性子机制 |
| 生成代码/插件越权 | 中 | 极高 | 强沙箱、签名、权限清单、撤销和隔离凭证 |
| 提示注入污染工具与知识 | 高 | 高 | 数据/指令隔离、独立授权、知识审核、攻击回归 |
| 多 Agent 放大成本与责任模糊 | 中 | 高 | 非默认、明确委派契约、预算、共享边界和责任 |
| 公开基准过拟合 | 高 | 高 | 隐藏变体、真实影子、跨环境消融 |
| 绑定模型或框架被迭代淘汰 | 中 | 高 | 开放协议、能力适配和多模型对照 |
| 多租户/数据驻留复杂度低估 | 中 | 极高 | 控制/数据面分离，Enterprise 阶段专门投入 |
| 客户只喜欢 Demo 不愿付费 | 中 | 极高 | 早期测 MTTR、错误成本和 enforce 转化，不以点赞代替购买 |
| 垂直方向分散 | 高 | 高 | 先 GUI 楔子；新包必须通过第 26.5 节门槛 |
| 恢复循环放大副作用 | 中 | 极高 | 幂等、次数/预算、补偿、安全停止 |
| Schema 快速演进破坏历史 | 中 | 高 | 版本、不变事件、投影迁移、N-1 兼容 |
| VastaCore 与 VISTA 名称混淆 | 中 | 中 | 公测前名称/商标/域名核查，明确无隶属关系 |
| 监管或模型政策变化 | 中 | 高 | 模型可替换、数据驻留、资产来源和法律评审 |

---

## 37. Build / Buy / Integrate 边界

### 必须自研

- 统一事件和证据语义；
- 认知主张图与生命周期；
- Action Contract 和计划失效机制；
- 世界模型清单、验证、影子和信任状态；
- Agent 可靠性评测与回放体验；
- 各能力之间的因果关联。

### 优先集成

- 基础模型与模型网关；
- 对象存储、数据库和向量索引；
- OIDC/SAML/SCIM；
- OpenTelemetry 和监控后端；
- 通用策略引擎、密钥管理和审批系统；
- 容器/microVM 沙箱基础设施；
- OCR、ASR、对象检测和视频处理。

### 有证据后再自研

- 学习型 Meta Controller；
- 通用概率世界模型语言；
- 高级跨模型规划器；
- 公共插件市场；
- 专用分布式向量或事件基础设施。

---

## 38. 决策、假设与待确认项

### 38.1 已收敛决策

| 决策 | 原因 |
|---|---|
| 定位为认知与执行可靠性平台 | 覆盖研究创新，也对应真实生产痛点 |
| 完整产品含七个产品面 | 避免把 SDK、企业治理和研究能力混成单体 |
| 采用五级渐进自治 | 降低采用和安全门槛 |
| 证据为事实源，认知为可修订资产 | 保留重新解释与审计能力 |
| 世界模型按需且允许 Unknown | 防止过早结构化与虚假完整性 |
| GUI 是首选商业楔子 | 多模态、长程、状态变化和审计价值同时存在 |
| 垂直差异放入解决方案包 | 核心协议稳定，市场聚焦 |
| 0–36 月六阶段交付 | 完整蓝图与现实执行兼顾 |

### 38.2 当前假设

- `[A1]` 项目目标是可复用产品/平台，而非只复现 ARC-AGI-3。
- `[A2]` 核心实现首选 Python，服务接口保持语言无关。
- `[A3]` 初期可使用云模型和本地模型适配，生产部署支持客户选择。
- `[A4]` GUI 为首个商业验证方向；视频、游戏和工业为后续包。
- `[A5]` 企业客户愿意为调试、治理、审计或降低错误成本付费，需要访谈验证。
- `[A6]` 关键业务工具能够提供至少一种可靠读回；否则自治等级受限。

### 38.3 需按阶段确认

| 问题 | 默认建议 | 最晚确认 |
|---|---|---|
| 开源范围与许可证 | 协议、SDK、本地运行和基础回放开放 | Developer Preview 前 |
| 首批模型支持 | 一个 OpenAI 兼容接口 + 一个独立适配器 | Foundation |
| 第一个真实 GUI 场景 | 有历史失败、可读回、非安全关键的后台流程 | Stage 0 |
| SaaS 与私有化优先级 | Team 先单租户/托管，Enterprise 提供 Hybrid | Team Beta 前 |
| 默认保留期 | 按数据分类与项目设置，不设无限保留 | Team Beta 前 |
| 规则 DSL 边界 | 先覆盖状态条件、效果、不变量和风险 | Foundation |
| 公共插件市场 | 先私有注册表，有生态证据后开放 | Stage 5 |
| 品牌名称 | 做商标、域名和开源项目冲突检索 | Developer Preview 前 |

---

## 39. 前 90 天执行计划

### 第 1–30 天：问题与基线

1. 访谈 10–15 个 Agent/平台工程师，收集真实失败轨迹。
2. 确定一个本地 GUI 演示流程与一个设计伙伴场景。
3. 冻结 v0 事件、Artifact、Observation、Action Contract Schema。
4. 建立 20 个 VastaLab 任务和 Baseline。
5. 创建 monorepo、CI、类型检查、测试和实验记录。
6. 实现 Local CAS + SQLite Event Store。

### 第 31–60 天：证据、认知与执行

1. 完成图像/JSON 证据、inspect、Diff 和派生血缘。
2. 完成 Working/Hypothesis/Guide/Counterexample 初版。
3. 打通 Observe–Contract–Policy–Act–Verify。
4. 完成字段、读回和视觉核验器。
5. 注入延迟、弹窗、重复提交和外部变化。
6. 生成自包含 Replay 报告。

### 第 61–90 天：模型、评测与外部接入

1. 完成规则式 Meta Controller。
2. 完成受限 DSL/Python 世界模型、回放和沙箱。
3. 完成六组消融和私有变体。
4. 完成 Tool Proxy 或 Playwright 适配器。
5. 让至少一个外部团队以 L0 Observe-only 接入。
6. 根据数据决定继续、缩小或调整 Stage 1。

---

## 40. 完整产品完成定义

### Foundation 完成

- 单机闭环、证据、认知、契约、基础模型和消融有效；
- 安全边界和失败停止机制通过测试。

### Team 产品完成

- 外部团队可独立接入；
- 共享项目、策略、审批、评测、Console 和备份可用；
- 至少一个真实场景证明排障或错误成本改善。

### Enterprise 1.0 完成

- 身份、租户、驻留、密钥、审计、SLO 和灾备通过评审；
- 资产可测试、影子、灰度、回滚；
- 至少三个生产客户且无未解决高严重度安全问题。

### Platform 2.0 完成

- 跨团队认知资产治理与复用产生可测价值；
- 多 Agent、组合模型和动态自治均有明确使用边界和收益；
- 三个垂直包不破坏核心协议。

### Ecosystem 3.0 完成

- 第三方可安全构建、测试、签名、发布和撤销扩展；
- 开放协议有外部采用；
- 生态带来真实使用或收入，而非只有插件数量。

---

## 41. 参考依据

本方案以用户头脑风暴为需求输入，并使用以下一手资料校准研究事实：

- [VISTA: A Visual Harness for Reasoning in an Interactive World](https://vista-research.github.io/)
- [Tycho: Active Abstraction with Programmatic World Models for ARC-AGI-3](https://arxiv.org/abs/2607.28287)
- [Tycho reference implementation](https://github.com/NIMI-research/Tycho/)
- [Schema: executable world models for ARC-AGI-3](https://schema-harness.github.io/)
- [NVIDIA AVO reaches 100% on ARC-AGI-3](https://developer.nvidia.com/blog/nvidia-avo-reaches-100-on-arc-agi-3-demonstrating-a-frontier-level-general-purpose-architecture-for-long-horizon-autonomous-agents/)
- [ARC-AGI-3 technical report](https://arcprize.org/media/ARC_AGI_3_Technical_Report.pdf)

这些资料证明的是相关机制在特定公开环境中的潜力，不替代 VastaCore 自身的私有评测、真实试点、安全验证、合规评审和商业验证。
