# VastaCore 文档地图

> 上手顺序：[README](../README.md)（是什么/三步接入）→
> [quickstart](quickstart.md)（15 分钟首跑）→
> [examples/cua](../examples/cua/README.md)（端到端原型）→ 按需查下表。
>
> 根 [README](../README.md) 的「文档目录」收录**读者要用的那部分**；
> 本文件是**全量地图**——含过程档案的逐组索引。

## 指南（读这一层就够开发）

| 文档 | 内容 |
|---|---|
| [quickstart.md](quickstart.md) | 15 分钟首跑：GridWorld → SQLite 证据库 → L0 全量记录 |
| [onboarding-log.md](onboarding-log.md) | 外部团队接入计时演练与已知摩擦点（SM-5 证据） |
| [epics.md](epics.md) | Epic 1–12 全部故事与验收标准（FR/NFR 对照） |
| ../README.md | 三步接入（AgentSession）、仓库布局、开发命令 |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | 贡献流程：环境/三道门禁/架构红线/提交与簿记约定 |
| [../SECURITY.md](../SECURITY.md) | 安全策略：报告渠道与平台安全姿态 |

## 架构

| 文档 | 内容 |
|---|---|
| [architecture/architecture-VastaCore-2026-09-08/ARCHITECTURE-SPINE.md](architecture/architecture-VastaCore-2026-09-08/ARCHITECTURE-SPINE.md) | 15 条架构决策（AD-1 依赖根 / AD-2 事件溯源 / AD-5 确定性重放 / AD-12 fail-closed…）、三面运行拓扑、栈与结构种子 |

包级结构：`packages/*/README.md` ×10——每包职责 / 公共 API / 依赖位置 / 测试锚点，统一模板。

## 产品谱系（蓝图 → 简报 → PRD → Epic）

| 文档 | 内容 |
|---|---|
| [../VASTA-BRAINSTORM.md](../VASTA-BRAINSTORM.md) | 外部同类项目调研（VISTA 及 ARC-AGI-3 生态），蓝图输入 |
| [../plan.md](../plan.md) | 完整产品与实施方案 v2.0（0–36 个月蓝图，PRD 上游） |
| [briefs/brief-VastaCore-2026-09-08/brief.md](briefs/brief-VastaCore-2026-09-08/brief.md)（+[附录](briefs/brief-VastaCore-2026-09-08/addendum.md)） | 产品简报（定位一句话之源） |
| [prds/prd-VastaCore-2026-09-08/prd.md](prds/prd-VastaCore-2026-09-08/prd.md)（+[附录](prds/prd-VastaCore-2026-09-08/addendum.md)） | 需求基线：82 FR / 15 NFR / 7 里程碑信号 |

## 端到端原型（examples/，零侵入）

| 目录 | 内容 |
|---|---|
| [../examples/cua/](../examples/cua/README.md) | macOS 桌面 CUA（P0–P5 全 PASS）：SoM 感知 + 六段链 + AX 核验 + R3 审批 + 字节级回放 + Claim 图 UI-记忆 + guardrails 闸 + eval；23 条实测坑位表 |
| [../examples/rag/](../examples/rag/README.md) | 多模态 RAG：两层检索 + 引用回源核验 + 消融（[设计决策 DESIGN.md](../examples/rag/DESIGN.md)；运行数据 `.vasta-rag/` 不入库） |
| [../examples/onboarding/](../examples/onboarding/README.md) | 从零接入演练（[from_zero.py](../examples/onboarding/from_zero.py)：自定义 env + 工具 + 契约模板 + 回放五段） |

## 过程档案（带日期，只增不改——历史记录）

- [decision-log.md](decision-log.md)：跨切裁决记录（主仓裁决 / W-1 解除 / Apache-2.0 / 缺口清偿提前实施）
- [briefs/](briefs/)、[prds/](prds/)、[architecture/](architecture/) 目录内附带的
  reconcile-*、review-rubric、reviews/*：文档产出时的对账与评审痕迹
- [reviews/](reviews/)：逐 Epic code review ×12 与修复记录（含 [W-1 复评解除记录](reviews/w1-recheck-2026-11-06.md)——真实模型 10 种子全对、CI 入评测报告）
- [stories/](stories/)：Story 级实现记录 ×59
- `epic-*-retro-*.md`：逐 Epic 复盘 ×6
- [reviews-epics-validation.md](reviews-epics-validation.md)、
  [project-final-review-2026-09-14.md](project-final-review-2026-09-14.md)、
  [project-final-review-addendum-2026-11-06.md](project-final-review-addendum-2026-11-06.md)：
  阶段性总检
- [../test-artifacts/traceability-matrix.md](../test-artifacts/traceability-matrix.md)：验收标准 ↔ 测试覆盖追溯矩阵

> 变更入口：里程碑汇总见根目录 [CHANGELOG](../CHANGELOG.md)
> （按 Story 提交，git log 即细目）。

## 不入目录的文件（说明）

- `.memlog.md` ×3（briefs/prds/architecture 目录内）：文档产出过程的内部工作日志，非交付物
- `.pytest_cache/`、`.ci_*.log`：工具自动生成 / 本地临时日志
- `.github/PULL_REQUEST_TEMPLATE.md`：工程模板，入口在 [CONTRIBUTING](../CONTRIBUTING.md)
