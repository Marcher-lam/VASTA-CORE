---
story_key: 8-2-trajectory-import
baseline_commit: fa26ace
---

# Story 8.2: 轨迹导入——一等接入形态（G1）

**Status:** review

## Story

As a 已有生产 Agent 的团队负责人,
I want 把历史执行日志导入证据库（映射事件族 + 工具原始响应入 CAS）,
So that 零侵入获得检索/回放/离线评估。

## Acceptance Criteria

**Given** 常见轨迹格式样例（OpenAI messages 风格与自定义 JSONL）
**When** 执行导入
**Then** 逐条映射为合法信封事件（schema 校验过）且工具响应入 CAS 可哈希取回
**And** 导入产物可被 search/timeline/复现包消费；不合法轨迹明确报错不入库（fail-closed）

## Tasks/Subtasks

- [x] T1: `TrajectoryImporter`——两格式预设（openai messages / generic 显式 type），
      记录→事件族映射（run/observation.external/observation.decision/action.*/memory.note/
      run.completed），逐条父链、合成确定性时间戳
- [x] T2: CAS 入库——消息内容与工具结果先落盘（AD-3），事件 payload 以 artifact_refs/
      result_ref 引用；action 事件带 imported=true 标记（历史记录 ≠ 六段链管辖，
      审计口径诚实）
- [x] T3: fail-closed 全量校验——任一记录非法即整体拒入（零事件写入，错误含记录
      序号与原因）；run_id 已存在事件时 `trajectory.run_exists` 明确报错；
      tool_call 无对应声明即拒（call_id 关联校验）
- [x] T4: 消费面验证——search_events（动作维度命中）/ timeline（covers_all_events）/
      export_repro_bundle（含 CAS 引用清单、可离线重放）对导入产物可用；
      同输入两导入归一化流逐字节一致（确定性）
- [x] T5: 测试 `tests/test_trajectory_import.py` 11 条 + 示例数据
      `examples/onboarding/trajectory-sample.jsonl`（文件路径形态端到端实跑）；
      全量 405 passed +1 skipped；ruff 全绿；import-linter 2 契约 KEPT

## Dev Notes

- 位置：`packages/vastacore-sdk/src/vastacore/trajectory.py`（接入面归 SDK 组装根，AD-1）。
- 事件族只用封闭集 13 族；导入动作不做六段链伪装（imported=true 让审计如实分类）。
- 合成时间戳：固定基准 + 序号递增（确定性，不用墙钟——AD-16 边界，导入器非安全机制）。
- all-or-nothing：先全量校验后写入，无部分导入态。

## Dev Agent Record

### Debug Log

- 测试首版把 `search_events` 首参当 run_id 传——实际签名是
  `(tenant_id, project_id, *, run_id=...)`，改为关键字形式。接口首参为作用域的
  约定（AD-7）在检索面同样生效。

### Completion Notes

- `import_trajectory(store, source, *, run_id, source_format)`：source 收
  记录列表 / JSONL 文本 / **文件路径**三种形态；两格式预设映射到 13 族封闭集
  （openai: user/system→observation.external、assistant→observation.decision、
  tool_calls/tool_call→action.contracted+executed；generic: 显式 type 的
  observation/action/note→memory.note）。
- 契约语义：tool_call 以 call_id 关联前置声明，缺声明即拒；消息内容与工具结果
  先入 CAS（AD-3），事件以 artifact_refs/result_ref 引用，哈希可校验取回。
- 诚实边界：全部导入事件带 imported=true——audit_six_segment 将导入动作如实
  分类为非受辖链（不伪装六段链完整性）。
- 文件形态端到端实跑：4 记录 → 6 事件（含 run.created/completed）+ 3 CAS，
  timeline 全覆盖、depth=5 因果链清晰。
- 全部 AC 满足（两格式映射/CAS 哈希取回/三消费面/fail-closed 零写入/确定性）。

### File List

- packages/vastacore-sdk/src/vastacore/trajectory.py（新增：import_trajectory/ImportSummary）
- packages/vastacore-sdk/src/vastacore/__init__.py（导出）
- tests/test_trajectory_import.py（新增：11 条）
- examples/onboarding/trajectory-sample.jsonl（新增：OpenAI 风格样例）
- docs/sprint-status.yaml（8-2 状态）

## Change Log

- 2026-09-09: Story 8.2 实现完成（T1–T5 全过，405 passed +1 skipped，ruff/lint 绿）→ review
