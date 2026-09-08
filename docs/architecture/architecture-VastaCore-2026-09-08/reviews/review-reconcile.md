# 架构输入对账：PRD（含附录技术移交输入）→ ARCHITECTURE-SPINE

- 日期：2026-09-08
- 输入：`docs/prds/prd-VastaCore-2026-09-08/prd.md`（final）、`docs/prds/prd-VastaCore-2026-09-08/addendum.md`（final）、`docs/architecture/architecture-VastaCore-2026-09-08/ARCHITECTURE-SPINE.md`（draft）
- 判据：脊柱哲学为"只固化防分叉不变量"。凡 AD / Structural Seed / Deferred 三处任一显式承接即算承接；写入 Deferred 视为有意推迟（非遗漏）；三处皆无且 PRD/附录点名要求承接的，记为**静默遗漏**。

---

## 1. 总体结论

PRD §4 九个能力组在 Capability → Architecture Map 全部有落点；附录 §2 点名的决策输入中，monorepo、Hybrid 边界、一致性族的大部分、四协议与两档选型均由 AD/Seed/Deferred 忠实承接。存在 **3 处实质静默遗漏**（G1 故障 fail-closed 语义、G2 SLO/容量/灾备基线、G3 Air-gapped 部署形态）与 **2 处承接不全**（G4 事件 13 族封闭词汇未锚定、G5 §17.3"CAS 先于事件"无对应条目），另见 2 处笔误级不一致（E1/E2）。

---

## 2. PRD §4 九个能力组落点核对

| PRD 组 | 脊柱落点（Lives in） | 治理 AD | 结论 |
| --- | --- | --- | --- |
| 4.1 接入与运行时（FR-001~009） | vasta-runtime、vasta-adapters、vastacore-sdk | AD-1/4/5/10/11 | 承接。FR-001 协议=AD-1 依赖根；FR-004 检查点/预算由 AD-2 事件流+AD-5 RunContext 承载；FR-007 跨进程恢复在 Deferred 显式推迟且论证了可迁移性 |
| 4.2 无损证据平台（FR-010~019） | vasta-storage（+services/artifact-worker） | AD-2/3/7/11 | 承接。FR-011 内容寻址=AD-3 sharded CAS；FR-016 按需派生=artifact-worker + AD-11 worker 幂等；FR-017 生命周期在 storage 职责内 |
| 4.3 认知资产与记忆（FR-020~029） | vasta-cognition | AD-2/7/9 | 承接。FR-022"推翻不删除"=AD-2 修正即新事件（claim.refuted）；FR-023 冲突显式化由 AD-2"禁止静默覆盖"（INV-01/04）背书 |
| 4.4 可信执行（FR-030~039） | vasta-contracts、vasta-policy、runtime/Tool Gateway | AD-4/11 | 承接。AD-4 显式引用 FR-030 与 NFR-001 六段链；FR-036 四态为 Consistency Conventions 固定枚举 |
| 4.5 世界模型与规划（FR-040~049） | vasta-model-lab（+services/model-lab-worker） | AD-5/6 | 承接。AD-6 显式引用 FR-044/046；FR-047 规划算法实现 Deferred（接口由 protocols 固定）；FR-045 生命周期 Stage 4 |
| 4.6 多 Agent 与人机（FR-050~056） | vasta-runtime（Supervisor/委派） | AD-4/11 | 承接（Stage 5 为主，结构在 runtime 内，无返工风险） |
| 4.7 回放、评测与发布（FR-060~069） | vasta-eval、apps/console（Replay） | AD-2/5/9/11 | 承接。FR-062 复现包=vasta-eval 职责 + AD-5 确定性替身；FR-068 审计导出有 services/audit-exporter 种子 |
| 4.8 企业控制面（FR-070~079） | services/control-plane | AD-7/8/9 | 承接。AD-7 防多租户返工、AD-8 防合规返工，均为 Stage 3 前置不变量 |
| 4.9 扩展生态（FR-080~085） | plugins + vasta-protocols + schemas/ | AD-1/9 | 承接。FR-085 开放 Schema=schemas/ N-1 金件 + AD-9 |

九组全部有落点，无整组丢失。

---

## 3. 附录 §2"架构阶段必须承接的技术决策输入"逐项核对

