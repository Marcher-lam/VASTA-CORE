# VastaCore 文档地图

> 上手顺序：[README](../README.md)（是什么/三步接入）→
> [quickstart](quickstart.md)（15 分钟首跑）→
> [examples/cua](../examples/cua/README.md)（端到端原型）→ 按需查下表。

## 指南（读这一层就够开发）

| 文档 | 内容 |
|---|---|
| [quickstart.md](quickstart.md) | 15 分钟首跑：GridWorld → SQLite 证据库 → L0 全量记录 |
| [onboarding-log.md](onboarding-log.md) | 外部团队接入计时演练与已知摩擦点（SM-5 证据） |
| [epics.md](epics.md) | Epic 1–12 全部故事与验收标准（FR/NFR 对照） |
| ../README.md | 三步接入（AgentSession）、仓库布局、开发命令 |

## 架构

| 文档 | 内容 |
|---|---|
| [architecture/architecture-VastaCore-2026-09-08/ARCHITECTURE-SPINE.md](architecture/architecture-VastaCore-2026-09-08/ARCHITECTURE-SPINE.md) | 15 条架构决策（AD-1 依赖根 / AD-2 事件溯源 / AD-5 确定性重放 / AD-12 fail-closed…）、三面运行拓扑、栈与结构种子 |

## 端到端原型（examples/，零侵入）

| 目录 | 内容 |
|---|---|
| [../examples/cua/](../examples/cua/README.md) | macOS 桌面 CUA（P0–P5 全 PASS）：SoM 感知 + 六段链 + AX 核验 + R3 审批 + 字节级回放 + Claim 图 UI-记忆 + guardrails 闸 + eval；23 条实测坑位表 |
| [../examples/rag/](../examples/rag/README.md) | 多模态 RAG：两层检索 + 引用回源核验 + 消融（运行数据 `.vasta-rag/` 不入库） |
| [../examples/onboarding/from_zero.py](../examples/onboarding/from_zero.py) | 从零接入完整演练（自定义 env + 工具 + 契约模板 + 回放） |

## 过程档案（带日期，只增不改——历史记录）

- [briefs/](briefs/)：产品简报（蓝图之源）
- [prds/](prds/)：PRD 与对账（34 ★FR / 387+ 测试的验收基线）
- [reviews/](reviews/)：逐 Epic code review 与修复记录
- [reviews-epics-validation.md](reviews-epics-validation.md)、
  [project-final-review-2026-09-14.md](project-final-review-2026-09-14.md)、
  [project-final-review-addendum-2026-11-06.md](project-final-review-addendum-2026-11-06.md)：
  阶段性总检
- `epic-*-retro-*.md`：逐 Epic 复盘
- [stories/](stories/)：Story 级实现记录

> 变更入口：里程碑汇总见根目录 [CHANGELOG](../CHANGELOG.md)
> （按 Story 提交，git log 即细目）。
