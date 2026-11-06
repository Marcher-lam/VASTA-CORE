# vasta-model-lab

**世界模型沙箱与验证**：把「agent 对环境的理解」做成可执行、可回放、可吊销的资产。

## 职责

- **双形态模型**：DSL（声明式转移表）与 Python（受限代码）——清单强制 unknowns 与覆盖率声明
- **受限子进程沙箱**：静态检查（import 白名单）+ CPU/内存限额 + 墙钟超时 + 最小环境；Linux 容器后端（Podman 类：网络恒关 + seccomp 白名单，运行时+镜像双探测，缺一自动回退子进程并留痕）
- **验证流水线**：静态检查 + 历史回放（真实动作序列重建状态比对）+ 性质测试——≥10 任务回放激活（AC-05）
- **Meta-controller**：规则版升降级（长规划/高风险/无模型 → BUILD 建议）
- **失效桥接（AD-13）**：认知 refute 自动 `world_model.suspended`

## 依赖位置（AD-1）

依赖 `vasta-protocols`；被 sdk 消费。

## 测试锚点

`tests/test_model_lab.py`、`tests/test_sandbox_pool.py`
Story 档案：`docs/stories/story-6-*`
