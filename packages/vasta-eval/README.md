# vasta-eval

**评测与消融**：让「平台有没有用」变成可复跑的数字。

## 职责

- **评测框架**：配置固化、可复现（同配置同种子同结果），报告整包可入 CAS
- **六组消融（AC-07）**：full / no-contract / no-verify / no-recovery / no-memory / no-budget——平台机制逐个关掉看退化
- **VastaLab 任务集**：内置任务与替身环境（真实模型接入见 sdk 侧 `real_eval`——≥10 种子置信区间）
- **失败分类**：FAILURE_KINDS 口径统一
- **复现包与负载校准**：离线重放与护栏档

## 依赖位置（AD-1）

依赖 `vasta-protocols`；被 sdk 消费。

## 测试锚点

`tests/test_evaluation.py`
Story 档案：`docs/stories/story-7-*`
