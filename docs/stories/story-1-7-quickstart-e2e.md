---
story_key: 1-7-quickstart-e2e
baseline_commit: 409ff0345fbf6bf4bf846534d75d82df2e1b3163
---

# Story 1.7: 示例环境与端到端首跑

**Status:** review

## Story

As a Agent 开发者,
I want 一个网格世界示例 EnvironmentAdapter 与 `vastacore-sdk` 一行装配入口,
So that 克隆后即可端到端跑通一个 L0 完整记录的 Run。

## Acceptance Criteria

**Given** 安装了 vastacore-sdk 的干净环境
**When** 运行 quickstart 示例
**Then** 一个完整 Run 跑通：证据全部落盘、事件链完整、可被后续 Epic 的检索/回放消费
**And** quickstart 文档与示例代码版本同步；此故事即 Epic 1 的验收演示

## Tasks/Subtasks

- [x] 1. GridWorldAdapter（vasta-adapters）：4×4 确定网格（start(0,0)→goal(3,3)，上下左右移动，达终局）；deterministic=True（AD-5 重放替身标记）；通过 Story 1.1 EnvironmentAdapterContract 契约套件
- [x] 2. 引擎证据采集接线：capture_observations=True 时每条观察载荷先落 CAS（source=observation.capture）再把 sha 写入事件 payload.artifact_refs（AD-3 先落盘后引用；1.4 遗留项收口）
- [x] 3. vastacore-sdk：quickstart(root, *, seed, run_id, max_steps) 一行入口——SqliteStorage + GridWorld + RunEngine(capture=True) + 预置路径策略 → 达终局后 complete；返回 RunSummary（run_id/终态/步数/事件数/证据数/store 路径/版本）
- [x] 4. examples/quickstart.py 可执行示例 + docs/quickstart.md（前置/命令/预期输出/版本号）
- [x] 5. E2E 测试：重开存储验证完整事件链（…observation.terminal→run.completed）与因果父链；全部观察事件 artifact_refs 非空且证据可校验取回；同 run_id+seed 两次 quickstart 事件流逐字节一致（确定性演示）；文档/示例版本同步守卫
- [x] 6. 对照 AC 验证并更新记录

## Dev Notes

- sdk 是 AD-1 组装根：唯一允许 import 适配器之处（import-linter 契约 2 不限制 sdk 方向）。
- 观察采集的载荷 = collector payload（kind/available_actions/detail/actionable）JSON 化；sha 内容寻址天然确定性，不影响重放。
- quickstart 的 run_id 默认随机、可显式传入（确定性测试用）。
- GridWorld 的 observation.detail 携带 agent/goal/step 坐标——检索/回放的消费素材。

## Dev Agent Record

### Implementation Plan

1. `vasta_adapters/gridworld.py`：确定网格世界（4×4、合法动作校验、越界夹紧、达 goal 出终局帧）；`deterministic=True`。
2. `runner.py`：`capture_observations` 参数——_record_observation 先落 CAS（AD-3）再写 artifact_refs 入事件 payload。
3. `vastacore/quickstart.py`：一行装配（SqliteStorage + GridWorld + RunEngine + RunContext(seed)），预置路径 right×3/down×3，终局→complete，预算超限接住为正常结局；RunSummary 摘要；sdk pyproject 依赖补全（runtime/storage/adapters）。
4. examples/quickstart.py + docs/quickstart.md（含版本字面量与同步守卫说明）。
5. 测试：GridWorld 契约套件、E2E 重开校验（链/父链/证据/计数）、SDK 级确定性、预算封顶结局、版本与命令同步守卫。

### Debug Log

- 首轮 3 处失败：契约套件硬编码 "noop" 动作 GridWorld 不接受 → 套件升级为 `valid_action_tool` 可覆写属性（向后兼容，AD-9 minor）；quickstart 未接住预算安全停止（BudgetExceededError 直接外抛）→ 捕获为正常结局（final_state=failed）；示例文件版本为动态 `__version__` 字面量不满足同步守卫 → 文件头注明版本字面量（守卫机制即"改版本必须同步改文档/示例"）。
- docs 预期输出事件数笔误（16→实测 17，数漏 run.completed），实跑后修正；演示产物 .vasta 已清理不入库。
- ruff 3 处自动修复后全绿。

### Completion Notes

AC 逐条验证：
1. **干净环境端到端跑通** — 实跑 `uv run python examples/quickstart.py` 输出：completed / 6 步 / 17 事件 / 14 证据 / goal_reached=True；`uv sync --all-packages` + quickstart + pytest 三步即文档所述路径。✅
2. **证据全部落盘 + 事件链完整 + 可消费** — E2E 测试重开 SqliteStorage：首事件 run.created 无父、末事件 run.completed、observation.terminal 在列、相邻事件因果父链全通过；**每条**观察事件 payload.artifact_refs 非空且 `get_artifact` 取回并 JSON 解析校验（含 kind），摘要计数与事件计数一致（14）——检索/回放（Epic 2/4）可直接消费事件流与 sha 引用。✅
3. **一行装配** — `await quickstart(".vasta", seed=42, run_id=...)` 即完整 L0 Run；RunSummary 携带全部关键数字与版本。✅
4. **文档/示例版本同步** — 守卫测试断 examples 与 docs 均含当前版本字面量与两条命令；升版本不同步即红。✅
5. **确定性（超额验证）** — 同 run_id+seed 两次 quickstart（不同根目录）事件流 model_dump_json 逐字节一致；预算封顶（max_steps=2）结局为 failed 且 goal_reached=False。✅

回归：全套 107 passed（前序 97 + 本故事 10）；ruff 全绿；import-linter 双契约 KEPT（sdk→adapters 组装方向合法）。

**Epic 1 全部 7 个 Story 完成**——验收演示即本故事的实跑输出。

## File List

- packages/vasta-adapters/src/vasta_adapters/gridworld.py（新建）
- packages/vasta-adapters/src/vasta_adapters/__init__.py（重写：导出 GridWorldAdapter）
- packages/vasta-runtime/src/vasta_runtime/runner.py（修改：capture_observations 证据采集接线）
- packages/vastacore-sdk/pyproject.toml（修改：依赖补全）
- packages/vastacore-sdk/src/vastacore/quickstart.py（新建）
- packages/vastacore-sdk/src/vastacore/__init__.py（重写：导出 quickstart/RunSummary）
- packages/vasta-protocols/src/vasta_protocols/contract_suites/environment.py（修改：valid_action_tool 可覆写）
- examples/quickstart.py（新建）
- docs/quickstart.md（新建）
- tests/test_quickstart_e2e.py（新建，10 测试）
- docs/stories/story-1-7-quickstart-e2e.md（本文件）

## Change Log

- 2026-09-08：Story 1.7 实现完成——GridWorld 示例环境（契约套件驱动）、引擎证据采集接线（AD-3 收口）、vastacore-sdk quickstart 一行入口、可执行示例与文档、E2E/确定性/版本守卫测试；实跑验收通过；107 测试全绿；Epic 1 收口，状态置 review。
