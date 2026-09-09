---
story_key: 8-4-tool-scaffold
baseline_commit: c0ce54a
---

# Story 8.4: 工具脚手架与协议测试（G2）

**Status:** review

## Story

As a 工具作者,
I want `vasta tool init` 生成清单骨架 + 一键协议测试,
So that 我的工具过五协议契约才上架，不用读文档抄样例。

## Acceptance Criteria

**Given** 脚手架命令与空工具项目
**When** 生成骨架、填实现、本地跑协议测试
**Then** 契约套件（manifest 完整性/幂等/读回/风险分类/dry-run）全绿才可注册网关
**And** 缺风险/幂等声明在构造期拒绝（复用 FR-032 语义）（FR-081，SM-5）

## Tasks/Subtasks

- [x] T1: `generate_tool_project(name, target)`——生成三文件：tool.py（骨架签名
      正确含 idempotency_key——消摩擦点③）、contract_template.py（七必填段
      骨架——消摩擦点②）、test_protocol.py（pytest 直接跑）；拒绝覆盖/非法名
- [x] T2: `run_tool_protocol_checks(tool)` 程序化检查器——五面：manifest 完整性 /
      幂等重放（replayed=True 且结果一致）/ dry-run 形态 / 读回形态（五类
      Observation）/ 网关注册+分类往返（AD-11 同键二次执行 replayed）；返回失败清单
- [x] T3: `vasta tool init NAME [--dir]` CLI 命令（Typer 子命令组）
- [x] T4: 骨架开箱即绿（CLI→生成→动态加载→检查全绿 + 生成项目内
      pytest 实跑 1 passed）；破坏幂等 → 检查器抓到；缺 risk/read_only/idempotent
      构造期 ValidationError（FR-032）
- [x] T5: 测试 `tests/test_tool_scaffold.py` 9 条 + CLI 端到端 1 条；
      全量 426 passed +1 skipped；ruff 全绿；import-linter 2 契约 KEPT

## Dev Notes

- 位置：`packages/vastacore-sdk/src/vastacore/scaffold.py`（组装根）。
- 复用 vasta_protocols 契约语义；不复制套件代码——检查器直接调适配器与网关。
- 生成代码是文本模板（.format 占位）；骨架实现为可运行的 echo 形态 + TODO 标注。
- 动态加载验证用 importlib.util.spec_from_file_location（不入 sys.path 污染）。

## Dev Agent Record

### Debug Log

- **检查器当场抓到三处既有同款 bug（最有价值产出）**：`DryRunResult(would_execute=...)`
  字段名错误（协议是 `allowed`）——生成模板、test_agent_sdk 夹具、onboarding 示例
  三处同错，均因 supports_dry_run=False 从未被调用而潜伏；检查器直调 dry_run
  即暴露。三处全修。
- **再抓一处**：SetStatusTool 适配器级幂等缓存缺失（网关层缓存掩盖了适配器
  协议不满足）——补 `_results` 缓存协议。
- Typer 子命令组：`@app.command("tool")` 函数式写法返回函数不可挂子命令，
  改 `typer.Typer()` 实例（同 control 组模式）。

### Completion Notes

- `vasta tool init my_tool` 三件套：骨架（从绿改起：正确签名+幂等缓存协议+TODO
  标注）、契约模板（七必填段，risk 留空走清单分级 AD-4）、协议测试
  （pytest 直跑，空失败清单=可注册上架）。
- 检查器五面覆盖 AC 全部要点；`test_checker_flags_broken_idempotency`
  证明检查器会红（不假绿）；`test_checker_on_known_good_tool` 交叉验证既有工具。
- 端到端实跑：CLI init → 生成项目内 `pytest test_protocol.py` → 1 passed。
- 接入摩擦点②③（onboarding-log）就此闭环——脚手架落地。

### File List

- packages/vastacore-sdk/src/vastacore/scaffold.py（新增：generate_tool_project/
  run_tool_protocol_checks/ScaffoldResult）
- packages/vastacore-sdk/src/vastacore/__init__.py（导出）
- packages/vastacore-sdk/src/vastacore/cli.py（tool init 子命令组）
- tests/test_tool_scaffold.py（新增：9 条）
- tests/test_cli.py（端到端 +1）
- tests/test_agent_sdk.py（夹具修复：DryRunResult 字段 + 幂等缓存协议）
- examples/onboarding/from_zero.py（DryRunResult 字段修复）
- docs/sprint-status.yaml（8-4 状态）

## Change Log

- 2026-09-09: Story 8.4 实现完成（T1–T5 全过，426 passed +1 skipped，ruff/lint 绿）→ review
