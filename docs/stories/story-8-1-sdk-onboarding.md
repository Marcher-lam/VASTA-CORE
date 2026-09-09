---
story_key: 8-1-sdk-onboarding
baseline_commit: 4ee98bf
---

# Story 8.1: SDK 接入与自测计时（G1）

**Status:** review

## Story

As a Agent 开发者,
I want 一个 pip 安装的 SDK 把我的 Agent 循环挂进 RunEngine（生命周期/预算/证据落盘/六段链对我透明）,
So that 不改架构就获得可信执行与完整回放。

## Acceptance Criteria

**Given** 空仓库与一个示例 Agent（README 快速上手为准）
**When** 按文档从零接入并**计时记录**
**Then** ≤3 工程日完成接入（SM-5 实验证据，计时记录入档）
**And** 写动作自动走六段链（开发者无需手工编排核验）；同 seed 字节级复现（FR-002，SM-5）

## Tasks/Subtasks

- [x] T1: `AgentSession` 高层 API（create/start/reset/observe/step/act/complete/close，
      async-with 支持；内部组装 RunEngine+SqliteStorage+ToolGateway+PolicyEngine）
- [x] T2: 契约模板机制——`act()` 对网关注册工具自动从模板构造 ActionContract
      （tool/args/goal 按调用填充；无模板的注册工具 fail-closed 拒执行；
      未注册工具走 env.step 观察路径；risk 缺省取清单分级——AD-4）
- [x] T3: `examples/onboarding/from_zero.py`——「外部团队视角」从零接入示例
      （订单看板 env + 发货工具 + 契约模板 + 运行回放，端到端实跑通过）
- [x] T4: `docs/onboarding-log.md` 接入计时演练记录（自动化实测 2.2s 机时 +
      人工步骤分解 ≈1–3 小时，SM-5 证据）+ README 接入节（三步示例）
- [x] T5: 测试 `tests/test_agent_sdk.py` 7 条（六段链自动走/无模板 fail-closed/
      观察路径/字节级复现/幂等关闭/摘要/模板缺段构造期拒）；全量 394 passed +1 skipped；
      ruff 全绿；import-linter 2 契约 KEPT

## Dev Notes

- AD-1：AgentSession 属 vastacore-sdk（组装根），可引用适配器/网关；核心包不感知。
- 写动作六段链唯一通道 `execute_contracted`（AD-4）——SDK 不旁路。
- fail-closed（AD-12）：注册工具无契约模板 → `sdk.contract_template_missing`，
  不降级为裸执行。
- 同 seed 字节级复现沿用 quickstart 的对照口径（归一化 run_id/时间戳后逐字节比对）。
- Assumption Audit P3 修正：≤3 工程日以「自测计时演练」落地为实验证据。

## Dev Agent Record

### Debug Log

- 首版测试工具签名写成 `execute(self, action, *, credentials=None)`——网关按协议
  以 `idempotency_key=` 关键字调用 → TypeError 被网关捕获为 adapter_error →
  ReadBack 核验偏差 → 恢复链补偿。修正签名后六段链通过。**已作为摩擦点③记入
  onboarding-log**（隐性签名契约，8.4 协议测试将拦截）。
- 计时演练中 `uv sync`（不带参数）把工作区成员可编辑安装剪除——根项目无
  dependencies 声明，默认 sync 只同步根项目。`uv sync --all-packages` 恢复。
  **真实接入摩擦点①，README 已标注正确命令**；建议后续 Story 在根声明依赖或
  提供自包含安装。

### Completion Notes

- `AgentSession`（packages/vastacore-sdk/src/vastacore/agent.py）：三参数接入面
  （env/tools/contracts）→ RunEngine+网关+策略全自动组装；`act()` 写动作六段链
  透明化（模板构造契约 → execute_contracted）；`normalized_stream()` 字节级复现
  对照；async-with + 幂等 close。
- 契约模板：`contract_from_template`（缺必填段构造期拒；risk 缺省取网关清单
  分级——AD-4 清单强制，模板自声明时以模板为准）。
- 计时演练（SM-5）：机时 2.2 s（sync 57ms / 示例 574ms / 回归 1.6s）；
  端到端人工估计 1–3 小时——≤3 工程日余量充足。三个真实摩擦点入
  docs/onboarding-log.md，其中 ①（uv sync 剪除工作区包）为本演练最有价值发现。
- 全部 AC 满足：README 快速上手 ✓、计时入档 ✓、六段链透明（测试断言审计
  complete）✓、同 seed 字节级复现（双根目录归一化流一致）✓。

### File List

- packages/vastacore-sdk/src/vastacore/agent.py（新增：AgentSession/SessionSummary）
- packages/vastacore-sdk/src/vastacore/__init__.py（导出 AgentSession）
- tests/test_agent_sdk.py（新增：7 条）
- examples/onboarding/from_zero.py（新增：从零接入示例）
- docs/onboarding-log.md（新增：SM-5 计时演练记录）
- README.md（接入三步节 + 快速开始命令修正）
- docs/sprint-status.yaml（Epic 8 story 条目）

## Change Log

- 2026-09-09: Story 8.1 实现完成（T1–T5 全过，394 passed +1 skipped，ruff/lint 绿）→ review
