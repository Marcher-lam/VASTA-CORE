---
story_key: 3-1-action-contract
baseline_commit: 3fafecb37e2b508e250f3c170fa89a674ef2467c
---

# Story 3.1: ActionContract 模型与缺段拒执行

**Status:** review

## Story

As a 平台工程师,
I want 每个状态改变型动作执行前生成含前置/预期变化/不变量/成败条件/核验器与超时的契约且缺段即拒,
So that 无预期的写动作根本无法发生。

## Acceptance Criteria

**Given** 一个声明为写动作的工具调用
**When** 生成契约时缺少任一必填段
**Then** 动作不执行并落 `action.policy_denied`（含拒因）事件（FR-030/031）
**And** 完整契约的六段链（before/contract/policy/execution/after/verification）在成功路径 100% 完整（NFR-001，AC-02）；幂等键与补偿字段按 AD-11/FR-038 预留、Stage 3 激活

## Tasks/Subtasks

- [x] 1. ActionContract 模型（vasta-contracts）：蓝图 §12.1 字段——goal/action/risk/前置/预期变化/不变量/成败条件/核验器/超时/幂等键（预留）/补偿（预留）；必填段 = 前置、预期变化、不变量、成功条件、失败条件、核验器、超时（None **或空**均算缺段；超时须 >0）
- [x] 2. 缺段校验 `missing_segments()` + ContractIncompleteError（错误信封）；校验为纯函数可独立复用
- [x] 3. 引擎 `execute_contracted(contract)`（runtime contracted mixin）：缺段 → 契约不执行 + `action.policy_denied`{phase:contract, missing:[...]} + 抛出；被拒动作不触环境、不耗预算
- [x] 4. 完整契约六段链：before（既有观察）→ 契约 JSON 先落 CAS（AD-3）→ `action.contracted`{contract_ref} → `action.policy_cleared`（3.1 默认放行、策略函数可注入；四态引擎属 3.3）→ `action.executed` → after（观察照常采集，带 last_action）→ `verification.{passed|deviated|inconclusive|errored}`（核验器注册表聚合；未注册/未注册名 → inconclusive）
- [x] 5. 六段链审计器 `audit_six_segment(events)`（vasta-contracts，AC-02 可复用断言工具）：识别每条 action.contracted，分类 complete/rejected/incomplete + missing 清单
- [x] 6. 执行异常 → `action.failed` + run failed（与 step 同语义）；预算/循环/终局/重放守卫全部沿用
- [x] 7. 测试：必填段矩阵（7 段逐一缺失各自拒）、完整链 100% 审计通过、拒路径（事件存在/环境未执行/预算未耗/无 executed 事件）、策略注入 deny、核验聚合（pass/inconclusive）、异常路径 action.failed、因果链完整
- [x] 8. 对照 AC 验证并更新记录

## Dev Notes

- 依赖方向（AD-1 图）：runtime → contracts 合法（RT→CT）；contracts 仅依赖 protocols。
- 事件动词在 action/verification 族内新增（action.policy_cleared 等）——族封闭、动词开放，符合 13 族约定；past-tense。
- 3.1 默认策略=放行是为本故事可测；R3+ 默认请求批准与四态引擎在 Story 3.3 落地（拒因事件类型已就位）。
- 幂等键/补偿为预留可选字段（Stage 3 激活，AC 明示）。

## Dev Agent Record

### Implementation Plan

