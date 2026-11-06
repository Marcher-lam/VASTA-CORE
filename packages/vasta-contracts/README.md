# vasta-contracts

**ActionContract 与组合核验器**：「什么算做对了」的机器可读声明 + 拿环境事实裁决的核验管线。

## 职责

- **契约模型**：六必填段（目标/前置/预期变化/不变量/成败判据/核验器+超时），缺段在构造期即拒（FR-030/031）
- **六段链审计**：`audit_six_segment`——契约→执行→核验的完整链可审计（NFR-001，拒链不进分母）
- **组合核验器**：schema 校验 / 读回比对（read_back）/ 不变量 DSL（eq/ne/contains/unchanged）——四态结论（passed/deviated/inconclusive/errored），观察不足不归成功
- **受约束规划**：PlanCaps 五维（时间/步数/副作用/风险/深度）与计划失效语义

## 依赖位置（AD-1）

依赖 `vasta-protocols`；被 runtime/policy/sdk 消费。

## 测试锚点

`tests/test_action_contracts.py`（16 测）、`tests/test_combined_verification.py`（18 测）
Story 档案：`docs/stories/story-3-1-*`、`story-3-4-*`
