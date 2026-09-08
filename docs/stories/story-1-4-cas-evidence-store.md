---
story_key: 1-4-cas-evidence-store
baseline_commit: a9a61d1613e76f0ef1d5924f2c234f27a959ae9d
---

# Story 1.4: 原始证据内容寻址入库

**Status:** review

## Story

As a Agent 开发者,
I want 每个原始观察与工具响应作为 sha256 内容寻址 Artifact 持久化并可校验取回,
So that 任何结论都能回到不可篡改的原始证据。

## Acceptance Criteria

**Given** Run 产生图像与 JSON 载荷
**When** Artifact 写入
**Then** 载荷按 sha256 前缀分桶存储（AD-3），元数据（来源/类型/大小/时间/分类/保留策略）事务写入，按哈希取回并校验成功（FR-010/011）
**And** 写入失败不产生"已捕获"状态（先落盘后引用，无部分状态）；一切实体含 `(tenant_id, project_id)` 作用域键且查询经作用域过滤（AD-7/AD-14：字节全局去重 + 租户引用映射分离）

## Tasks/Subtasks

- [x] 1. SqliteStorage（vasta_storage.sqlite_store）：events 表（PRIMARY KEY (run_id, seq) + event_id UNIQUE，冲突抛 DuplicateEventError——AD-2 真实落地）
- [x] 2. 分桶 CAS：objects/<sha[:2]>/<sha>，临时文件 + 原子替换写入，写后重读校验哈希（AD-3）；同哈希去重（字节全局单份）
- [x] 3. 元数据事务：artifacts 表（sha256 全局去重）+ artifact_refs 租户引用映射（AD-14），作用域键齐全（AD-7）；save 为"落盘→校验→事务元数据"顺序，任一步失败无部分状态
- [x] 4. 取回校验：按哈希读回并重算校验（篡改检测）；带租户参数取回时要求引用存在（跨租户不可达），未知哈希抛 artifact.not_found
- [x] 5. 通过 Story 1.1 的 StorageAdapterContract 契约套件（真实实现首过）+ 新测试：分桶布局/去重/作用域/原子性/篡改检测/持久化重开/引擎集成
- [x] 6. 对照 AC 验证并更新记录

## Dev Notes

- StorageAdapter 端口（1.1）签名最小（save_artifact(payload)->sha）；实现以带默认值的可选参数扩展（tenant/project/元数据），与端口兼容且满足 AD-9 minor 扩展规则。
- AD-10：sqlite3 为同步驱动 → 经 `asyncio.to_thread` 隔离（adapter 边缘合法），单连接 + 线程锁。
- 存储簿记时间戳（created_at/referenced_at）读系统时钟——非重放决策路径，不违反 AD-5；事件 ts 恒由调用方信封携带。
- "写动作 before/after 缺失率 0（NFR-001 六段链）"依赖 Epic 3 契约链，本故事交付其存储底座；PRD 已将该 NFR 归 FR-030 后果。
- schema PRAGMA user_version=1（AD-9 迁移起点）；不引入新三方依赖（sqlite3/hashlib 均为 stdlib）。

## Dev Agent Record

### Implementation Plan

1. `sqlite_store.py` 单模块：三表 schema（events 主键 (run_id,seq)+event_id 唯一；artifacts 哈希全局去重；artifact_refs 租户引用映射）+ WAL + user_version=1。
2. CAS 写入序：哈希 → 临时文件 → 重读校验 → 原子替换 → 事务写 artifacts(OR IGNORE)+artifact_refs(OR IGNORE)——"先落盘后引用"由顺序与原子性共同保证。
3. 异步端口：全部公开方法经 asyncio.to_thread；单连接 + threading.Lock（跨线程安全）。
4. 取回：租户参数存在时先验引用映射（AD-14 可达性），读后重算哈希（篡改 → artifact.corrupted）。
5. 测试：契约套件子类（tempfile 工厂）+ 分桶/去重双租户/元数据事务/落盘失败原子性/租户可达/篡改/SQLite 唯一约束/缺失事件/引擎集成重开。

### Debug Log

- 测试文件首版含两处草稿残渣（一个必然失败的套件占位类、一行无效导入语法），重写为干净版本后 15/15 通过——契约套件以 tempfile 工厂子类驱动，避免 fixture 与基类工厂的组合复杂度。
- `__init__` 导出误含两个无用名（json/new_event_id），即时清除。
- ruff 1 处自动修复（导入排序）；引擎集成测试末尾一段双重推导断言简化为直接循环。

### Completion Notes

AC 逐条验证：
1. **sha256 前缀分桶 + 元数据事务（AD-3/FR-010/011）** — `test_blob_written_to_sharded_path` 断言 objects/<sha[:2]>/<sha> 路径与内容；`test_metadata_transactional` 断言 mime/source/classification/retention/size/created_at 全字段落库。✅
2. **取回并校验（FR-011）** — Story 1.1 契约套件（含哈希往返校验）首次由真实 SQLite 实现驱动通过；`test_tampered_blob_detected` 磁盘级篡改 → artifact.corrupted。✅
3. **写入失败无"已捕获"状态（先落盘后引用）** — `test_blob_failure_leaves_no_captured_state`：分桶目录被占位阻塞写盘 → save 抛 OSError 且 artifact_info=None、引用表空——无部分状态。✅
4. **作用域键 + 查询过滤（AD-7/AD-14）** — 事件与引用均带 (tenant_id, project_id)（引擎集成断言逐事件校验）；`test_tenant_reachability_enforced`：同字节跨租户共享但 t-b 无引用即不可达；`test_list_scoped_by_tenant_and_classification` 查询经作用域过滤；`test_same_bytes_dedup_one_blob_two_refs` 字节全局单份+双租户映射独立。✅
5. **(run_id,seq) 唯一约束真实落地（AD-2）** — `test_duplicate_seq_on_real_sqlite` SQLite IntegrityError → DuplicateEventError；引擎集成测试证明 RunEngine 与 SqliteStorage 端到端工作且重开持久。✅

回归：全套 74 passed（前序 59 + 本故事 15）；ruff 全绿；import-linter 双契约 KEPT。未做：before/after 观察与事件的 Artifact 关联自动化（引擎侧 evidence capture 集成随 Story 1.7 端到端）、删除/保留生命周期（FR-017，Stage 3）。

## File List

- packages/vasta-storage/src/vasta_storage/sqlite_store.py（新建）
- packages/vasta-storage/src/vasta_storage/__init__.py（重写：公共 API 导出）
- tests/test_sqlite_storage.py（新建，15 测试）
- docs/stories/story-1-4-cas-evidence-store.md（本文件）

## Change Log

- 2026-09-08：Story 1.4 实现完成——SqliteStorage（事件库+分桶 CAS+租户引用映射+篡改检测+原子写入序）；Story 1.1 契约套件首过真实实现；引擎持久化集成验证；74 测试全绿；全部 AC 验证通过，状态置 review。
