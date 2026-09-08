# 技术核证评审 — ARCHITECTURE-SPINE（Web 核证）

- **评审对象**: `docs/architecture/architecture-VastaCore-2026-09-08/ARCHITECTURE-SPINE.md`（Stack 表、AD-6、AD-10、Consistency Conventions）
- **核证方式**: WebSearch / WebFetch，核证日 **2026-09-08**，证据以当日 PyPI / python.org / 官方文档 / 一手工程资料为准
- **评审角色**: 技术核证评审（核实承诺的决策是否经过现实核证，而非训练数据断言）
- **总体结论**: Stack 表 8 项钉版本中 5 项准确、**1 项为捏造版本（fastapi 1.1.x，实际最新 0.141.1）**、2 项口径过时（Python 开发环境落后一个稳定大版本、PostgreSQL 下限落后两个大版本）；AD-6 沙箱与 AD-10 异步的技术事实全部成立；UUIDv7 约定成立但与 3.12 基线存在未解决的内部矛盾；greenfield 不用 starter 合理，但缺工具链 seed。

---

## 1. Stack 表逐项核证

| 脊柱声称 | 实测（2026-09-08） | 判定 | 证据 |
| --- | --- | --- | --- |
| Python 3.12+（基线；开发环境 3.13） | 稳定版：**3.14.7**（2025-10-07 首发，当前 bugfix 期）、3.13.15（bugfix 期）；**3.12 已进 security-only 期**（仅安全修复）；3.15 预计 2026-10-01 发布 | **过时（非错误）** | python.org/downloads |
| pydantic 2.13.x | 最新 **2.13.5**（2026-08-28） | **准确** | PyPI |
| fastapi 1.1.x | 最新 **0.141.1**（2026-07-29）；**1.x 从未发布** | **错误——捏造版本** | PyPI |
| typer 0.27.x | 最新 **0.27.2**（2026-08-28） | **准确** | PyPI |
| pytest 9.1.x | 最新 **9.1.1**（2026-06-19） | **准确** | PyPI |
| hypothesis 6.167.x | 最新 **6.167.1**（2026-08-30） | **准确** | PyPI |
| SQLite（stdlib，随 Python ≥3.12） | 成立，无版本风险 | **准确** | — |
| PostgreSQL 16+（Team 档，Stage 3 起） | **PG 18 已于 2025-09-25 GA**（当前 minor 18.6，2026-08-13），PG 19 beta 3；16 的 EOL 为 2028-11 | **口径过时**（作为下限不算错，但新部署不会从 16 起步） | postgresql.org 版本页 / 官方发布公告 |
| opentelemetry-sdk 1.x 最新 | 最新 **1.44.0**（2026-07-16），Python SDK 仍为 1.x 线 | **准确** | PyPI |
| playwright 最新稳定 | 声称里无可核验的具体版本号 | **不可核证**（建议落地时钉主版本） | — |

### 重点发现：fastapi 1.1.x 是捏造版本

FastAPI 截至 2026-09-08 的最新发布为 **0.141.1**（2026-07-29），项目从未发布过任何 1.x。这不是"过时"而是"从未存在"。Stack 表 seed 行声称 "SEED — 2026-09-08 web 核实"，但这一条证明该声称至少对部分条目不成立（版本号系训练数据幻觉）。**建议将 seed 行改为逐条附证据链接与核证日期，并把 fastapi 钉为 0.141.x。**

### 重点发现：Python 版本与 UUIDv7 约定互相矛盾

- Consistency Conventions 规定"实体 ID 用 UUIDv7/ULID 字符串"。
- **UUIDv7 已是正式标准**：IETF **RFC 9562**（2024-05 发布，取代 RFC 4122 的新格式部分）。
- **Python stdlib `uuid.uuid7()` 自 3.14 起才提供**（3.14 同时加入 uuid6/uuid7/uuid8）。
- 基线 3.12 下要用 UUIDv7，必须引入第三方库（`uuid6`（oittaa/uuid6-python，stdlib API 的原型库）或 `uuid-backport`）——脊柱未声明该依赖。
- 另注意 **PostgreSQL 18 原生支持 uuidv7()**，与 ID 约定形成正反馈。

