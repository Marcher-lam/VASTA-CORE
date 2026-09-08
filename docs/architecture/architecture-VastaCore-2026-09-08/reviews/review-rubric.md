# Review — Rubric Walker（Good-spine checklist）

- 对象：`docs/architecture/architecture-VastaCore-2026-09-08/ARCHITECTURE-SPINE.md`（altitude=feature，下一层 Epic，greenfield）
- 标准：`~/.agents/skills/bmad-architecture/references/reviewer-gate.md` "Good-spine checklist"
- 驱动输入：PRD final（prd-VastaCore-2026-09-08/prd.md + addendum.md）、plan.md 蓝图
- 评审日期：2026-09-08（含当日 web 版本核实）
- **门禁判定：pass-with-findings**（1 critical + 3 high；core AD 集合本身是成立且自洽的，发现项均可定位修复）

---

## 0. 逐项判定（对照 checklist）

| # | Checklist 项 | 判定 | 依据 |
|---|---|---|---|
| 1 | 固定下一层真正的分叉点且无遗漏 | **基本成立，有遗漏** | 11 条 AD 全部是真实的跨 Epic 分叉点（依赖向、写路径、确定性、沙箱、租户、控制面边界、版本、异步、幂等），无一深入 Story 层——altitude 干净。遗漏：H2（MVP CLI/HTML Replay 无归属）、H3（fail-closed 降级语义）、M5（Meta Controller / Context Builder 无具名归属） |
| 2 | 每条 AD 的 Rule 可执行且真的阻止声明的分歧 | **多数成立** | AD-1（import-linter 可查）、AD-5（可 lint：datetime.now/random/os.environ/全局单例）、AD-6/9/10/11 均可机械或经契约测试执行。两个缺口：AD-2 有持久化旁路（M4）；AD-5 与配置约定字面冲突（L2） |
| 3 | Deferred 里没有会让两单元分叉的东西 | **成立** | 每个 deferral 都留了防分叉锚点：队列→AD-11 行为语义；多节点→AD-2/11 事件语义；规划算法→protocols 接口；DSL 语法→§13.3 最小接口；沙箱选型→AD-6 已定边界。这是本脊柱做得最好的一节 |
| 4 | 技术版本核实过 | **不成立（1 条）** | C1：fastapi 1.1.x 不存在。其余条目核实通过（见 §6 表） |
| 5 | brownfield 批准而非矛盾 | N/A | 项目 greenfield，无既有代码 |
| 6 | 覆盖驱动 spec 的能力 | **成立，有缺口** | Capability Map 覆盖 PRD §4.1–4.9 全部九域且 Governed by 指向合理；缺口是 4.7 的 MVP 形态（H2）与两个 MVP-Must 组件的归属（M5） |
| 7 | 父脊柱继承不被削弱 | N/A | 无父脊柱 |
| 8 | altitude 拥有的维度全部 决策/Deferred/开放 三态 | **部分不成立** | 运维与环境维度（部署拓扑✓ 三面图、环境 SQLite/PG✓、infra 选型✓ Deferred）大体覆盖，但 **SLO/性能预算、容量目标、备份/DR 完全沉默（H1）**；air-gapped 缺（L3）；"开放"态只存在于 .memlog 而不在交付物正文（M3） |

---

## 1. Critical

### C1 — Stack：fastapi 1.1.x 是虚构版本，"web 核实"声明对该条目不成立
- **位置**：Stack 表 `fastapi | 1.1.x`；.memlog 更写了"fastapi 1.1.x（已过 1.0）"。
- **事实**：FastAPI 从未发布 1.0。截至 2026-07-29 最新为 **0.141.x**（0.131.0 于 2026-02-22，0.141.0 于 2026-07-29）。其基础层 Starlette 已于 2026-03 到 1.0.0，但 FastAPI 本体没有。
- **为什么 critical**：checklist 第 4 项（named tech verified-current）直接失败；且 0.x 阶段 minor 也可能破坏性变更，"1.1.x"会给下游 Epic 一个不存在的稳定性假设（选 API 框架的稳定性是真实分叉点，AD-9 的 N-1 纪律也依赖它）。
- **处置建议：autofix** — 改为 `0.141.x`，并注明 0.x 语义版本风险（锁 minor、升级走独立 PR）；同时重跑一遍 stack 核实流程，确认没有第二处凭印象写的版本。
- 来源：eolrisk.com/fastapi/、github.com/fastapi/fastapi/releases、PyPI。

---

## 2. High

