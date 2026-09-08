---
story_key: 3-2-tool-gateway
baseline_commit: a196f21a5def7b3e982d4e476c47b7a2e3ae7037
---

# Story 3.2: 工具清单与 Tool Gateway

**Status:** review

## Story

As a 平台工程师,
I want 工具以清单声明风险/幂等/读回/补偿/权限与副作用边界，Tool Gateway 强制分类并统一派生幂等键,
So that 旁路执行与重复副作用在结构上不可能。

## Acceptance Criteria

**Given** 未声明风险与幂等语义的工具
**When** 某写动作尝试调用它
**Then** 调用被拒绝（FR-032）
**And** 读写/风险分类由网关依清单强制判定，调用方自声明无效（AD-4）；同幂等键 `(run_id, plan_step_id, tool, canonical_args_hash)` 的重复请求返回原结果 + `replayed=true`，绝不静默重执行（AD-11）；业务工具凭证只存在于网关

## Tasks/Subtasks

- [x] 1. ToolGateway（runtime gateway.py）：注册表（唯一持有适配器/凭证，AD-4）；注册校验清单完整（经 ToolManifest pydantic）与重名拒绝
- [x] 2. 分类强制：classify(tool) → (read_only, risk) 全部取自清单；未注册 → ToolNotRegisteredError；契约自报风险仅作 declared 记录，effective 恒为清单值（AD-4：调用方自声明无效）
- [x] 3. 幂等（AD-11）：canonical_args_hash（键序无关 JSON 规范化 + sha256）；幂等键 = `run_id:plan_step_id:tool:hash`；缓存命中返回原结果 + `replayed=True`，适配器零调用、预算零消耗；重复注册同键幂等
- [x] 4. dry_run 门：清单声明 supports_dry_run 时先试运行，不允许 → ToolResult(ok=False) 不触适配器执行
- [x] 5. 引擎接入：execute_contracted 增 gateway 分支——未注册 → `action.policy_denied`{phase:tool}（不执行不耗预算）；执行经网关，ToolResult JSON 先落 CAS（source=tool.response，FR-010 工具原始响应入库）再 `action.executed`{ok,replayed,risk_effective,risk_declared,result_ref}；after 段合成 observation.external（artifact_refs=[result_sha]，带 last_action）；replay 不计预算
- [x] 6. 无网关时保持 3.1 env 直连路径（向后兼容，GridWorld 类环境）
- [x] 7. 测试：未注册拒（事件+零执行+零预算）、幂等重放（适配器计数=1、replayed 标志、预算只扣一次）、键序无关哈希、分类强制（契约 R0 vs 清单 R3 → effective R3）、dry_run 门、工具响应证据可回读、六段链审计在网关路径仍 complete、凭证隔离结构性断言（引擎不持有任何 ToolAdapter）
- [x] 8. 对照 AC 验证并更新记录

## Dev Notes

- plan_step_id 由调用方传入（默认 "default"）——计划步绑定在 Story 3.5 计划失效落地时启用。
- 幂等缓存在 MVP 为网关内存态；Stage 3 随 FR-038 持久化。
- 契约风险与清单不一致不拒绝但显式记录（risk_declared vs risk_effective）——3.3 策略引擎以 effective 为准。

## Dev Agent Record

### Implementation Plan

1. `gateway.py`：ToolGateway（注册/重名拒/分类强制/is_replay/execute 幂等短路+dry_run 门）+ canonical_args_hash + idempotency_key（AD-11 唯一确定函数）+ 两个错误类型。
2. `runner.py`：tool_gateway 构造参数（引擎不 import 适配器，AD-4）。
3. `contracted.py`：网关分支——注册检查（未注册 → policy_denied{phase:tool}，零执行零预算）→ 预算闸对重放放行（is_replay）→ `_execute_via_gateway`（ToolResult 先落 CAS 再 executed 事件，risk_declared/effective 双记录）→ 统一落入公共 after+核验段（六段链不断）；env 直连路径保持。
4. 测试 14 个（网关单元 + 引擎路径双形态 + 结构性凭证隔离断言）。

### Debug Log

- 补丁链一处断言失败（ruff 早前移除了未使用导入导致锚点漂移）——改用 Edit 工具定点修复。
- 首轮 2 处实现缺陷被测试抓住：
  1. 网关分支提前 `return` 跳过了核验段（六段链断在 verification）→ 重构为双路径统一落入公共 after+核验段；
  2. 重放请求在预算预检即被拒（重放不是新动作）→ `gateway.is_replay` 预判，预算闸对幂等命中放行（结果仍由缓存返回、不计数）。

### Completion Notes

AC 逐条验证：
1. **未声明工具拒（FR-032）** — 空网关下契约调用 → `action.policy_denied`{phase:tool} + `tool.not_registered`；环境零调用、预算零消耗（双计数断言）；清单缺 risk/read_only/idempotent 在 ToolManifest 构造期即抛（pydantic 强制）；重名注册拒。✅
2. **分类强制（AD-4）** — 契约自报 R0、清单 R3 → executed 事件 `risk_declared=R0, risk_effective=R3`、read_only 取清单值；classify 未注册即拒。✅
3. **幂等（AD-11）** — 同键二次请求：适配器 execute_count==1、`replayed=True`、结果原样；不同 args 不同键照常执行；canonical_args_hash 键序无关；**重放不耗预算且预算耗尽后重放仍可返回原结果**（is_replay 预判放行闸门）。✅
4. **凭证只在网关** — 结构性断言：引擎 __dict__ 无任何 ToolAdapter 实例；适配器仅存于网关注册表。✅
5. **工具响应入库（FR-010）+ 六段链** — ToolResult JSON 先落 CAS（source=tool.response），executed 事件引用 result_ref 且可回读解析；网关路径六段链审计 complete（after 段为合成 observation.external，带 result_sha 引用与 last_action）。✅
6. **向后兼容** — 无网关时 3.1 env 直连路径事件形态逐字段不变。✅
7. **dry_run 门** — 清单声明 supports_dry_run 且不允许 → ToolResult(ok=False){phase:dry_run}，适配器零执行。✅

回归：全套 221 passed（前序 207 + 本故事 14）；ruff 全绿；import-linter 契约 KEPT。

## File List

- packages/vasta-runtime/src/vasta_runtime/gateway.py（新建）
- packages/vasta-runtime/src/vasta_runtime/contracted.py（修改：网关分支+重放预算放行+统一核验段）
- packages/vasta-runtime/src/vasta_runtime/runner.py（修改：tool_gateway 参数）
- packages/vasta-runtime/src/vasta_runtime/__init__.py（修改：导出网关族）
- tests/test_tool_gateway.py（新建，14 测试）
- docs/stories/story-3-2-tool-gateway.md（本文件）

## Change Log

- 2026-09-08：Story 3.2 实现完成——ToolGateway 唯一通道（清单强制分类/幂等键唯一派生/dry_run 门/凭证隔离）、引擎网关路径六段链保持完整、工具原始响应入 CAS；测试抓住并修复核验段跳过与重放预算误拒两处实现缺陷；221 测试全绿；全部 AC 验证通过，状态置 review。