1. `vasta-contracts/contract.py`：ActionContract（蓝图 §12.1 全字段 + 预留位）/Prediction/REQUIRED_SEGMENTS(7)/missing_segments（None 或空即缺；超时非正即缺）/ContractIncompleteError/make_complete_contract 工厂/audit_six_segment（ChainReport: complete|rejected|incomplete + missing；all_success_paths_complete 即 NFR-001 断言）。
2. `vasta-runtime/contracted.py`：ContractedMixin.execute_contracted——六段链逐段落事件（契约 JSON 先落 CAS 再引用，AD-3）；PolicyOutcome/PolicyCheck 可注入（3.1 默认 allow）；核验器注册表聚合（未注册名优先判 inconclusive，不冒充 pass）；预算/循环/终局/重放守卫沿用；执行异常 → action.failed + run.failed。
3. 依赖接线：runtime +vasta-contracts（AD-1 RT→CT）；contracts +pydantic。
4. 测试 25 个：缺段矩阵参数化 ×10、拒路径（未触环境/未耗预算/事件断言）、策略 deny、六段链 100% 审计、契约 CAS 回读全等、因果链、last_action 携带、聚合三态、守卫四项。

### Debug Log

- 测试导入笔误（vastacore.contracts → vasta_contracts）。
- 两处首轮修正：timeout_ms 的 gt=0 约束移出模型（非正数语义归 missing_segments，避免校验在拒因检测前抛 pydantic 错误）；聚合规则改为未注册名优先判 inconclusive（声明的核验没跑完不能算 passed）。
- 执行失败链的审计边界（无 executed/after/verification 段记 incomplete）已在测试注明——Story 3.4 组合核验器落地时细化失败链语义。

### Completion Notes

AC 逐条验证：
1. **缺任一必填段 → 不执行 + action.policy_denied（含拒因）** — 参数化矩阵 10 例（None/空/非正超时各形态）；拒路径断言：环境 execute_count==0、actions_used==0、`action.policy_denied`{phase:contract, missing_segments:[...]}、无 contracted/executed 事件。策略期拒（deny 注入）同样落 policy_denied（phase:policy）且审计记 rejected 合法终态。✅
2. **六段链成功路径 100%（NFR-001/AC-02）** — happy path事件序含 before 观察→action.contracted{contract_ref}→action.policy_cleared→action.executed→after 观察（带 last_action）→verification.passed；`audit_six_segment` 判 complete==total==1、all_success_paths_complete=True；因果父链逐对完整。✅
3. **契约先落盘后引用（AD-3）** — contracted 事件引用的 sha 取回后 `ActionContract.model_validate(json.loads(payload)) == contract` 全等回读；幂等键/补偿字段在事件 payload 显式可见（值 None，Stage 3 激活）。✅
4. **核验聚合** — 全 pass→passed；未注册名/空注册表→inconclusive（不冒充 pass）；deviation 支配→deviated。✅
5. **守卫沿用** — 非 STARTED 拒、预算计数并在超限时安全停止（failed）、执行异常→action.failed+run.failed 不卡 STARTED。✅

回归：全套 207 passed（前序 182 + 本故事 25）；ruff 全绿；import-linter 契约 KEPT（RT→CT 依赖方向合法）。

## File List

- packages/vasta-contracts/src/vasta_contracts/contract.py（新建）
- packages/vasta-contracts/src/vasta_contracts/__init__.py（重写：公共 API）
- packages/vasta-contracts/pyproject.toml（修改：+pydantic）
- packages/vasta-runtime/src/vasta_runtime/contracted.py（新建）
- packages/vasta-runtime/src/vasta_runtime/runner.py（修改：挂载 ContractedMixin）
- packages/vasta-runtime/src/vasta_runtime/__init__.py（修改：导出 PolicyDeniedError/PolicyOutcome）
- packages/vasta-runtime/pyproject.toml（修改：+vasta-contracts）
- tests/test_action_contracts.py（新建，25 测试）
- docs/stories/story-3-1-action-contract.md（本文件）

## Change Log

- 2026-09-08：Story 3.1 实现完成——ActionContract 全字段模型 + 七段缺段即拒 + 六段链全事件化（含 AD-3 契约落 CAS）+ 审计器 + 核验聚合 + 守卫沿用；Epic 1 评审挂起的 action.* 事件族决策随本故事落地（action.contracted/policy_cleared/policy_denied/executed/failed）；207 测试全绿；全部 AC 验证通过，状态置 review。
