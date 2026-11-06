# VastaCore

面向长程、多模态、工具调用型 Agent 的**认知与执行可靠性平台**：保留原始证据、管理可修订认知、约束并核验行动、按需构建可执行世界模型。

当前状态：**六阶段（Epic 1–12）全量交付**——82 条 FR 全 delivered（2026-11-06 终检增补清偿：FR-002 五接入形态、FR-015/016 真实字节与识别引擎面、FR-084 商业分发全闭环）；1315+ 测试；属地运营三项（SLO 生产统计/真分布式部署/多区域演练）登记在册（[docs/project-final-review-addendum-2026-11-06.md](docs/project-final-review-addendum-2026-11-06.md)）。

## 快速开始

```bash
uv sync --all-packages              # 注意：必须带 --all-packages（根项目无依赖声明，默认 sync 不装工作区成员）
uv run python examples/quickstart.py   # GridWorld → SQLite 证据库 → L0 全量记录
uv run pytest -q                        # 1315+ 测试
```

详见 [docs/quickstart.md](docs/quickstart.md)。

## 把你的 Agent 接进来（五形态，SDK 三步起，≤3 工程日）

```python
from vastacore import AgentSession

session = await AgentSession.create(
    env=my_env,                                  # ① 你的环境（实现 EnvironmentAdapter 五方法）
    tools=[my_tool],                             # ② 你的工具（ToolAdapter，清单强制风险分类）
    contracts={"my_tool": {...}},                # ③ 契约模板（七必填段；risk 自动取清单分级）
    root=".vasta", seed=42,
)
async with session:
    await session.start()
    await session.reset()
    await session.act(Action(tool="my_tool", args={...}))   # 六段链自动走：契约→策略→执行→核验→审计
```

- `act()` 对网关注册工具自动构造契约并走 `execute_contracted`（核验/恢复/幂等全自动）；无模板 **fail-closed 拒执行**
- 完整从零示例（自定义 env + 工具 + 模板 + 回放）：`examples/onboarding/from_zero.py`
- 接入计时演练与已知摩擦点：[docs/onboarding-log.md](docs/onboarding-log.md)（SM-5 证据，端到端 1–3 小时）
- **五接入形态**（FR-002 全量）：SDK（上方三步）｜HTTP 服务（`ops.service.create_app`）｜轨迹导入｜ToolProxy（既有工具零重写）｜**middleware**（`VastaMiddleware`——既有编排器 dict 进出零改造）｜**sidecar**（`python -m vastacore.execution.sidecar`——任意语言 loopback 伴生，Agent 侧只说 HTTP）

## 端到端原型（examples/）

| 目录 | 一句话 | 详情 |
|---|---|---|
| `examples/cua/` | **macOS 桌面 CUA 原型**（P0–P5 全 PASS，零侵入只调公共 API）：SoM 视觉感知 + 点击反推标定 + AX 确定性核验 + 六段链执行 + R3 人在环 + 字节级确定性回放 + Claim 图 UI-记忆（改版=反例级联失效）+ guardrails 四层闸 + 任务集 eval；附 23 条 macOS 桌面实测坑位表 | [examples/cua/README.md](examples/cua/README.md) |
| `examples/rag/` | **多模态 RAG 原型**（零侵入只调公共 API）：MinerU 图文 PDF 解析 + L1 向量粗筛 + L2 原始证据兜底（邻域扩展/原图直读/图文双向对齐）+ 引用回源核验 + 模型响应内容寻址缓存；21 题四层消融评测（X 跨模态层 L2 兜底 +0.67 裁判分，关键词覆盖 +13.1pp），设计决策见 DESIGN.md | [examples/rag/README.md](examples/rag/README.md) |

CUA 是平台论点的完整实证——「看图决策的 agent 被契约约束、被 AX 事实核验、幻觉被 Supervisor 熔断拦停、UI 改版被记忆失效机制捕获、R3 写盘必须人在环」：

```bash
uv run python -m examples.cua.probe_grounding        # P0 视觉 grounding 门禁（11/11）
uv run python -m examples.cua.run_task               # P1 六段链旗舰（42×3=126）
uv run python -m examples.cua.loop                   # P2-A VLM 自主闭环（vision/memory/auto）
uv run python -m examples.cua.textedit               # P2-B R3 人在环审批（原生 approval 事件）
uv run python -m examples.cua.replay --run-id <id>   # P3 确定性回放（归一化流逐字节一致）
uv run python -m examples.cua.run_memory             # P4 cognition UI-记忆三相
uv run python -m examples.cua.eval                   # P5 任务集批量评测（guardrails 值守）
```

## 仓库布局

```text
packages/
  vasta-protocols/   # 依赖根（AD-1）：事件信封 + 五协议 + 契约测试套件
  vasta-storage/     # Evidence Store：SQLite 事件库 + sha256 分桶 CAS
  vasta-cognition/   # Claim 图与记忆（Epic 5）
  vasta-contracts/   # ActionContract 与核验器（Epic 3）
  vasta-policy/      # 策略引擎（Epic 3）
  vasta-runtime/     # RunEngine/Supervisor/RunContext
  vasta-model-lab/   # 世界模型沙箱与验证（Epic 6）
  vasta-eval/        # 消融与评测（Epic 7）
  vastacore-sdk/     # 组装根（AD-1 唯一允许引用适配器的位置）
  vasta-adapters/    # 适配器实现（GridWorld 等）
examples/            # cua（桌面 CUA）/ rag（多模态检索）/ onboarding（从零接入）
tests/  docs/
```

**依赖规则（AD-1）**：一切指向 `vasta-protocols`；适配器不被 import（`uv run lint-imports` 强制）。

## 文档地图

- **[docs/README.md](docs/README.md)** —— 文档索引（指南 / 架构 / 原型 / 过程档案分层）
- 上手：[docs/quickstart.md](docs/quickstart.md)（15 分钟首跑）→ [docs/onboarding-log.md](docs/onboarding-log.md)（接入演练）
- 架构：[ARCHITECTURE-SPINE](docs/architecture/architecture-VastaCore-2026-09-08/ARCHITECTURE-SPINE.md)（15 条 AD）
- 产品：[docs/briefs](docs/briefs/)（简报）→ [docs/prds](docs/prds/)（PRD）→ [docs/epics.md](docs/epics.md)（Epic/Story）→ [docs/stories](docs/stories/)（Story 记录）
- 里程碑：[CHANGELOG.md](CHANGELOG.md)（阶段汇总；按 Story 提交，git log 即细目）

## 开发

```bash
uv run pytest -q              # 测试
uv run ruff check packages tests examples   # lint
uv run lint-imports           # 架构依赖契约
```

CI（GitHub Actions）：lint → import-linter → pytest（Python 3.12/3.13 矩阵）。
