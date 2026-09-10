---
story_key: 9-3-lifecycle-deletion-proof
baseline_commit: 5a161fb
---

# Story 9.3: 数据生命周期与删除证明（G2）

**Status:** review

## Story

As a 合规负责人,
I want 热/温/冷分层、法律保留、删除请求与不含内容的删除证明,
So that 「已删除」是可审计的事实而非口头承诺。

## Acceptance Criteria

**Given** 集中存储中的证据与认知/评测/法律保留依赖
**When** 发起删除请求
**Then** 删除前依赖检查（活跃认知/评测/法律保留阻止并说明）；执行后留不含内容的证明事件（artifact.deletion_proved）
**And** 热/温/冷分层策略可配置；法律保留期间删除被拒且留痕（FR-017）

## Tasks/Subtasks

- [x] T1: `LifecyclePolicy`——tier 配置（hot/warm/cold 天数）+ `classify_artifacts`
      按工件年龄分层（dry-run 报告，不移动数据；时间取 protocols.ids 供给点）
- [x] T2: `place_legal_hold` / `release_legal_hold`——legal_holds 表
      （jurisdiction/note/placed_at/released_at）+ `request_deletion`
      依赖检查链：legal.hold_active / lifecycle.derived_dependency /
      lifecycle.entity_reference → 任一阻止即 blocked 且返回原因清单
      （DeletionBlocker model 携带 code + detail）
- [x] T3: 删除执行——blob 文件 + artifacts/artifact_refs 行清除，随后经
      Sequencer 落 `artifact.deletion_proved` 事件（sha/reason/tier/
      content_excluded=True——**不含任何内容字段**，守卫测试断言
      model_dump_json 不含原始 bytes）
- [x] T4: 测试 `tests/test_lifecycle.py` 9 条（按年龄分层/阈值可配/
      法保留阻+原因/release 后可删/删除证明事件+无内容/get 后 404/
      幂等二次删/派生依赖阻/实体引用阻）；全量 533 passed +2 skipped；
      ruff 全绿；import-linter 2 契约 KEPT

## Dev Notes

- 位置：`packages/vasta-storage/src/vasta_storage/lifecycle.py`。
- 删除不可逆——幂等：已删 sha 再请求返回成功（不重复发事件）。
- deletion_proved 落 "lifecycle" 系统流（Sequencer 系统流模式）。

## Dev Agent Record

### Debug Log

- 事件族坑：`deletion.proved` 不在 13 族封闭集 → `artifact.deletion_proved`
  （AD-5 事件族约束是硬校验——信封构造期即拒）。
- 测试断言 `in b` 遍历的是 DeletionBlocker model 而非字符串——改 `in b.code`。
- AD-5 determinism guard 抓到 `datetime.now(UTC)`（lifecycle.py 的
  classify_artifacts）→ 改 protocols.ids.now_utc 供给点——守卫有效性再次实证。

### Completion Notes

- 删除证明事件 `artifact.deletion_proved` 含 sha/reason/tier/
  content_excluded=True——不含原始内容的任何字段（守卫测试断言整个
  envelope JSON 不含原始 bytes）；落 "lifecycle" 系统流。
- 三类删除阻止：法律保留（jurisdiction 明细）、派生血缘依赖
  （derived_assets 引用）、实体索引引用——均返回结构化 blocker 清单
  （code + detail），非静默拒。
- 幂等：已删 sha 再请求返回 deleted（不重复发事件——proof 事件数守卫）。
- 分层 classify 为 dry-run 报告（不移动数据）；Stage 4 存储层迁移。

### File List

- packages/vasta-storage/src/vasta_storage/lifecycle.py（新增：LifecyclePolicy/
  place_legal_hold/release_legal_hold/request_deletion/classify_artifacts）
- packages/vasta-storage/src/vasta_storage/__init__.py（导出）
- tests/test_lifecycle.py（新增：9 条）
- docs/sprint-status.yaml（9-3 状态）

## Change Log

- 2026-09-10: Story 9.3 实现完成（T1–T4 全过，533 passed +2 skipped，ruff/lint 绿）→ review
