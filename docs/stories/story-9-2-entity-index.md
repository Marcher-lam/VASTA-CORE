---
story_key: 9-2-entity-index
baseline_commit: 750801c
---

# Story 9.2: 实体索引与检索维度补全（G1）

**Status:** review

## Story

As a 团队分析师,
I want 业务实体维度的专用索引与别名检索,
So that 按订单号/客户号等实体键秒级定位全部相关证据。

## Acceptance Criteria

**Given** G1 双后端与既有 payload_equals 检索
**When** 工件/事件登记实体标签（entity_index 表或 PG 等价）
**Then** search_by_entity 命中跨事件/工件/派生物三类；空/未知实体明确空结果
**And** WAIVER W-2 解除（实体索引 + 检索测试入矩阵复评）（FR-013 字母级收口）

## Tasks/Subtasks

- [x] T1: SQLite `entity_index` + `entity_alias` 表（schema v3→v4：旧库
      CREATE IF NOT EXISTS 自动迁移）——登记入口：save_artifact(entities=...)
      事务内写入（kind=artifact）+ 事件 payload.entity_refs 自动登记
      （kind=event，run_id:seq 引用）
- [x] T2: `search_by_entity(store, key, value, *, tenant, project)` ——
      跨三表命中（索引 + 血缘一跳 derived_assets JOIN 派生物并入）；
      `register_entity_alias` 别名（检索时自动解析为 canonical）；
      作用域 fail-closed（validate_scope_pair）
- [x] T3: PG 等价 DDL（entity_index/entity_alias 表 + 索引；save_artifact
      entities 参数写入）——与 SQLite 同契约；DSN 门控集成测试不变
- [x] T4: WAIVER W-2 解除——矩阵 FR-013 行翻 FULL + 复评记录四
      （P1 32/32、Overall 39/39=100% PASS 维持）
- [x] T5: 测试 `tests/test_entity_index.py` 7 条（跨三类命中/别名解析/
      作用域隔离/未知实体空/空白作用域拒/键区分不串/迁移 v3→v4）；
      全量 524 passed +2 skipped；ruff 全绿；import-linter 2 契约 KEPT

## Dev Notes

- 实体标签形态：`entities={"order_id": "A102", "customer": "C-88"}`——
  键值对；别名解决同一实体多写法（A-102 vs A102）。
- 血缘一跳：派生物经 derived_assets 表 JOIN 命中（不递归全链——
  全链属 9.4 权限 Story 的深度需求，本 Story 检索面一跳够用）。
- 检索面作用域 fail-closed：空/空白作用域对拒（与既有 search 守卫一致）。

## Dev Agent Record

### Debug Log

- **to_thread 漏传 entities**：save_artifact async→sync 签名两侧 + 调用
  三处，首次补丁只改了一处——TypeError 9 参数 vs 10 暴露；教训：
  双层签名（async wrapper + sync body）加参必须三处同步（签名/签名/调用）。
- **artifact 实体索引块被 to_thread 不匹配回退**：首次补丁的目标字符串
  因签名不匹配 assert 失败后整块被跳过——只写入了 event 侧；测试
  `artifact in kinds` 失败暴露后重加。
- 既有迁移测试 `assert version == 3` 需随 schema v4 更新（v3→v4 是新表
  CREATE IF NOT EXISTS，无列变更——旧库零破坏）。

### Completion Notes

- 实体索引双写路径：工件 save（事务内 kind=artifact/sha）与事件 append
  （payload.entity_refs → run_id:seq 引用）；血缘一跳在检索时 JOIN 并入
  （不预写——派生物的实体继承是查询语义而非存储冗余）。
- 别名登记后检索透明解析（同键别名表命中即替换 canonical）——
  A-102 与 A102 同键命中同一实体。
- WAIVER W-2 解除入矩阵复评记录四：FR-013 字母级收口（六维检索中
  「业务实体」维度从 payload_equals 通用覆盖升级为专用索引+别名）。

### File List

- packages/vasta-storage/src/vasta_storage/sqlite_store.py（schema v4 +
  entities 参数 + search_by_entity/register_entity_alias + 事件实体登记）
- packages/vasta-storage/src/vasta_storage/pg_store.py（entity DDL + PG 登记）
- tests/test_entity_index.py（新增：7 条）
- tests/test_derived_lineage.py（迁移断言 v3→v4）
- test-artifacts/traceability-matrix.md（复评记录四：W-2 解除 FR-013 FULL）
- docs/sprint-status.yaml（9-2 状态）

## Change Log

- 2026-09-10: Story 9.2 实现完成（T1–T5 全过，524 passed +2 skipped，W-2 解除）→ review
