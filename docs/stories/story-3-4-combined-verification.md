---
story_key: 3-4-combined-verification
baseline_commit: 5acbcd952ce3d4fa7bfe392b8527647360b5a7ce
---

# Story 3.4: 执行后组合核验

**Status:** review

## Story

As a Agent 开发者,
I want 动作执行后自动采集观察并按契约 verify_with 运行组合核验器（schema/读回/不变量/视觉 Diff 首版）,
So that "执行了"与"生效且没弄坏别的"被分别证明。

## Acceptance Criteria

**Given** 已执行的写动作与采集到的动作后观察
**When** 组合核验运行
**Then** 全部核验器通过才判 pass；结果为 pass/deviation/inconclusive/system_error 四态之一（FR-035/036）
**And** 观察不足（如读回超时）判 inconclusive 而非成功；不变量核验可由用户以结构化规则定义（UJ-2 的本地版）

## Tasks/Subtasks

- [x] 1. 核验器实现集（vasta-contracts.verifiers）：SchemaVerifier（ToolResult 形状/ok 一致）、ReadBackVerifier（适配器 read_back 与预期变化比对——首版：read_back 可用且 kind 合法即核成功变化子集匹配）、InvariantVerifier（结构化不变量规则求值）
- [x] 2. 不变量规则 DSL（最小结构化）：字段路径 = 值 / ≠ 值 / contains / unchanged 四操作；用户以字典定义（UJ-2 本地版）；不认识的操作 → inconclusive
- [x] 3. VerificationPipeline（vasta-contracts）：按 verify_with 顺序组合执行，聚合规则复用 3.1 语义（未注册名优先 inconclusive、deviation 支配、system_error 支配、否则全 pass 才 pass）；单个核验器异常 → 该器 system_error 不中断整链
- [x] 4. 引擎接线：execute_contracted 的核验段用 VerificationPipeline 替代 3.1 的内联注册表循环；after 观察与 ToolResult 证据传入核验器 evidence
- [x] 5. 观察不足判 inconclusive：核验器收到 evidence 缺 after_observation/result → inconclusive（不冒充 pass）
- [x] 6. 测试：四态各路径、不变量四操作（含违反 → deviation）、未注册名、单器异常不中断、观察不足 inconclusive、聚合支配序、引擎端到端六段链 verification 段事件正确
- [x] 7. 对照 AC 验证并更新记录

## Dev Notes

- 核验器只读 evidence dict（contract_ref/tool/result/after_observation/expected_changes）——独立确定性来源原则（INV-06）在 MVP 的形态：不依赖执行模型自评。
- 视觉 Diff 核验器留接口占位（kind 注册表可扩展）；首版交付 schema/read_back/invariant 三器。
- 不变量 DSL 的字段路径用点分访问 evidence（dict 键 + 对象属性双通道）；类型不匹配 → inconclusive（不抛）。

## Dev Agent Record

### Implementation Plan

1. `verifiers.py`：_BaseVerifier（异常→system_error 包装）+ SchemaVerifier（result 形状/ok）+ ReadBackVerifier（after 观察可用 + 预期变化子串匹配）+ InvariantRule/InvariantVerifier（四操作 DSL，路径缺失/未知操作/无规则 → inconclusive）+ VerificationPipeline（默认注册三器、可覆盖/可注册、外部核验器异常 → 该器 system_error）。
2. `contracted.py` 核验段：内联循环 → VerificationPipeline；evidence 携带 after_observation/expected_changes/网关路径回读的 ToolResult（从最近 action.executed 事件的 result_ref 取回 CAS——核验器读独立证据，INV-06）。
3. 测试 18 个（三器单元 × 各态 + 流水线聚合支配序 + 引擎端到端）。

### Debug Log

- `_dig` 初版只走 dict 键，遇 pydantic 模型属性（result.ok）即断 → 补 getattr 双通道。
- 流水线初版对外部核验器异常不做包装（Broken 核验器直接炸整链）→ run() 内 try/except 转 system_error。
- 3.1 两个聚合测试语义随默认流水线变化而更新（空注册表→inconclusive 变为：默认 read_back 对空观察细节判 deviation——更强的不冒充 pass 语义）；端到端不变量测试改对 env 路径真实存在的字段立规则。

### Completion Notes

AC 逐条验证：
1. **四态（FR-035/036）** — Schema（ok=False→deviation / result 缺→inconclusive / ok→pass）；ReadBack（变化可见→pass / 变化缺失→deviation / after 缺→inconclusive）；Invariant（违反→deviation / 路径缺或未知操作→inconclusive / 满足→pass）；流水线聚合支配序（unregistered→inconclusive、system_error>deviation>全 pass 才 pass）。✅
2. **观察不足 inconclusive（不冒充成功）** — result 缺/after 缺/路径缺失/无规则四路径均 inconclusive；引擎端到端：env 路径 after 观察细节为空 → read_back 判 deviation（预期变化未体现）——绝不 pass。✅
3. **结构化不变量（UJ-2 本地版）** — InvariantRule（field/op/value/note）四操作全覆盖测试（eq/ne/contains/unchanged + 违反 + 缺路径 + 未知操作）；引擎端到端注入自定义规则核验通过。✅
4. **单器异常不中断整链** — Broken 核验器 + schema deviation 同时在场 → 聚合 errored（system_error 支配），链未中断且两器结果都在 detail。✅
5. **INV-06（独立证据）** — 网关路径的 ToolResult 从 CAS 回读入 evidence（核验器不读执行模型自评）；env 路径 after 观察直采。✅

回归：全套 252 passed（前序 234 + 本故事 18）；ruff 全绿；import-linter 契约 KEPT。3.1 两个聚合测试语义更新已记录（更强不冒充语义）。

## File List

- packages/vasta-contracts/src/vasta_contracts/verifiers.py（新建）
- packages/vasta-contracts/src/vasta_contracts/__init__.py（修改：导出核验器族）
- packages/vasta-runtime/src/vasta_runtime/contracted.py（修改：核验段接 VerificationPipeline + evidence 组装）
- tests/test_combined_verification.py（新建，18 测试）
- tests/test_action_contracts.py（修改：两个聚合测试随默认流水线语义更新）
- docs/stories/story-3-4-combined-verification.md（本文件）

## Change Log

- 2026-09-08：Story 3.4 实现完成——三核验器（schema/read_back/不变量 DSL 四操作）+ VerificationPipeline（默认注册/异常隔离/聚合支配序）+ 引擎 evidence 组装（网关 ToolResult 从 CAS 回读，INV-06）；观察不足一律 inconclusive/deviation 不冒充 pass；252 测试全绿；全部 AC 验证通过，状态置 review。
