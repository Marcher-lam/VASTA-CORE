---
story_key: 9-1-storage-backends-sequencer
baseline_commit: 0d38828
---

# Story 9.1: 存储抽象双后端与统一 Sequencer（G1）

**Status:** review

## Story

As a 平台维护者,
I want StorageAdapter 的 PG/S3 双后端实现与全仓统一的 Sequencer/EnvelopeBuilder,
So that 团队档存储切换不动业务代码，五个手工信封构造点收敛为一。

## Acceptance Criteria

**Given** 现有 SQLite 实现与 5 处 EventEnvelope 手工构造点
**When** 实现 PostgresEventStore + S3BlobStore（StorageAdapter 同契约）与统一 Sequencer
**Then** 契约套件（storage 七项）对双后端全绿；五处构造点全部改经 Sequencer（grep 零残留）
**And** SQLite 路径行为不变（502 测试全绿）；Sequencer 并发分配无 seq 洞（测试锚定）（FR-070 存储侧；复盘 B1）

## Tasks/Subtasks

- [x] T1: `EventSequencer`（vasta-protocols，依赖根）——统一七字段信封构造 +
      seq 分配双模式：系统流模式（每发全量同步）与引擎快道模式（成功才推进，
      `EventSequencer.resuming` 重建入口）；跨实例并发安全靠 (run_id,seq)
      唯一约束 → DuplicateEventError 明确报错（测试锚定双模式冲突路径）
- [x] T2: **六站点收敛**（grep 守卫抓到第六处——ConflictService.resolve
      的手工构造，原计数遗漏）——runner._emit（快道）/ cognition._emit（系统流，
      _rebuild 语义修正：序列器自同步，重放恢复无需手动对齐游标）/
      model-lab _bookkeeping_stub / sdk trajectory（合成时钟注入序列器）/
      sdk versioning / cognition ConflictService.resolve 全部经 Sequencer
- [x] T3: `PostgresEventStore`（pg 可选 extra：find_spec 驱动检测——无驱动
      构造期明确报错）——events 表 (run_id,seq) 主键 + event_id 唯一、
      artifact bytea + ON CONFLICT 去重、artifact_scope 作用域映射分离
      （AD-14）；aiter_run_events 异步入口 + 同步迭代器循环内守卫；
      核心 StorageAdapter 契约（roundtrip/dup seq/artifact 哈希校验）；
      检索/血缘 mixins SQLite 耦合不在本 Story（后续 Story 诚实标注）
- [x] T4: `S3BlobStore`（s3 可选 extra：boto3 延迟导入 + **客户端可注入**）
      ——sha[:2] 分桶键布局、head 去重（AD-14 字节全局同址）、取回哈希校验
      （损坏实测检出 artifact.corrupted）、租户/项目入对象元数据（AD-9）
- [x] T5: 测试 16 条——test_sequencer.py 9（双模式/父链/续接/并发冲突/
      时钟与 id 注入/**grep 守卫**）+ test_team_backends.py 7（S3 Fake 注入：
      布局/去重/篡改检出/not_found/元数据作用域；PG 驱动门控报错 + DSN
      门控契约套件）；全量 517 passed +2 skipped（PG DSN + Windows resource）；
      ruff 全绿；import-linter 2 契约 KEPT

## Dev Notes

- Sequencer 归 protocols（cognition/runtime/model-lab 核心包都可用——AD-1）；
  只依赖 EventEnvelope + ids，零新依赖。
- PG/S3 驱动为**可选 extra**（pyproject optional-dependencies 声明、默认不装）
  ——开发环境零新增安装；集成测试 DSN/服务门控 skip（Windows resource 模块先例）。
- 团队档组合形态：PostgresEventStore(事件) + S3BlobStore(工件)——构造注入。
- runner 快道语义保持：seq 只在 append 成功后推进（评审修复语义不回退）。

## Dev Agent Record

### Debug Log

- cognition `_rebuild` 首版重构破坏投影（break-on-sync 逻辑错误）——
  根因是概念误置：系统流模式序列器每发全量同步，重放恢复根本无需手动
  对齐游标——修正为纯投影重建（只 apply claim 事件），代码更简。
- grep 守卫抓到**第六处**手工构造（ConflictService.resolve，Epic 5 遗留）
  ——"五处"计数本身是低估；守卫比人眼可靠，一并收敛。
- trajectory 收敛后 `events=seq` 变量残留 NameError——全量测试即时暴露。
- Windows 下 ruff --fix 删了 pg_store 的 asyncpg import 标注——改
  find_spec 驱动检测（ruff 友好且更 Pythonic）。

### Completion Notes

- **复盘 B1 闭合**：信封构造 + seq 分配收敛为 vasta-protocols 的
  EventSequencer 单一实现；生产写路径 grep 零手工构造（contract_suites
  的测试构造与 sqlite_store/pg_store 读路径除外——非生产写路径）。
- 双模式语义：系统流（cognition/registry/import/bridge——多实例并发安全）
  与引擎快道（runner——成功才推进不留洞）；跨实例冲突统一报
  DuplicateEventError。六站点行为零变更（全量测试绿）。
- Team 档双后端：PostgresEventStore（核心 StorageAdapter 契约）+
  S3BlobStore（工件面契约，客户端可注入零服务测试）——组合形态
  `PostgresEventStore(dsn, blob_store=S3BlobStore(...))`；检索/血缘
  mixins 的 PG 化留后续 Story（诚实范围）。
- 可选 extras 声明不装：开发环境零依赖变更；PG 集成测试 DSN 门控
  （无服务 skip——与 Windows resource 模块同策略）。

### File List

- packages/vasta-protocols/src/vasta_protocols/sequencer.py（新增：EventSequencer）
- packages/vasta-protocols/src/vasta_protocols/__init__.py（导出）
- packages/vasta-runtime/src/vasta_runtime/runner.py（_emit → 序列器快道）
- packages/vasta-cognition/src/vasta_cognition/cognition.py（_emit/_rebuild/
  ConflictService.resolve → 序列器系统流）
- packages/vasta-model-lab/src/vasta_model_lab/_bookkeeping_stub.py（emit → 序列器）
- packages/vastacore-sdk/src/vastacore/trajectory.py（emit → 序列器 + 合成时钟）
- packages/vastacore-sdk/src/vastacore/versioning.py（_emit_registry → 序列器）
- packages/vasta-storage/src/vasta_storage/pg_store.py（新增：PostgresEventStore）
- packages/vasta-storage/src/vasta_storage/s3_blobs.py（新增：S3BlobStore）
- packages/vasta-storage/src/vasta_storage/__init__.py（导出）
- packages/vasta-storage/pyproject.toml（pg/s3 可选 extras）
- tests/test_sequencer.py（新增：9 条含 grep 守卫）
- tests/test_team_backends.py（新增：7 条）
- docs/sprint-status.yaml（Epic 9 十四键 + 9-1 状态）

## Change Log

- 2026-09-10: Story 9.1 实现完成（T1–T5 全过，517 passed +2 skipped，ruff/lint 绿，六站点收敛 + 双后端）→ review
