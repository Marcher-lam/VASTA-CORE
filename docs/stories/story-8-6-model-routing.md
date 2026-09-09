---
story_key: 8-6-model-routing
baseline_commit: b6805d4
---

# Story 8.6: 模型路由、熔断与成本（G3）

**Status:** review

## Story

As a 平台使用者,
I want 按能力+成本+健康的路由（超时/重试/熔断/降级）,
So that 换模型不动代码且故障不放大，成本看得见。

## Acceptance Criteria

**Given** 多个适配器与可配置路由策略
**When** 发起模型调用
**Then** 路由决策落事件留痕；失败按阈值熔断计数；成本计入预算归集（NFR-015）
**And** 降级链可配置且降级发生留痕（FR-006；伙伴信号可调整）

## Tasks/Subtasks

- [x] T1: `ModelRouter`——命名适配器注册（含 cost_per_1k）+ 能力过滤
      （capability_views 可注入接 8.5 探测报告；默认自声明）+ cheapest-capable /
      显式降级链（chain）两策略 + prefer 直选；无可行适配器 fail-closed
      （`no capable adapter`，不猜测、零调用）
- [x] T2: 熔断器——连续失败达阈值 open（incident.opened 事件经 emitter 留痕，
      当次调用内确定性完成）；open 跳过（trace 记 skipped）；冷却后半开试探
      （成闭合败重开）；冷却钟默认真实 monotonic（安全机制，AD-15）可注入
- [x] T3: 超时与重试——单次 wait_for(timeout_ms)；同适配器重试 N 次（默认 0）
      后沿候选链 failover（降级即留痕 degraded=True）；全链失败抛聚合 RouterError
- [x] T4: 留痕与成本——每次调用产 routing-trace Artifact 入 CAS（候选/过滤/
      选择/尝试/熔断状态/降级/成本，AD-5 不发明 model.* 事件族）；
      `cost_summary()` 按模型归集（usage 优先，字符估算兜底，basis 显式标注）
- [x] T5: 测试 `tests/test_model_router.py` 12 条（cheapest 胜出/能力过滤
      fail-closed/chain 策略/超时降级留痕/重试后 failover/熔断开跳半开/
      trace 落盘哈希校验/成本 usage·字符双口径/prefer）；全量 445 passed +1
      skipped；ruff 全绿；import-linter 2 契约 KEPT

## Dev Notes

- 位置：`packages/vastacore-sdk/src/vastacore/router.py`（组装根）。
- 事件族约束（AD-5/13 族）：模型调用与路由元数据是 Artifact；熔断开闭是运维
  事件 → incident.opened（kind=circuit_breaker）。
- 成本估算：usage tokens 优先（response.detail.usage），否则字符数/1000 ×
  cost_per_1k（声明值）——basis 字段显式标注口径。
- 伙伴信号可调整：策略首版 cheapest-capable + chain，学习型路由属后续 Stage。

## Dev Agent Record

### Debug Log

- 熔断测试首版预期「失败调用抛 RouterError」——与降级语义冲突：dead 失败后
  由 alive 兜底成功是**设计行为**（failover 即降级）。修正测试为断言「兜底成功
  + dead.calls 不增 + trace 记 circuit_open skipped」。
- incident 事件首版 fire-and-forget（create_task）——断言先于任务执行竞态；
  改为 await 确定性留痕（当次调用返回前完成）。

### Completion Notes

- ModelRouter 组合四要素：能力过滤（接 8.5 `effective_capabilities()` 注入）×
  成本排序/显式链 × 熔断健康 × 超时重试；prefer 支持临时直选。
- 全部 AC 满足：路由 trace 每次 CAS 落盘（哈希校验）；熔断阈值/跳过/半开恢复
  实测（0.05s 冷却注入钟真实时序）；降级 failover 留痕（degraded=True + 尝试
  错误明细）；成本双口径归集（usage/chars-estimated，basis 显式）。
- fail-closed 两处：无可行适配器零调用报错；熔断 open 期跳过不试探。

### File List

- packages/vastacore-sdk/src/vastacore/router.py（新增：ModelRouter/_Breaker/
  CostEntry/RouterError）
- packages/vastacore-sdk/src/vastacore/__init__.py（导出）
- tests/test_model_router.py（新增：12 条）
- docs/sprint-status.yaml（8-6 状态）

## Change Log

- 2026-09-09: Story 8.6 实现完成（T1–T5 全过，445 passed +1 skipped，ruff/lint 绿）→ review
