# vasta-cognition

**Claim 图与可修订记忆**：环境规律以带证据、带版本、可撤回的主张管理——反例到达按依赖闭包级联失效（AD-13 认知侧 owner）。

## 职责

- **四类记忆**：Working / Hypothesis / Guide / Counterexample，Claim 全生命周期（proposed → supported → accepted → disputed → refuted → retired；缺证据不得 accepted）
- **互斥冲突**：矛盾主张显式成对，不静默覆盖
- **失效传播**：`claim.refuted` 沿依赖闭包级联，穿透且环安全
- **Context Builder**：按目标/预算/相关性装配上下文
- **世界模型桥接（AD-13）**：认知失效触发 `world_model.suspended`——两条状态流不说两套话

## 依赖位置（AD-1）

依赖 `vasta-protocols`；被 runtime/sdk 消费。

## 测试锚点

`tests/test_cognition.py`（24 测）、`tests/test_revalidation.py`
Story 档案：`docs/stories/story-5-*`
