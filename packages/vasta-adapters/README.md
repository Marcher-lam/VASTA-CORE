# vasta-adapters

**适配器实现库**：具体环境/工具的参考实现——协议端口的「被实现方」。

## 职责

- **GridWorldAdapter**：确定性网格世界（quickstart / 回放演示 / 契约测试的默认环境）
- 参考形态：实现 `vasta-protocols` 的 EnvironmentAdapter 五方法即可接入（自定义环境见 [examples/onboarding](../../examples/onboarding/README.md)）

## 依赖规则（AD-1 的另一半）

本包实现端口但**不被任何包 import**（组装根 vastacore-sdk 除外）——`uv run lint-imports` 强制。这保证核心包永远面向端口编程。

## 测试锚点

`tests/test_quickstart_e2e.py`
Story 档案：`docs/stories/story-1-7-*`
