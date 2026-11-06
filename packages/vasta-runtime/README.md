# vasta-runtime

**运行时核心**：RunEngine / Supervisor / ToolGateway / RunContext——六段链的唯一执行通道（AD-4）。

## 职责

- **Run 生命周期**：启动/暂停/恢复/取消/完成/失败状态机，每次转移落 `run.*` 事件（含因果父链），预算超限安全停止
- **六段链执行**：`execute_contracted`——契约校验 → 策略 → 审批闸 → 网关执行 → 组合核验 → 偏差恢复，全段落事件（NFR-001）
- **有界恢复**：核验偏差 → 计划失效 + 故障分类 + 有限恢复分派，达限安全停止（FR-037）
- **Supervisor**：重复状态/持续偏差检测与升级暂停（FR-053）
- **ToolGateway**：清单强制注册，未声明工具不可被写调用；幂等键回放
- **RunContext（AD-5）**：时钟/随机/环境读取注入——确定性重放的根
- **跨进程恢复**：事件流重建引擎状态（`run.adopted` 留痕）

## 依赖位置（AD-1）

依赖 protocols/storage/cognition/contracts/policy；被 sdk 消费。

## 测试锚点

`tests/test_run_engine.py`、`tests/test_supervisor.py`、`tests/test_deviation_recovery.py`
Story 档案：`docs/stories/story-1-2-*`、`story-1-6-*`、`story-3-5-*`
