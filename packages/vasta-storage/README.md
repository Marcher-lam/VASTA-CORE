# vasta-storage

**Evidence Store**：SQLite 事件库 + sha256 分桶 CAS（内容寻址原始证据）——「先落盘、哈希校验、才允许被事件引用」（AD-3）。

## 职责

- **事件持久化**：append-only，`(run_id, seq)` 唯一；租户/项目作用域（AD-7）
- **CAS 工件库**：字节级内容寻址、防篡改检测（哈希不对拍即 `artifact.corrupted`）
- **多维检索与实体索引**：按来源/元数据/实体键取回证据
- **派生血缘**：`save_derived` 全链路（派生物 → 源 → 参数 → 版本），回链校验
- **生命周期面**：删除证明（不含内容）、证据权限、备份/恢复（WAL 一致性快照）
- **可选后端**：PG（`pg` extra）与 S3 兼容 blob（`s3` extra）——同契约双后端

## 依赖位置（AD-1）

依赖 `vasta-protocols`；被 runtime/sdk 消费。

## 测试锚点

`tests/test_sqlite_storage.py`、`tests/test_evidence_search.py`、`tests/test_derived_lineage.py`、`tests/test_lifecycle.py`
Story 档案：`docs/stories/story-1-4-*`、`story-2-*`
