---
story_key: 8-7-lineage-recall
baseline_commit: f1bbc0e
---

# Story 8.7: 版本回溯收口——派生物与记忆（G4）

**Status:** review

## Story

As a 调试中的开发者,
I want 派生物与记忆一键回到当时版本,
So that 历史结论可复现、可对质。

## Acceptance Criteria

**Given** 任一派生物或 Claim ID
**When** 执行 as-of 时间点查询
**Then** 取回当时版本及其血缘链/证据链（哈希校验过）
**And** 查询只读零副作用（FR-061，验收性收口：复用既有血缘与 Claim.version）

## Tasks/Subtasks

- [x] T1: `claim_as_of(store, claim_id, *, as_of_seq | as_of_ts)`——重放
      claim.* 事件至指定点重建当时 Claim（含 version/status/evidence 链，
      语义与 CognitionService 投影同构）；该时点不存在 →
      `claim.not_found_at` 明确报错（不返回"最新"冒充当时）
- [x] T2: `derived_recall(store, sha)`——派生物回链收口：血缘 +
      verify_lineage 三态聚合（全 verified 才 verified，否则首个非绿态）+
      源/本体哈希校验取回（CAS 内容寻址天然不可变——as-of 语义记录于此）
- [x] T3: 只读零副作用守卫——查询前后事件数/工件数不变（两条测试锚定：
      派生侧 + 记忆侧）
- [x] T4: 测试 `tests/test_time_travel.py` 9 条（中途版本 v1/v2/v3 重放/
      seq 边界/时点不存在/未知主张/ts 分层时点/篡改源检测/未知派生拒/
      零副作用×2）；全量 454 passed +1 skipped；ruff 全绿；import-linter
      2 契约 KEPT

## Dev Notes

- 位置：`packages/vastacore-sdk/src/vastacore/timetravel.py`（组装根；组合
  storage+cognition 既有能力，零新存储面）。
- 复用 CognitionService._apply_claim_event 语义（事件重放），不复制投影逻辑——
  实现按事件类型驱动重建（与 cognition.py 同构，函数式）。
- 派生物侧不造时间机器：CAS 内容寻址即不可变；收口=回链+校验+语义说明。

## Dev Agent Record

### Debug Log

- Windows 时钟粒度使相邻 cognition 事件同 ts（propose/support 同微秒）——
  ts 过滤无法区分子毫秒事件。ts 语义测试改为手工构造明确分层时点
  （各事件间隔 1 秒）；seq 为主锚、ts 为辅的口径如实记录。
- verify_lineage 返回 LineageVerification 模型（非 dict）——按属性读并
  聚合三态：全记录 verified 且 derived_status=ok 才 verified。

### Completion Notes

- `claim_as_of`：事件重放真时间旅行——中途点取回当时版本（v1 proposed 无
  later evidence / v2 supported 含 sha:extra / 全量重放=当前态 v3 accepted，
  与投影一致）；越界时点明确报错不冒充。
- `derived_recall`：三态聚合 + 当时内容原样取回（payload 哈希寻址）；
  篡改源实测检出 source_corrupted。
- 零副作用双锚定：记忆重放与派生回链前后事件数/工件数不变。
- 全部 AC 满足；G4 的「已回溯类收口」完成（8.8 模型/策略版本化为新建项）。

### File List

- packages/vastacore-sdk/src/vastacore/timetravel.py（新增：claim_as_of/
  derived_recall/DerivedRecall）
- packages/vastacore-sdk/src/vastacore/__init__.py（导出）
- tests/test_time_travel.py（新增：9 条）
- docs/sprint-status.yaml（8-7 状态）

## Change Log

- 2026-09-09: Story 8.7 实现完成（T1–T4 全过，454 passed +1 skipped，ruff/lint 绿）→ review
