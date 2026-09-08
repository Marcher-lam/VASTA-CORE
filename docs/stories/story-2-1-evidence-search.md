---
story_key: 2-1-evidence-search
baseline_commit: 0c6953f8960864367bf1c9671d9212cdc4111668
---

# Story 2.1: 多维检索索引

**Status:** review

## Story

As a Agent 开发者,
I want 按时间窗、动作、事件类型、区域、对象与业务实体标签组合检索证据,
So that 排障时能直接定位相关证据而不是翻全量记录。

## Acceptance Criteria

**Given** 含多类型 Artifact 与事件的 Run 历史
**When** 任意维度或维度组合查询
**Then** 返回的 Artifact/Event 引用全部可取回且哈希校验通过——无死链（FR-013）
**And** 检索只经租户引用映射（AD-14），跨作用域查询被拒绝

## Tasks/Subtasks

- [x] 1. 事件检索 search_events（vasta-storage）：**作用域强制**（tenant+project 成对必填）；维度 = run_id / 事件类型（精确或族前缀 `observation.`）/ 时间窗（ts_from/ts_to）/ 载荷等值过滤（json_extract，键白名单防注入）；结果按 ts+run+seq 排序、可限条数
- [x] 2. Artifact 检索 search_artifacts：经 artifact_refs JOIN（AD-14 可达性）；维度 = source / classification / 标签（tags，新列 tags_json）/ 入库时间窗
- [x] 3. 无死链保证：search_events 返回前校验每条事件的 artifact_refs 在作用域内可达且 blob 存在，死链抛 `search.dead_links`（证据完整性问题要响亮）
- [x] 4. 动作维度落地：引擎在 step 执行期间的观察载荷携带 `last_action`（载荷字段，非事件族——与 Epic 3 action 管道不冲突）；`payload_equals={"last_action": tool}` 即按动作检索
- [x] 5. schema 迁移 v1→v2（artifacts 加 tags_json 列，AD-9 首次演练：旧库 ALTER、新库内联、user_version 检查拒读过新）
- [x] 6. save_artifact 增 tags 参数（去重时标签合并为并集）
- [x] 7. 测试：单维×组合、作用域隔离（他租户事件不可见/引用不可达）、半作用域拒绝、死链抛错、标签检索与合并、按动作检索端到端（quickstart 数据上 `last_action=right` 命中）、AC 逐条
- [x] 8. 对照 AC 验证并更新记录

## Dev Notes

- 检索 API 是 storage 服务扩展（非协议端口方法）——端口保持最小（AD-1 不变）。
- ts 以 ISO8601 UTC 字符串存储，字典序即时间序（信封校验已保证 UTC）。
- 区域/对象/业务实体三类领域维度以 tags 承载（保存方打标）；事件维度走结构化列+载荷过滤。
- 迁移放行 v1→v2，拒读 >2（1.4 已有 user_version 守卫，升级上限同步改 2）。

## Dev Agent Record

### Implementation Plan

1. `search.py`：EvidenceSearchMixin（search_events / search_artifacts / _assert_no_dead_links），挂载 SqliteStorage；json_extract 键白名单（`^[A-Za-z0-9_]+$`）防路径注入；作用域成对强制复用 _scope 模块。
2. `sqlite_store.py`：artifacts 增 tags_json（新库内联/旧库 ALTER，user_version→2）；save_artifact 增 tags 参数、去重命中时标签并集合并；`_validate_scope_pair` 抽到 `_scope.py`（解 mixin 循环导入）。
3. `runner.py`：step 期间 `self._current_action` 生效，_record_observation 载荷携带 `last_action`（finally 清除，不泄漏到 reset/observe 路径）。

### Debug Log

- 循环导入（mixin ↔ store）：作用域校验抽独立 `_scope.py` 解决。
- **测试抓到真实缺陷**：同 seed 不同 run_id 的两个 Run 种子派生 event_id 完全相同，撞 events.event_id 全局唯一约束——ID 流改为掺入 run_id（`{seed}:{run_id}:event-id`），同 run_id+seed 仍逐字节可再生，不同 run 同 seed 不再碰撞。这正是 1.5 评审"RNG 双流"修复的边界遗漏。
- ruff 两处测试未用变量清理。

### Completion Notes

AC 逐条验证：
1. **任意维度/组合查询** — 单维：事件类型精确（run.created=1）/族前缀（observation. 四类全命中且逐条可按 (run,seq) 取回）/时间窗（未来窗空、过去窗全量）；组合：run+族前缀+payload_equals 三维叠加精确命中 stop 动作的两条观察。✅
2. **无死链（FR-013）** — `test_all_refs_retrievable_and_hash_verified`：检索结果中每个 artifact_ref 均可按作用域取回且 sha256 重算一致、载荷可解析；`test_dead_blob_raises`：删除被引用 blob → search_events 抛 `search.dead_links`（响亮失败不静默过滤）。✅
3. **只经租户引用映射 + 跨作用域拒绝（AD-14）** — 事件检索作用域强制且仅返回本租户行（t-a 查询不见 run-b）；半作用域调用抛 `scope.half_pair`；artifact 检索经 refs JOIN（无引用租户查询为空）；载荷键注入尝试抛 `search.bad_key`。✅
4. **动作维度** — 引擎观察载荷携带 last_action；`payload_equals={"last_action":"go"}` 精确命中 step("go") 的 2 条观察；标签维度（区域/对象/业务实体载体）：tags 检索单标签与多标签组合命中、去重并集合并验证。✅
5. **schema 迁移（AD-9 首次演练）** — 手工构造 v1 旧库 → 打开即迁移（user_version=2 + ALTER 补列）→ 迁移后带标签存取正常；v99 未来库拒读。✅

回归：全套 137 passed（前序 123 + 本故事 14）；ruff 全绿；import-linter 契约 KEPT；quickstart 实跑 17 事件/14 证据不变（last_action 为载荷字段，不改变事件计数）。

## File List

- packages/vasta-storage/src/vasta_storage/search.py（新建）
- packages/vasta-storage/src/vasta_storage/_scope.py（新建：作用域校验，解循环导入）
- packages/vasta-storage/src/vasta_storage/sqlite_store.py（修改：tags 列+迁移 v2、save_artifact tags、mixin 挂载）
- packages/vasta-runtime/src/vasta_runtime/runner.py（修改：step 期间观察载荷携带 last_action）
- packages/vasta-runtime/src/vasta_runtime/runcontext.py（修改：ID 流掺入 run_id 防同 seed 跨 run 撞唯一键）
- tests/test_evidence_search.py（新建，14 测试）
- docs/stories/story-2-1-evidence-search.md（本文件）

## Change Log

- 2026-09-08：Story 2.1 实现完成——事件/Artifact 多维检索（作用域强制+无死链校验+载荷过滤防注入）、tags 维度与去重并集、schema v1→v2 迁移演练、last_action 动作维度；测试暴露并修复同 seed 跨 run 的 event_id 碰撞；137 测试全绿；全部 AC 验证通过，状态置 review。
