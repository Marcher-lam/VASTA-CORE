---
story_key: 9-15-ops-slo
baseline_commit: 81c322c
---

# Story 9.15: 运营达标工程面（G4，NFR-004/006/014 收口）

**Status:** done

## Story

As a 平台运营负责人,
I want SLO 达成度测量、计时恢复演练与多进程部署形态的工程面,
So that 终检三处「属地运营」缺口的工程可验部分闭环。

## Acceptance Criteria

**Given** 事件流（run 终局）与 ops 系统流
**When** `slo_report` 按窗口统计并留痕；`timed_recovery_drill` 实测
RTO/RPO 并按 SLO 门判定；`drill_due`/`drill_executor` 与 9.9
Scheduler 组合实现 cron 定期演练
**Then** 3 OS 进程并发写同一 SQLite 库（每流单写者分区契约）各流
序号连续、event_id 全局唯一、全库完整性绿
**And** 留痕 evaluation.slo_reported / evaluation.drill_completed
（ops 流）；生产多区域演练与月度统计的运营执行仍属地化

## Tasks/Subtasks

- [x] T1: `ops/slo.py`——`SloSpec`/`SloReport`（可用率、错误预算
      允许/剩余、attained；**无数据 availability/attained=None——
      不伪造 100%**）；`slo_report` 从 run 终局事件按窗口统计（失败
      优先保守口径；全 UTC 比较）
- [x] T2: `record_slo_report` / 演练留痕——evaluation 族新事件
      slo_reported/drill_completed；新系统流 "ops" 入 SYSTEM_STREAMS
      （守卫零漂移——流与目录双快照回写）
- [x] T3: `timed_recovery_drill`——9.12 演练外套实测：RTO=墙钟，
      RPO=恢复库最新事件距演练开始的滞后期（灾难瞬间命中的数据损失
      上界）；rto_slo_s/rpo_slo_s 门判定（违反 → passed=False）
- [x] T4: 定期编排——`drill_due`（CronSpec.next_after 到期判定）+
      `drill_executor`（演练包成 Scheduler 执行器形态——摘要对象
      .runs/.success_rate 同 batch 契约）
- [x] T5: `tests/test_multiprocess_store.py`——3 真实子进程并发写
      同库（每流单写者），序号连续/event_id 唯一/完整性绿（NFR-006
      分布式形态工程锚点——真跨机属属地运营）
- [x] T6: 测试 `tests/test_ops_slo.py` 9 条——达成度与错误预算/
      无数据不伪造/窗口过滤/留痕；RTO+RPO 实测门判/违反失败/空库；
      cron 到期判定/Scheduler 驱动演练（FakeClock 推进触发、ops 流
      留痕）。全量 1315 passed + 5 skipped；ruff 全绿；import-linter
      5 契约 KEPT；流/事件目录守卫零漂移

## Dev Notes

- 位置：`packages/vastacore-sdk/src/vastacore/ops/slo.py`（复用
  ops._distinct_runs 元数据直查与 scheduling.CronSpec）。
- 时区口径三处统一 UTC（drill_due 的 next_after 恒返 aware——
  naive 入参归一，否则比较 TypeError）。
- 演练执行器自开自关存储句柄（生产语义——演练连接独立于常驻连接）。
- 诚实边界：交付的是可复跑的测量与编排机制；生产多区域演练、
  月度可用性统计的运营执行属地化（数字由真实运营数据产生）。

## Dev Agent Record

### Debug Log

- Scheduler.tick 是协程（测试先漏 await）；执行器返回契约是摘要
  对象（.runs/.success_rate）非裸 dict——按 batch 契约包 _DrillSummary。
- Sequencer 的 clock 在构造器非 emit（种子夹具接线修正）。

### Completion Notes

- NFR-004/006/014 的工程可验面交付（终检 §三 表三条 partial 的
  工程侧闭环）；属地运营部分维持登记（不伪称完成）。

### Change Log
