---
story_key: 8-14-middleware
baseline_commit: 72103cc
---

# Story 8.14: Middleware 接入形态（G1，FR-002 第四形态）

**Status:** done

## Story

As a 已有自研 Agent 编排器的团队,
I want 一个 middleware 包装层把我的 decide 函数挂进六段链,
So that 编排器零改造（纯 dict 进出）、动作自动契约化核验。

## Acceptance Criteria

**Given** 既有 `async decide(observation: dict) -> action: dict`（零 VastaCore 类型）
**When** 经 VastaMiddleware.wrap / run 执行
**Then** 动作自动走 AgentSession.act 同一六段链（contracted/executed/
verification 落事件）；核验偏差记录于 verdicts 不抛（FR-037 有界恢复引擎内管）
**And** fail-closed 异常原样穿透（无模板拒执行）；缺 tool 键在 middleware
层即拒（不进链不耗预算）（FR-002，蓝图 §18.5-2）

> **启动门槛裁决（2026-11-06）**：原排序「SM-5 伙伴信号后启动」，由用户
> 指令提前实施——与 8.11 ToolProxy 同裁决模式。

## Tasks/Subtasks

- [x] T1: `VastaMiddleware(session)`——`wrap(decide)` 包住用户决策函数
      （观察 dict 喂入经 session.observe 采集）；`execute_action(dict)`
      动作 dict → Action → session.act（六段链唯一通道，AD-4 不旁路）
- [x] T2: `run(decide, steps)` 循环托管——有界步数、episode 终止、
      decide 异常原样穿透；观察路径（未注册工具）记 no_verification
- [x] T3: 偏差语义——每次 act 后从事件流取核验结论入 last_verdict/
      verdicts（不向用户循环抛——FR-037 有界恢复引擎内管）
- [x] T4: 形状与 fail-closed——缺 tool 键 `middleware.action_shape`
      本层即拒；`sdk.contract_template_missing` 等 AD-12 异常穿透
- [x] T5: 测试 `tests/test_middleware.py` 5 条（六段链落事件/偏差
      recorded-not-raised/fail-closed 穿透/形状拒/有界 run）；
      全量 1260 passed + 5 skipped；ruff 全绿；import-linter 5 契约 KEPT

## Dev Notes

- 位置：`packages/vastacore-sdk/src/vastacore/execution/middleware.py`
  （组装根 execution 子包；不 import ops/models/evidence——10.1 层契约）。
- 观察经 `Observation.model_dump(mode="json")` 转 dict——非 pydantic
  实现走 kind/detail/available_actions 兜底（协议允许实现自由）。
- 偏差不抛的设计依据：引擎 `_on_deviation` 返回 None=已分派可继续，
  仅恢复预算耗尽才 RecoveryLimitExceededError——middleware 不在中间
  再造一层重试语义。

## Dev Agent Record

### Debug Log

- 偏差用例构造：契约预期 `status=done`、实参 `status=blocked` →
  read_back 预期变化不匹配 → verification.deviated（无需注入自定义
  核验器——expected_changes 从契约 prediction.changes 派生）。

### Completion Notes

- FR-002 第四形态交付；SM-5 计时实验面（middleware 路径 ≤3 工程日）
  由接入计时演练（docs/onboarding-log.md）承载。

### Change Log