### H1 — 运维维度三态缺失：SLO/性能预算、容量目标、备份/DR 全部沉默
- **位置**：全文（无对应 AD / Deferred / 开放项）。
- **证据**：PRD §10 明文"完整 SLO 表与容量目标见 addendum 并由架构阶段承接"——即 PRD 把这项**显式移交给了本脊柱所在阶段**；addendum §3 列出 SLO 八项（非模型编排开销 P95 <500ms 等）与容量目标（蓝图 §20.2：单租户 100 活跃 Run、单 Run 10 万事件/1 万 Artifact、日百万级事件写入、时间线按 Run/序号分页）；NFR-014（RPO/RTO 与恢复演练，蓝图 §21.3）。脊柱对这些既未决策、未 Deferred、未列为开放。
- **为什么是分叉点**：容量数字直接决定 E1（事件存储分页/索引形态）与 E3（时间线加载）的设计取舍——"单 Run 10 万事件"意味着任何全量加载路径都是错的；两个 Epic 各自假设容量会各自设计存储访问层。SLO 的"平台开销可单独测量"还要求 E3/E4 的遥测切分从第一天就分得开模型时延与平台时延。
- **处置建议：discuss** — 不要求把 SLO 数字写进脊柱，但至少要显式 Deferred（"SLO 表与容量目标 → 哪个 Stage、由谁定"）或落一条最小决策（如"时间线/事件读取一律按 (run_id, seq) 分页，禁止全量加载"并入 AD-2 或 AD-11）。

### H2 — MVP 交付形态（CLI + HTML Replay）在结构种子里没有归属单元
- **位置**：Structural Seed（apps/ 只列 console / domain-studio 且标注 Stage 2+）；Capability Map 4.7 把 Replay 指向 apps/console。
- **证据**：PRD §6.1 MVP 承载形态 = "Python SDK + Local Runtime + SQLite/CAS + **HTML Replay** + …"，MVP 外清单明说"MVP 用 CLI + HTML Replay"；UJ-1 的核心交互是 `vasta inspect RUN_ID`。而脊柱里：AD-10 的 Binds 括注甚至提到了"**CLI 入口**"、Stack 里有 typer——概念上承认 CLI 存在，结构上却没有任何包/目录 owns 它；HTML Replay 生成器同样无家（apps/console 是 Stage 2+，vasta-eval 注释只写"消融、门禁、复现包"）。
- **为什么是分叉点**：SDK Epic、eval Epic（复现包/回放导出）与 runtime Epic 都可能以为对方 owns CLI 与 replay 渲染——这是 MVP 唯一的用户入口，漏掉即 MVP 无法验收 AC-01/AC-08 的"完整回放/离线重放"体验。
- **处置建议：autofix（需用户确认形态）** — 在 Structural Seed 显式放置：或 apps/ 增加 `cli/`（Stage 1），或写明"CLI 入口与 HTML Replay 导出归 vastacore-sdk / vasta-eval（指名一个）"。

### H3 — 降级与 fail-closed 语义无 AD 承接
- **位置**：全文（最接近的是 AD-4，但只覆盖 happy-path 管道）。
- **证据**：蓝图 §21.2 六条故障策略 + PRD §11 运营要求："Evidence Store 不可用时禁止新写动作""策略/审批不可用时高风险动作 fail closed""派生不可用时原始证据仍入库、延后处理"。这些是跨 E1/E3/E4/E6/E9 的**行为**约束：依赖不可用时每个单元做什么，若脊柱不定，各 Epic 会各自发明（有人 fail closed、有人静默重试、有人降级继续）——且 fail-open 恰好摧毁 AD-4 想保住的审计链。
- **处置建议：discuss** — 最小代价是给 AD-4 补一条 Rule 尾注（"依赖不可用时的动作 = fail closed；派生类 = 延后不阻塞入库"），或新增 AD-12。

---

## 3. Medium

### M1 — AD-7 与 AD-2 的 Binds 范围自相矛盾
AD-2 把"一切持久实体"绑到 E1/E2/E3/E4/E6/E7；AD-7 同样声称"一切持久实体与查询"，却只绑 E1/E2/E9。Evaluation/Release 等持久实体是否需要 tenant_id 作用域键，两读不一致。按 AD-7 自己的 Prevents（Stage 3 多租户返工），评测记录与发布资产恰恰是 Stage 3 起会被租户化的实体。**建议：autofix** — 对齐两处的持久实体集合。

### M2 — E0–E13 花名册不存在于任何文档，Binds 无法审计
所有 AD 用 E 编号绑定，但 PRD/plan/脊柱都没有 E0–E13 的一行一条定义（只能从括注反推 E1=storage、E5=model-lab、E9≈control-plane…）。Epic 尚未创建，编号是脊柱单方面预承诺：下游若以不同切分建 Epic，全部 Binds 静默错位。**建议：autofix** — 脊柱加一张 14 行的"单元 ↔ Epic 假设"对照表，或把 Binds 主键改为单元名、E 号作括注。

### M3 — 开放问题只活在 .memlog（scratch），交付物正文没有开放态
.memlog 记了三条开放项（首批模型适配器 OQ4、DSL 边界 OQ7、沙箱生产化时间点），但 ARCHITECTURE-SPINE.md 正文没有 Open Questions 节——checklist 第 8 项的"开放"态对读者不可见。**建议：autofix** — 把开放项写进正文（沙箱时间点那条其实已被 AD-6/Deferred 定为 Stage 3，可直接删）。

### M4 — AD-2 未封死"自建持久化"旁路
AD-3 封了 blob 直写，AD-2 说状态变更用事件表达，但没有任何条文禁止其他包**自开持久化存储**（如 eval 自己建 SQLite 表存报告）——这不违反现有任何 Rule 的字面，却正是 AD-2 要防的"双写路径"。**建议：autofix** — AD-2（或 AD-3）补一句"一切持久化写入只能经 vasta-storage 的存储端口，其他包不得自建持久化存储"。

