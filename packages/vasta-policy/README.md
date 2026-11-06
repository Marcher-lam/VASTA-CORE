# vasta-policy

**策略引擎**：动作放行/降级/审批/拒绝的四态裁决面——依赖不可用一律 fail-closed（AD-12），不静默放行。

## 职责

- **四态决策**：allow / degrade（留痕降级）/ approval / deny——风险分格（R0 只读 → R4 禁止）与环境等级联动（FR-033）
- **fail-closed 回退**：策略引擎不可用时高风险动作拒绝而非放行
- **审批流原语**：`ApprovalRequestedError`（挂起请求不可伪造）与撤销语义（R3 人在环的引擎侧半边）
- **预算与速率**：动作数/模型调用/时长三档预算检查点

## 依赖位置（AD-1）

依赖 `vasta-protocols`；被 runtime（execute_contracted 的策略段）消费。

## 测试锚点

`tests/test_policy_engine.py`（13 测）、`tests/test_human_control.py`（11 测）
Story 档案：`docs/stories/story-3-3-*`、`story-3-6-*`
