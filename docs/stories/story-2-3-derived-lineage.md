---
story_key: 2-3-derived-lineage
baseline_commit: 4ed7f32ad1d53da80b35daf32e123e8b5c4d6a76
---

# Story 2.3: 派生血缘与回链校验

**Status:** review

## Story

As a 平台工程师,
I want 每个 DerivedAsset 登记源 Artifact、变换参数与版本并可一键回链校验,
So that 摘要与抽取永远只是索引层、不是唯一事实源。

## Acceptance Criteria

**Given** 由源 Artifact 生成的摘要/状态抽取派生物
**When** 查看派生物并执行回链
**Then** 源 Artifact 取回且哈希校验通过、变换参数与版本完整展示（FR-012，对应 AC-03）
**And** 源被删除时派生物标记"来源不可再验证"而非静默可用

## Tasks/Subtasks

- [x] 1. derived_assets 表（schema v3 迁移：新表 CREATE IF NOT EXISTS，无 ALTER；user_version→3，拒读 >3）
- [x] 2. save_derived(payload, *, source_sha, transform, params, transformer_version, scope)：载荷照走 CAS（save_artifact），血缘记录登记源/变换/参数/版本/作用域
- [x] 3. lineage(derived_sha, scope) → 血缘记录列表（多源支持：同派生物可由多源产生）
- [x] 4. verify_lineage(derived_sha, scope) → 逐记录校验：派生载荷与源均可取回且哈希通过 = verified；源缺失 = source_missing（"来源不可再验证"，不静默）；源损坏 = source_corrupted
- [x] 5. 测试：登记→回链全绿（参数/版本完整展示）；源 blob 删除→source_missing；多源记录；作用域隔离与半作用域拒绝；AC-03 对应断言（一键回到原始证据并校验）
- [x] 6. 对照 AC 验证并更新记录

## Dev Notes

- 血缘行作用域化（tenant/project 入复合主键）；派生载荷本体仍走全局 CAS + refs（AD-14 语义一致）。
- 删除生命周期（FR-017）属 Stage 3；本故事的"源被删除"以 blob 缺失模拟（评审已确立 dead-link 语义同款）。
- 同 (derived, source, transform) 重复登记幂等（OR IGNORE）。

## Dev Agent Record

### Implementation Plan

1. `lineage.py`：LineageMixin——save_derived（载荷经 save_artifact 入 CAS + 血缘行 OR IGNORE 幂等）/lineage（多源列表，作用域过滤）/verify_lineage（派生与源逐记录 get_artifact 哈希校验；missing/corrupted 显式状态；无记录 → lineage.not_found）。
2. schema v3：derived_assets 复合主键 (tenant, project, derived, source, transform)；CREATE IF NOT EXISTS 式迁移（v2 库直开即升级）。
3. 簿记时间抽取 `_bookkeeping.py`（AD-5 白名单从 sqlite_store.py 换绑到该模块——lineage 落 storage 扫描范围后必须收敛簿记例外面）。

### Debug Log

- v3 落地连带两处：lineage 方法内 `datetime.now` 触发 AD-5 静态扫描（storage 已在扫描范围）→ 簿记时间抽 `_bookkeeping.py` 共享、白名单换绑；2.1 的 v1→v2 迁移测试硬编码 version==2 → 改 `>= 2`（旧库直接升到当前版）。
- LineageVerification 一处引号笔误与 sqlite_store 的 E402（原位替换产生的 import 位置），即时修正。

### Completion Notes

AC 逐条验证：
1. **回链全绿 + 参数/版本完整（FR-012/AC-03）** — `test_register_and_link_back_full_green`：lineage 返回源 sha/transform/params（逐键断言）/transformer_version/created_at；verify_lineage all_verified；派生物一键取回源 Artifact 且字节全等（哈希校验在 get_artifact 内）。✅
2. **源删除→不可再验证（不静默）** — `test_source_deleted_marks_unverifiable`：删源 blob 后 all_verified=False 且 status=source_missing；`test_source_corrupted_detected`：篡改→source_corrupted（区分缺失与损坏）。✅
3. **多源血缘** — 同派生内容登记两源：载荷 CAS 去重（同 sha）+ 两条血缘记录；重复登记幂等（OR IGNORE，1 条）。✅
4. **作用域** — lineage 按租户隔离（t-b 查空）；半作用域拒绝；未知派生物 lineage.not_found。✅
5. **schema v3 迁移** — v2 库直开升级（新表 CREATE IF NOT EXISTS + user_version=3）并完成登记→回链全链路；v99 仍拒读（复用 2.1 用例语义）。✅

回归：全套 157 passed（前序 148 + 本故事 9）；ruff 全绿；import-linter 契约 KEPT。**Epic 2 全部 3 个 Story 完成。**

## File List

- packages/vasta-storage/src/vasta_storage/lineage.py（新建）
- packages/vasta-storage/src/vasta_storage/_bookkeeping.py（新建：簿记时间，AD-5 白名单收敛）
- packages/vasta-storage/src/vasta_storage/sqlite_store.py（修改：schema v3、LineageMixin 挂载、簿记导入）
- packages/vasta-storage/src/vasta_storage/__init__.py（修改：导出血缘族）
- tests/test_determinism_guards.py（修改：白名单换绑 _bookkeeping.py）
- tests/test_evidence_search.py（修改：迁移断言 >=2）
- tests/test_derived_lineage.py（新建，9 测试）
- docs/stories/story-2-3-derived-lineage.md（本文件）

## Change Log

- 2026-09-08：Story 2.3 实现完成——派生血缘登记/多源列表/一键回链校验（missing/corrupted 显式状态）、schema v3 迁移、簿记时间例外面收敛；157 测试全绿；全部 AC 验证通过，状态置 review；Epic 2 收口。