| # | 决策输入（附录原文） | 承接方式与位置 | 结论 |
| --- | --- | --- | --- |
| 1 | 四协议（EnvironmentAdapter/ModelAdapter/ToolAdapter/Verifier，plan §18.1） | AD-1（依赖根）+ Design Paradigm 端口枚举 + Seed（vasta-protocols / vasta-adapters） | 承接。但范式句写"Model/Environment/Tool/Storage/Verifier **四协议**"——列了 5 个名字却计 4，与 FR-001 五协议口径不一致（E1 笔误级，读者可能误判 Storage 非一等协议） |
| 2 | §13.3 最小接口（PartialWorldModel：init_state/transition/observe/outcome + allowed_actions/state_hash/heuristic） | 间接承接：vasta-protocols"端口 + 全部 schema"所有权；Deferred 两条显式回指（"接口由 protocols 固定"“接口已由 §13.3 最小接口约束”）；AD-6 固化激活必须带验证轨迹 | 承接（接口内容归 E0 schema，符合脊柱哲学）。备注：范式句端口枚举未点名 PartialWorldModel/Planner 端口，依赖两处 Deferred 回指，稍隐晦但非遗漏 |
| 3 | 事件词汇表：§17.2 共 13 族（run、observation、artifact、claim、memory、plan、action、verification、world_model、evaluation、release、incident、episode），Epic E0 范围 | 部分承接：命名约定（past-tense 点分）+ schema 所有权在 vasta-protocols；但 **13 族的封闭集合未写明，也未入 Deferred** | **承接不全（G4）**。族集是 E0 范围边界，episode/incident 等族最易被后续 Epic 静默漏建 |
| 4 | 一致性与幂等语义：§17.3（单调序号、幂等键、CAS 先于事件、outbox/inbox、投影重建） | 单调序号+因果父项=AD-2；幂等键、at-least-once、checkpoint、投影重建=AD-11（显式引用蓝图 §17.3）；outbox/inbox 以"事件追加即写路径（AD-2）+ 至少一次投递 + worker 幂等"语义等价承接；**"CAS 先于事件"（乐观并发先于 append）无任何条目对应** | **承接不全（G5）**：五项语义承接了四项 |
| 5 | 仓库结构：§16.4 monorepo（packages/services/apps/solutions/schemas/plugins） | Structural Seed 全量镜像，另含 examples/tests/docs/deploy；frontmatter scope 亦对齐 | 完整承接 |
| 6 | 技术选型两档 + "明确不提前引入"清单（plan §19） | Foundation 档全部入 Stack（Python 3.12+/pydantic/fastapi/typer/pytest/SQLite）+ hypothesis/OTel/playwright 增补；PostgreSQL 16+（Stage 3）入 Stack；消息队列/独立向量库/K8s/OPA/SSO 入 Deferred 且保留"证据条件" | 基本承接。备注 E2：Team 档 **S3（对象存储/blob 后端）未入 Stack seed 也未入 Deferred**——经 vasta-adapters/storage 实现端口，影响低，但附录点名的选型项两处皆无踪迹 |
| 7 | 部署形态：§7.2 六种（Local/单租户/SaaS/Hybrid/Air-gapped/Edge）+ §16.2 控制面/数据面边界 | Local=Stack（SQLite 档）；SaaS/单租户=services/control-plane 三面拓扑；Hybrid=AD-8；Edge=Deferred（"边缘形态…不决策"）；**Air-gapped：AD/Seed/Deferred 三处皆无** | **静默遗漏（G3）**。FR-074（Stage 4）、NFR-008 明确列 air-gapped 为共享核心能力的形态之一，其"数据面离线自足"约束未被声明归属 |
| 8 | Hybrid 边界（控制面不接触原始证据） | AD-8 [ADOPTED]（显式引用蓝图 §16.2），拓扑图以虚线边固化"只读摘要与聚合指标" | 完整承接，质量最高的 AD 之一 |

### 附录 §3 运营与容量基线（架构输入）

| 输入 | 承接 | 结论 |
| --- | --- | --- |
| SLO 表（plan §21.1 两档八项） | 无 | **静默遗漏（并入 G2）**。PRD §10 明言"完整 SLO 表与容量目标见 addendum 并由架构阶段承接"——这是 PRD 对架构的显式委托，脊柱既未落地数值（符合哲学）也未 Deferred 声明承接文件与时点（不符合委托） |
| 容量设计目标（§20.2：单租户 100 活跃 Run、单 Run 10 万事件/1 万 Artifact、日百万级事件写入） | 无 | 同上并入 G2。容量数量级会影响 AD-11 投影重建策略与事件库分页设计，至少应 Deferred 引用 |
| 故障策略六条（§21.2：Evidence 不可用禁新写、Policy 不可用 fail closed 等） | 无（AD-4 只规定管道顺序，未规定依赖不可用时的行为） | **静默遗漏（G1，最实质）**——见下节 |
| 灾备（§21.3：元数据 RPO ≤5min / RTO ≤1h，季度演练） | 无 | 并入 G2（NFR-014 悬空） |

---

## 4. §8 NFR / §9 护栏 / §10 契约 / §11 运营交叉核对

**NFR（PRD §8）**：

