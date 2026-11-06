# 贡献指南

感谢关注 VastaCore——面向长程 Agent 的认知与执行可靠性平台。

## 环境准备

```bash
# 需要：Python ≥ 3.12、uv ≥ 0.12
git clone git@github.com:Marcher-lam/VASTA-CORE.git
cd VASTA-CORE
uv sync --all-packages        # 必须带 --all-packages（根项目无依赖声明，默认不装工作区成员）
uv run pytest -q              # 应全绿（平台差异见下）
```

## 三道门禁（提交前必过）

```bash
uv run pytest -q                          # ① 测试
uv run ruff check packages tests examples # ② lint
uv run lint-imports                       # ③ 架构依赖契约（AD-1 强制）
```

CI（GitHub Actions，Python 3.12/3.13 矩阵）跑同一套门禁；失败时日志尾部会自动提交到 `ci-logs/*` 分支便于诊断。

**平台差异说明**：少数测试按平台诚实跳过（如 RLIMIT_AS 内存强制在 macOS/Windows 不可执行）——本地跳过数与 CI 略有差异是预期行为，失败才是问题。

## 架构红线（改代码前必读）

- **AD-1 依赖单向**：一切指向 `vasta-protocols`；核心包不 import `vasta-adapters`/`vastacore-sdk`；`lint-imports` 会拦
- **六段链唯一通道**：状态改变型动作只走 `execute_contracted`，SDK 不旁路（AD-4）
- **fail-closed**：依赖不可用 → 拒绝而非放行（AD-12）；新增外部依赖面遵循同语义
- **事件先行**：新事件类型须过族闭集校验并回写目录快照（`vasta_protocols/catalog_gen`；新系统流同理走 `stream_catalog_gen`——守卫测试零漂移）

## 提交约定

- **Story 驱动**：功能开发按 `docs/epics.md` 拆 Story；实现含三件套——代码 + 测试 + `docs/stories/story-*.md` 记录（AC 映射/Dev Notes/Debug Log）
- **显式路径 git add**（禁 `-A` 兜底）；一次提交一个语义单元
- **簿记同步**：完成后回写 `docs/sprint-status.yaml` 对应键
- 提交信息第一行说清「做了什么 + 为什么」（可含根因），中文为主

## 文档约定

- 过程档案（`docs/reviews/`、复盘、终检）**带日期、只增不改**
- 里程碑汇总进 [CHANGELOG.md](CHANGELOG.md)；细目以 git log 为准
- 指南类文档（quickstart/README）保持与代码同步，发现失实随手修

## PR 清单

见 [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md)——三道门禁绿、测试补齐、Story 簿记、架构红线自查。

## 安全问题

请勿开公开 issue 报安全漏洞——见 [SECURITY.md](SECURITY.md)。
