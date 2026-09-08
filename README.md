# VastaCore

面向长程、多模态、工具调用型 Agent 的**认知与执行可靠性平台**：保留原始证据、管理可修订认知、约束并核验行动、按需构建可执行世界模型。

当前状态：**Epic 1（可记录的 Agent Run）已交付**——L0 Observe-only 端到端闭环。

## 快速开始

```bash
uv sync --all-packages
uv run python examples/quickstart.py   # GridWorld → SQLite 证据库 → L0 全量记录
uv run pytest -q                        # 107+ 测试
```

详见 [docs/quickstart.md](docs/quickstart.md)。

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
