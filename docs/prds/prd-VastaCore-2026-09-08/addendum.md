---
title: VastaCore PRD 附录
status: final
created: 2026-09-08
updated: 2026-09-08
---

# PRD 附录：移交架构阶段的技术内容

本附录承接"属于架构/解决方案设计、不宜写进 PRD 正文"的内容与指针。原始底稿始终是 [plan.md](../../../plan.md)；此处只做导航与决策摘要，避免双源漂移——架构阶段应回读 plan.md 对应章节原文。

## 1. PRD → plan.md 章节映射

| PRD 章节 | plan.md 底稿 |
|---|---|
| §4.1 接入与运行时 | §9 端到端流程、§16.3 核心组件、§18 协议 |
| §4.2 证据平台 | §10 无损证据平台（存储原则/检索/生命周期/成本） |
| §4.3 认知资产 | §11 认知资产与长期记忆（Claim 结构/晋升/冲突衰减） |
| §4.4 可信执行 | §12（契约 JSON 形态/核验器体系/风险分级 R0–R4/恢复顺序） |
| §4.5 世界模型 | §13（接口 Protocol/触发公式/生命周期/验证/沙箱） |
| §4.6 多 Agent | §14（共享边界表/角色协作） |
| §4.7 回放评测 | §15（评测八层级/六组消融/反馈飞轮/发布门） |
| §4.8 控制面 | §16 架构、§20–23（部署/可靠性/安全/可观察） |
| §4.9 生态 | §27（扩展生命周期/注册表/协议候选） |
| §8 NFR | §30 原表 |
| §9 约束护栏 | §22 安全隐私合规（威胁模型九条） |
| §10 契约 | §17 数据模型与事件语义、§18.4 API 端点、§19 技术选型 |
| §11 运营要求 | §20.2 容量、§21 可靠性/灾备（本附录 §3 为对应摘要） |

## 2. 架构阶段必须承接的技术决策输入

- **接口定义**：PartialWorldModel 最小接口（init_state/transition/observe/outcome + allowed_actions/state_hash/heuristic）与 EnvironmentAdapter/ModelAdapter/ToolAdapter/Verifier 四协议（plan.md §13.3、§18.1）。
- **事件词汇表**：§17.2 关键事件清单（run、observation、artifact、claim、memory、plan、action、verification、world_model、evaluation、release、incident、episode 共 13 族）——Epic E0 协议基础的范围。
- **一致性与幂等语义**：§17.3（单调序号、幂等键、CAS 先于事件、outbox/inbox、投影重建）。
- **仓库结构**：§16.4 monorepo 布局（packages/services/apps/solutions/schemas/plugins）。
- **技术选型**：§19 两档（Foundation：Python 3.12+、Pydantic、SQLite、Typer、FastAPI、pytest；Team：PostgreSQL、S3、pgvector 起步、托管队列、Redis 仅缓存、OPA 可选、K8s 延后）与"明确不提前引入"清单。
- **部署形态**：§7.2 六种（Local/单租户/SaaS/Hybrid/Air-gapped/Edge）与控制面/数据面边界（§16.2，Hybrid 下控制面不接触原始证据）。

## 3. 运营与容量基线（架构输入，非 PRD 承诺）

- SLO 表：plan.md §21.1（Team Beta 与 Enterprise 两档八项指标；模型/外部工具时延单独统计）。
- 容量设计目标：§20.2（单租户 100 活跃 Run、单 Run 10 万事件/1 万 Artifact、日百万级事件写入）。
- 故障策略六条：§21.2（Evidence 不可用禁新写、Policy 不可用 fail closed 等六条映射）。
- 灾备：§21.3（元数据 RPO ≤5min / RTO ≤1h（Enterprise 初始），季度演练）。

## 4. 风险登记册（按影响与架构相关性选 5，全表见 plan.md §36）

| 风险 | 概率/影响 | 一线应对 |
|---|---|---|
| 核验模型产生虚假安全感 | 中/极高 | 独立读回、组合核验、允许不确定、测漏检 |
| 生成代码/插件越权 | 中/极高 | 强沙箱、签名、权限清单、撤销、隔离凭证 |
| 客户只喜欢 Demo 不付费 | 中/极高 | 早测 MTTR/错误成本/enforce 转化，不以点赞代替购买 |
| 产品膨胀为通用 Agent 平台 | 高/高 | 守五条主线（证据/认知/执行/模型/评测），优先集成 |
| 世界模型过拟合历史 | 高/高 | Unknown、范围、影子、私有变体、逐步现实核验 |

## 5. 商业与定价维度（未决，供产品决策）

计量维度候选：席位+活跃项目（Team）、受管 Run 或动作量（Runtime）、存储与派生处理（Evidence）、年度许可+数据面+支持（Enterprise）、批量作业（Eval/Model Lab）。约束：必要审计链不得按事件高价收费（防变相鼓励关闭记录）。完整 land-and-expand 与验证指标见 plan.md §28。
