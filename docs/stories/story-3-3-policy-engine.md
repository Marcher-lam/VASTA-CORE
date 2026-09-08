---
story_key: 3-3-policy-engine
baseline_commit: f2337e0544ddffd698ef4794fe893bde6d6bc5b4
---

# Story 3.3: 策略引擎四态与 fail-closed

**Status:** review

## Story

As a 安全治理人员,
I want 策略输出允许/拒绝/请求批准/降级四态、R3+ 默认请求批准、策略服务不可用时高风险 fail-closed,
So that 权限收紧不需要逐工具改造、故障也不会放大风险。

## Acceptance Criteria

**Given** R3 风险动作与生效策略
**When** 动作进入策略判定
**Then** 默认进入"请求批准"（MVP 落地为暂停等待人工在本地界面确认，FR-033）并留判定依据事件
**And** 策略引擎不可用时 R2+ 动作一律拒绝（AD-12）；降级路径被记录为事件

## Tasks/Subtasks

- [x] 1. PolicyEngine（vasta-policy.policy）：PolicyDecision 四态模型（allow/deny/request_approval/degrade + basis + degraded 标志）；默认风险映射（蓝图 §12.4）：R0/R1→allow、R2→allow（经策略核）、R3→request_approval、R4→deny；自定义规则列表（首个命中优先）
- [x] 2. 引擎接入（contracted.py）：分类前置（网关 effective risk 先于策略判定，AD-4×FR-033 交叉）；`policy_engine` 构造参数；优先级 = 显式 policy_check 可调用（3.1 兼容）> policy_engine > 默认放行
- [x] 3. 四态处理：allow → policy_cleared；deny → policy_denied + PolicyDeniedError；request_approval → `action.approval_requested` + 暂停（checkpoint+tracker.pause，同升级语义）+ ApprovalRequestedError；`execute_contracted(..., approved=True)` → `action.approved`{via:human-local} 后继续执行；degrade → policy_cleared{decision:degrade, degraded:true} 照常执行（降级路径入事件）
- [x] 4. fail-closed（AD-12）：decide() 抛异常 → R2+ 拒（basis=fail_closed）+ policy_denied 事件；R0/R1 放行但 payload 记 degraded=true（策略不可用的降级路径入事件）
- [x] 5. 网关集成：清单 R3（契约自报 R0）→ request_approval——策略看 effective 风险
- [x] 6. 测试：四态各路径事件断言、R3 暂停后 approve 续行、fail-closed 双分支、3.1 兼容（callable/默认放行）、effective 风险驱动、审计器兼容（rejected 链）
- [x] 7. 对照 AC 验证并更新记录

## Dev Notes

- 无网关时 effective = 契约自报 risk（env 直连路径）。
- approval_requested 暂停不产生 incident（区别于 Supervisor 升级）；恢复走人工 approved=True 重入。
- 3.6 人工控制故事会补齐完整暂停/接管/撤销面板；本故事只交付批准闭环的最小形态。

## Dev Agent Record

### Implementation Plan

1. `vasta-policy/policy.py`：PolicyDecision（四态+basis+degraded）/DEFAULT_RISK_POLICY（蓝图 §12.4 映射）/PolicyEngine（规则优先、默认按风险、未知风险 fail-closed 拒）/fail_closed_fallback（AD-12 纯函数）/ApprovalRequestedError。
2. `contracted.py`：分类前置（effective 风险供策略用）；策略段三分支（callable 兼容 > policy_engine 四态 > 默认放行）；`_apply_policy_decision`——deny 拒、request_approval 挂起（approval_requested + checkpoint + 暂停 + 抛出；approved=True 重入走 action.approved）、allow/degrade 照常（degraded 入事件）；decide 异常 → fail_closed_fallback。
3. `runner.py`：policy_engine 构造参数。
4. 审计器扩展：`action.approved` 计为合法 policy 段；approval_requested 且未决 → 链状态 `pending`（合法挂起，不算 NFR-001 缺段）。
5. 测试 13 个。

### Debug Log

- RunEngine `__init__`/`create` 两处签名漏加 policy_engine 形参（赋值先于签名写入）——测试抓住后补齐。
- 审计器两处语义扩展由测试驱动：approved 属合法 policy 段；批准等待链为 pending 而非 incomplete。首次挂起 + 批准重入会产生两条 contracted（各自可追溯）但 executed 仅一次——测试改为断言 complete≥1 且 executed==1（一次逻辑执行）。
- 测试文件一处幽灵导入（不存在的模块）清除。

### Completion Notes

AC 逐条验证：
1. **R3 默认请求批准（FR-033）** — `test_r3_requests_approval_and_pauses`：approval_requested 事件（含 risk/basis）→ checkpoint → run.paused{approval} → ApprovalRequestedError；环境零执行。批准闭环：resume 后 `approved=True` → `action.approved`{via:human-local} → 执行 → 六段链 complete，且 executed 全程仅一次。✅
2. **fail-closed（AD-12）** — 策略引擎抛异常：R2/R3/R4 全拒（policy_denied{fail_closed:true}）+ 零执行；R0/R1 放行且 policy_cleared{degraded:true, basis:"策略引擎不可用，低风险放行"}——降级路径入事件。未知风险同样 fail-closed 拒。✅
3. **四态全覆盖** — 默认映射（R0/R1/R2 allow、R4 deny + 事件依据）；degrade 规则注入 → policy_cleared{decision:degrade} 照常执行；deny → policy_denied + 抛出。✅
4. **effective 风险驱动（AD-4 交叉）** — 清单 R3 + 契约自报 R0 → approval_requested{risk:"R3"}（策略看清单不看自报）。✅
5. **降级路径入事件** — degrade 决策与策略不可用放行两条降级路径均落 degraded 标志。✅
6. **向后兼容** — 3.1 callable（deny 仍走 policy_denied）；无引擎默认放行（basis=default_allow_3.1 + risk_effective 记录）。✅

回归：全套 234 passed（前序 221 + 本故事 13）；ruff 全绿；import-linter 契约 KEPT。

## File List

- packages/vasta-policy/src/vasta_policy/policy.py（新建）
- packages/vasta-policy/src/vasta_policy/__init__.py（重写：公共 API）
- packages/vasta-policy/pyproject.toml（修改：+vasta-contracts +pydantic）
- packages/vasta-runtime/src/vasta_runtime/contracted.py（修改：分类前置、四态策略段、_apply_policy_decision、approved 参数）
- packages/vasta-runtime/src/vasta_runtime/runner.py（修改：policy_engine 参数）
- packages/vasta-runtime/pyproject.toml（修改：+vasta-policy）
- packages/vasta-contracts/src/vasta_contracts/contract.py（修改：审计器 approved/pending 语义）
- tests/test_policy_engine.py（新建，13 测试）
- docs/stories/story-3-3-policy-engine.md（本文件）

## Change Log

- 2026-09-08：Story 3.3 实现完成——四态策略引擎（默认风险映射+规则注入+批准闭环+degrade 入事件）、AD-12 fail-closed 双分支、effective 风险驱动判定、审计器 pending 语义；234 测试全绿；全部 AC 验证通过，状态置 review。