即：要么把基线上调至 3.14（stdlib 直接满足约定），要么在 Stack 中显式加 uuid6 依赖。当前"3.12 基线 + UUIDv7 约定"组合处于未核证状态。

---

## 2. AD 与约定中的技术事实核证

### AD-6 — 沙箱分层（成立）

- **subprocess 隔离的局限为公认事实**：社区共识是子进程不隔离内核攻击面（"The main problem with sandboxing untrusted code is that the kernel is exposed"），需叠加 seccomp/配额/网络出口控制；对 LLM 生成代码，2025–26 共识明确偏向 microVM 级隔离。
- **方案命名全部核实存在且为主流**：
  - rootless 容器：Podman（rootless 模式）、rootless Docker/nerdctl；
  - microVM：**Firecracker**（最小设备模型，约 100–200ms 冷启动，AWS Lambda/Fargate 同款）；**Kata Containers**（可用 Firecracker 作 VMM 后端，容器体验 + 硬件隔离）；
  - 中间档：**gVisor**（syscall 拦截，兼容容器工作流；注意其 rootless 模式会牺牲部分网络沙箱能力）；
  - 生态参考：Kubernetes 已有 **Agent Sandbox SIG**，提供 Firecracker sandbox 用例（Kata + Firecracker VMM）。
- **脊柱的处理（MVP 受限子进程 + 明示非生产边界 + Stage 3 换 rootless 容器/microVM）与业界共识一致**，成立。
- 建议：Deferred 里 "rootless 容器 vs microVM" 二选一的表述可扩为三选（+gVisor），并引用 k8s Agent Sandbox SIG 作为 Stage 3 选型的现实参照系；若模型生成的代码形态收敛为纯计算，WASM（wasmtime/WASI）可作为窄域备选。

### AD-10 — asyncio + executor 隔离同步 SDK（成立，是通行做法）

- `asyncio.to_thread()`（3.9+）/ `loop.run_in_executor()` / starlette 的 `run_in_threadpool` 均为现行标准做法；FastAPI 对 `def`（非 `async def`）处理器自动进线程池，官方文档背书。
- 脊柱规则（async-first，同步 SDK 只准出现在 adapter 边缘并经 executor 隔离，循环内禁阻塞）与社区最佳实践分层完全一致。
- **建议补充两条实践告诫**（社区反复踩坑的点，脊柱未提）：
  1. 默认线程池规模有限（anyio/starlette 默认约 40 线程），与连接池失配时高负载下会整池死锁（FastAPI 官方讨论区有实录）——应在 AD-10 或实现规范里要求显式定容；
  2. 优先真异步驱动（如 asyncpg/aiosqlite）直连，executor 包装只作为存量同步 SDK 的过渡边界——这与脊柱"只有同步 SDK 允许存在于 adapter 边缘"的措辞一致，但可把"优先原生 async 驱动"写明，防止适配器作者图省事全走线程。

### Consistency Conventions 其他事实

- OTel `trace_id` 贯穿：opentelemetry-sdk 1.44.0（2026-07-16）仍为 1.x 线，"1.x 最新"准确。
- 金额/数量禁浮点、ISO8601 UTC、sha256 CAS：无版本依赖的工程惯例，无核证风险。

---

## 3. Greenfield 起点检查：不推荐 starter 是否合理

**结论：合理，且基本是唯一正确选择——但脊柱缺一块"工具链 seed"。**

