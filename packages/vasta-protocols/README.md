# vasta-protocols

**依赖根（AD-1）**：事件信封 schema + 五协议端口 + 契约测试套件——整个 monorepo 唯一被所有包依赖、自身零依赖的基座。

## 职责

- **事件信封（EventEnvelope）**：`run_id/seq/type/parent_event_id/ts/tenant_id/project_id/event_id`，`(run_id, seq)` 唯一约束（AD-2），13 事件族封闭集，schema 带版本（FR-001）
- **五协议端口**：`EnvironmentAdapter` / `ToolAdapter` / `ModelAdapter` / 存储 / 核验器——实现方写适配器，平台只面向端口
- **契约测试套件**：驱动任意适配器实现的端口级一致性检查
- **事件目录与流清单守卫**：`EVENT_FAMILIES` / `SYSTEM_STREAMS` 从代码发射点生成（防手工快照漂移）
- **统一 Sequencer**：事件信封构造/seq 分配唯一入口

## 依赖规则

一切包可依赖本包；本包不依赖任何 `vasta-*` 包（import-linter 强制）。

## 测试锚点

`tests/test_workspace.py`、`tests/test_catalog_guard.py`、`tests/test_stream_catalog_guard.py`
Story 档案：`docs/stories/story-1-1-*`