### M5 — Meta Controller（FR-040）与 Context Builder（FR-025）无具名归属
两个 MVP-Must 组件：cognition 包注释只列"Claim 图、记忆、冲突、晋升"（无 Context Builder）；model-lab 只列"沙箱、回放、性质测试、规划"（无 Meta Controller），而 Capability Map 又把 4.5 整体指给 model-lab。Meta Controller 在运行循环内决策（build/use/repair/bypass/stop），存在 runtime vs model-lab 双归属风险。**建议：discuss** — 在 Structural Seed 包注释里点名归属。

---

## 4. Low

- **L1（Stack）**：`opentelemetry-sdk | 1.x 最新` 与 `playwright | 最新稳定` 未钉版本（lint_spine 的机械项本应拦截）；Team 档 Artifact 后端（S3 兼容对象存储，蓝图 §19.2）既不在 Stack 也不在 Deferred——它是 vastasta-adapters 的 storage 实现目标，应至少出现在其中一处。
- **L2（AD-5 vs 约定）**："非模型路径不得读取环境变量"与约定"配置 pydantic-settings + 环境变量"字面冲突。应写明豁免层：settings 构造期可读 env，业务代码只消费经 RunContext 注入的不可变配置快照。
- **L3（环境维度）**：Deferred 列了"边缘形态、跨区域数据面"，但 **air-gapped**（NFR-008、FR-074）缺席——其架构后果（核心路径无外联依赖、离线许可、本地模型适配）值得一行显式 Deferred。
- **L4（AD-1 图）**：图中 `EVAL --> RT` 且 `RT --> LAB`；若 eval 需独立驱动 model-lab 沙箱（消融里的 Model 组），依赖走向需在 Epic 拆分时复核。次要。

---

## 5. Capability 覆盖核对（PRD §4.1–4.9）

| 域 | 映射 | 判定 |
|---|---|---|
| 4.1 接入与运行时 | runtime + adapters + sdk | ✓（Model Router/能力探测隐含于 runtime，可接受） |
| 4.2 证据平台 | storage + artifact-worker | ✓（保留/删除证明由 AD-2 事件语义覆盖） |
| 4.3 认知资产 | cognition | △ Context Builder 未具名（M5） |
| 4.4 可信执行 | contracts + policy + runtime | ✓ |
| 4.5 世界模型 | model-lab + model-lab-worker | △ Meta Controller 未具名（M5） |
| 4.6 多 Agent | runtime（Supervisor/委派） | ✓ |
| 4.7 回放评测发布 | eval + apps/console（Replay） | ✗ MVP 形态（CLI + HTML Replay）无归属（H2） |
| 4.8 控制面 | control-plane | ✓ |
| 4.9 生态 | plugins + protocols + schemas/ | ✓（签名清单字段属协议 Epic 范围，AD-9 管版本，可接受） |

## 6. Stack 核实记录（2026-09-08）

| 条目 | 声明 | 核实 | 结果 |
|---|---|---|---|
| Python | 3.12+（开发 3.13） | 3.12/3.13 在支持期 | ✓（基线策略，非钉死，可接受） |
| pydantic | 2.13.x | 2.13.4 为当前稳定（2.14.0a1 alpha） | ✓ |
| fastapi | 1.1.x | **1.0 从未发布；最新 0.141.x（2026-07-29）** | ✗ C1 |
| typer | 0.27.x | 0.27.2（2026-08-28） | ✓ |
| pytest | 9.1.x | 9.1.1（2026-06-19） | ✓ |
| hypothesis | 6.167.x | 6.167.1（2026-08-30） | ✓ |
| SQLite / PostgreSQL 16+ | — | — | ✓ |
| opentelemetry-sdk | "1.x 最新" | 未钉版本 | △ L1 |
| playwright | "最新稳定" | 未钉版本 | △ L1 |

版本来源：[PyPI pydantic](https://pypi.org/project/pydantic/)、[PyPI typer](https://pypi.org/project/typer/)、[PyPI pytest](https://pypi.org/project/pytest/)、[PyPI hypothesis](https://pypi.org/project/hypothesis/)、[pytest changelog](https://docs.pytest.org/en/stable/changelog.html)、[EOL Risk fastapi](https://eolrisk.com/fastapi/)、[fastapi releases](https://github.com/fastapi/fastapi/releases)、[hypothesis changelog](https://hypothesis.readthedocs.io/en/latest/changelog.html)。

---

## 7. 结论

脊柱的决策密度与 altitude 纪律是好的：11 条 AD 条条对着真实分叉点，Deferred 每项都留了防分叉锚，事件溯源 + 端口/适配器范式与 PRD INV/NFR 的对齐紧密。主要问题集中在三处：一个虚构的 fastapi 版本（C1，autofix）、运维/环境维度的三态缺口（H1/H3，需用户裁决 Deferred 去向）、MVP 形态（CLI + HTML Replay）无结构归属（H2，需用户确认放置）。修复这三组后无需重写。