| NFR | 脊柱承接 | 状态 |
| --- | --- | --- |
| 001 链完整 100% | AD-4（显式引用"NFR-001 六段链断裂"） | 承接 |
| 002 可复现 | AD-5（显式引用 NFR-002） | 承接 |
| 003 安全三零 | AD-6（沙箱）+ AD-7（租户作用域）+ AD-4（唯一通道，批准不可绕过） | 承接 |
| 004 SLO / 005 性能开销 / 014 RPO-RTO | 三处皆无 | **悬空 → G2** |
| 006 单机→分布式不改事件语义 | AD-2/11 + Deferred#2 显式论证 | 承接 |
| 007 N-1 兼容 | AD-9（显式引用 NFR-007） | 承接 |
| 008 五形态共享核心 | AD-8 承接 Hybrid；air-gapped 缺 | **部分 → G3** |
| 009 隐私 | AD-8 + 日志约定（不记密钥/原始载荷） | 承接 |
| 010 四域遥测 | Consistency Conventions（OTel trace_id 贯穿 Event 与日志） | 承接（四域明细归实现） |
| 011 契约边界与测试 | AD-1 + 每端口契约测试套件约定 | 承接 |
| 012 无障碍 / 013 国际化 | 随"Console/Domain Studio UI"Deferred | 承接（可接受） |
| 015 成本归集 | AD-7（tenant_id+project_id 作用域键是结构使能） | 承接（结构层） |

**§9 约束护栏**：R0–R4 风险分级=vasta-policy 职责（Seed）；强沙箱=AD-6 [ADOPTED]；INV-06"执行模型不做自己唯一裁判"由 AD-4 管道形态（Verify 独立于 Execute 的段位）结构性体现。**提示注入防护（"观察内容永不自行提升为指令"）与供应链（SBOM/签名/撤销列表）三处皆无**——按脊柱哲学可辩护为策略/实现层，但注入防护是适配器可违背的安全不变量，建议至少入 Deferred 声明归属（观察级，不升级为差距）。

**§10 开发者契约**：Schema 版本/弃用四阶段/N-1=AD-9 完整承接；Python 3.12+=Stack；性能预算（P95<500ms、首屏 <3s）→ G2；商业形态=Deferred（计费计量）承接。

**§11 运营要求**：可用性数字与事件持久化等级 → G2；**"策略/审批不可用时高风险动作 fail closed；Evidence Store 不可用时禁止新写动作"→ G1**。

---

## 5. 差距清单（按严重度）

- **G1（高）故障 fail-closed 语义静默遗漏**。PRD §11 与附录 §3（蓝图 §21.2 六条）要求：Policy/Approval 不可用→高风险动作 fail closed；Evidence Store 不可用→禁止新写动作。这是 open-fail 与 fail-closed 的真实分叉面，属典型"防分叉不变量"；脊柱 AD-4 只固化了管道顺序，未规定依赖不可用时的行为，Deferred 亦无。两个团队可各自实现出相反语义而不违反任何 AD。
- **G2（中高）SLO/容量/灾备基线三处皆无**。PRD §10 显式委托"完整 SLO 表与容量目标见 addendum 并由架构阶段承接"；NFR-004/005/014 由此悬空。数值不进脊柱符合哲学，但对显式委托的输入既不落地也不 Deferred 声明承接文件与时点，构成对 PRD 承诺的静默丢弃。
- **G3（中）Air-gapped 部署形态静默遗漏**。附录 §2 六种形态中 Local/Hybrid/Edge 分别由 Stack/AD-8/Deferred 承接，单租户/SaaS 由 control-plane 拓扑承接，唯 Air-gapped（FR-074、NFR-008）三处皆无，连"Stage 4 届时定"的声明都没有。
- **G4（中低）事件 13 族封闭词汇未锚定**。命名约定与 schema 所有权已定，但 13 族封闭集合（附录 §2 点名、Epic E0 范围）未写明也未 Deferred；episode/incident 族最易在后续 Epic 被静默漏建或自造同义族。
- **G5（低）§17.3"CAS 先于事件"无对应条目**。一致性五项语义（单调序号/幂等键/CAS/outbox-inbox/投影重建）中 AD-2/11 承接了四项，唯独乐观并发（写前 CAS）缺失，并发更新丢失的防护无不变量背书。
- E1（笔误）范式句与 AD 层"四协议"实列五个名字（Model/Environment/Tool/Storage/Verifier），与 FR-001 五协议口径不符。
- E2（笔误级）Team 档 S3/object-storage 未入 Stack seed、未入 Deferred（附录 §2 点名项）。

---

## 6. 建议动作（最小修订）

1. 新增 AD-12（或并入 AD-4 补一句）：Policy/Approval 服务不可用→高风险动作 fail closed；Evidence Store 不可用→禁止新写动作（引 PRD §11、蓝图 §21.2 六条映射）。
2. Deferred 增补一行：SLO 表与容量/灾备基线（蓝图 §20.2/§21.1–§21.3）——数值不进脊柱，声明承接文件与决策时点（Team Beta 前），消化 G2 与 NFR-004/005/014。
3. Deferred 增补 Air-gapped（FR-074，Stage 4；数据面离线自足约束届时定），消化 G3。
4. 在 vastaa-protocols 种子条目或 Consistency Conventions 锚定 13 族封闭词汇（run/observation/artifact/claim/memory/plan/action/verification/world_model/evaluation/release/incident/episode；新增族=minor 变更，走 AD-9 纪律），消化 G4。
5. AD-11 增补"并发写先 CAS、后 append 事件"一句，消化 G5。
6. 勘误：范式句"四协议"改"五协议"（对齐 FR-001）；Stack 酌情补 S3/object-storage 一行（Team 档 blob 后端，Stage 3）。
