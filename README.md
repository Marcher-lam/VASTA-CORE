# VastaCore

面向长程、多模态、工具调用型 Agent 的**认知与执行可靠性平台**：保留原始证据、管理可修订认知、约束并核验行动、按需构建可执行世界模型。

当前状态：**MVP（Epic 1–7）已交付并通过四轮 code-review**——34 条 ★FR 全量、387+ 测试；Stage 2（Epic 8 开发者接入体验）进行中。

## 快速开始

```bash
uv sync --all-packages              # 注意：必须带 --all-packages（根项目无依赖声明，默认 sync 不装工作区成员）
uv run python examples/quickstart.py   # GridWorld → SQLite 证据库 → L0 全量记录
uv run pytest -q                        # 490+ 测试
```

详见 [docs/quickstart.md](docs/quickstart.md)。

## 把你的 Agent 接进来（三步，≤3 工程日）

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
examples/  tests/  docs/
```

**依赖规则（AD-1）**：一切指向 `vasta-protocols`；适配器不被 import（`uv run lint-imports` 强制）。

## 文档地图

- 产品：[docs/briefs](docs/briefs/)（简报）→ [docs/prds](docs/prds/)（PRD）→ [docs/epics.md](docs/epics.md)（Epic/Story）
- 架构：[ARCHITECTURE-SPINE](docs/architecture/architecture-VastaCore-2026-09-08/ARCHITECTURE-SPINE.md)（15 条 AD）
- Story 记录：[docs/stories](docs/stories/)

## 开发

```bash
uv run pytest -q              # 测试
uv run ruff check packages tests examples   # lint
uv run lint-imports           # 架构依赖契约
```

CI（GitHub Actions）：lint → import-linter → pytest（Python 3.12/3.13 矩阵）。