- 主流 FastAPI 模板（官方 `full-stack-fastapi-template`：React + SQLModel + PostgreSQL + Vite + Docker Compose）是 **CRUD/全栈应用导向**的；社区共识明确指出复杂应用需要在模板的路由中心结构之外自行解耦业务层。VastaCore 的核心价值恰恰是自研结构（protocols 为依赖根的多包平台、事件溯源、四协议端口），套模板会引入大量需要拆除的脚手架噪音，且模板偏离上游后更新痛苦。
- 协议密集型 + 10 个自有包的 monorepo，市面无对应模板；**uv workspaces**（Cargo 风格，Astral 官方支持）是 2026 年 Python monorepo 的主流底座，与脊柱 `packages/` 结构天然吻合。脊柱 Stack 表当前完全没有构建/依赖管理/ lint 工具的任何条目——建议补一行工具链 seed（uv workspace + ruff 等），或在 Deferred 中显式推迟该决策；现状是"沉默缺口"而非"有意推迟"。
- 若未来某个包要独立发 PyPI，可用 copier 类库模板（uv + ruff + pytest + GH Actions）做参考，但作为平台骨架不建议从模板起。

---

## 4. 修正建议（按优先级）

1. **[必须]** Stack 表 `fastapi 1.1.x` → `0.141.x`（0.141.1，2026-07-29）。这是捏造版本，直接证伪 seed 行的"web 核实"声称。
2. **[必须]** 解决 UUIDv7 × Python 基线矛盾：基线上调 `3.14`（stdlib `uuid.uuid7()`，RFC 9562），或保持 3.12/3.13 并在 Stack 显式加 `uuid6` 依赖。推荐前者：3.14 已稳定 11 个月（当前 3.14.7），3.12 已 security-only，"基线 3.12 + 开发 3.13"整体落后一个稳定大版本，建议改"基线 3.13+，开发/目标 3.14"。
3. **[建议]** PostgreSQL 下限 `16+` → `17+`，并把 18 注为参考目标（18 GA 于 2025-09-25，含原生 uuidv7()；19 已 beta，GA 预计 2026 Q3/Q4）。
4. **[建议]** Stack seed 行改为逐条附"核证日期 + 证据链接"，恢复该行的可审计性。
5. **[建议]** AD-6 Deferred 的 Stage 3 沙箱选型从二选一扩为"rootless 容器 / gVisor / microVM(Firecracker/Kata)"三选，引用 k8s Agent Sandbox SIG。
6. **[建议]** AD-10 补两条实现告诫：线程池显式定容防死锁；优先原生 async 驱动。
7. **[建议]** 补工具链 seed（uv workspaces + ruff）或在 Deferred 显式推迟；playwright 落地时钉主版本。
8. **[无动作]** AD-2/3/4/5/7/8/9/11、AD-6 沙箱分层事实、AD-10 模式、UUIDv7 标准地位、OTel 1.x、pydantic/typer/pytest/hypothesis 版本：核证通过。

---

## 5. 证据来源

- PyPI（2026-09-08 实查）: fastapi 0.141.1 / pydantic 2.13.5 / typer 0.27.2 / pytest 9.1.1 / hypothesis 6.167.1 / opentelemetry-sdk 1.44.0
- python.org/downloads: 3.14.7（bugfix）、3.13.15、3.12 security-only、3.15 pre-release（计划 2026-10-01）
- Python 3.14 `uuid` 模块文档（RFC 9562，uuid6/7/8）；uuid6-python（github.com/oittaa/uuid6-python）；uuid-backport（PyPI）
- PostgreSQL 官方：18 发布公告（2025-09-25）、版本策略页（18.6 / 17.11 / 16.15，19 beta 3）
- 沙箱: healeycodes.com《Running Untrusted Python Code》；lobste.rs 相关讨论（内核攻击面）；northflank.com / edera.dev / onidel.com（Kata vs Firecracker vs gVisor 对比）；gvisor.dev rootless 文档；agent-sandbox.sigs.k8s.io（Firecracker Sandbox）；blaxel.ai（LLM 代码沙箱 microVM 指南）
- 异步模式: FastAPI 官方 async 文档；starlette `run_in_threadpool`；Stack Overflow / BBC CloudFit asyncio 系列；FastAPI GitHub discussion #15353（线程池死锁实录）
- 模板评估: github.com/fastapi/full-stack-fastapi-template；fastapi.tiangolo.com/project-generation/；github.com/fastapi/fastapi/discussions/15311（复杂应用需解耦层的共识）；docs.astral.sh/uv/concepts/projects/workspaces/

