# 接入计时演练记录（Story 8.1 / SM-5 实验证据）

**日期**: 2026-09-09　**演练者**: 平台方自演（模拟外部团队从零接入）
**对象**: `AgentSession` SDK + `examples/onboarding/from_zero.py`
**SM-5 判据**: 基础接入 ≤3 工程日（本记录把该假设变成可复核的实验）

## 计时结果

| 步骤 | 机时（实测） | 人工估计 | 备注 |
|---|---|---|---|
| 1. 环境就绪 `uv sync --all-packages` | 57 ms（热缓存；冷装首次实测约 3–8 s 量级，依赖本机网络） | 5 分钟 | **摩擦点①见下** |
| 2. 读接入文档 + 复制示例骨架 | — | 15 分钟 | README 接入节 + from_zero.py |
| 3. 替换自己的 env / tool / 契约模板 | — | 0.5–2 小时 | 示例源码 ~5 KB；两接口（EnvironmentAdapter/ToolAdapter）+ 一份模板字典 |
| 4. 跑通 + 时间线回放 | 574 ms | 5 分钟 | 六段链自动执行、首偏差定位 |
| 5. 接入回归 | 1.6 s | 5 分钟 | `uv run pytest tests/test_agent_sdk.py` |
| **合计** | **2.2 s 机时** | **≈1–3 小时** | **远低于 ≤3 工程日门槛** |

机时合计 2.2 s；含人工步骤的端到端估计 1–3 小时。对单一环境 + 单一写工具的团队，SM-5 的 ≤3 工程日有充足余量（余量留给：多工具清单补齐、契约语义打磨、接入方代码审查）。

## 演练发现的真实摩擦点（按严重度）

**① `uv sync` 默认不含工作区成员（演练中实锤，曾致环境损坏）**
根项目 `vastacore-workspace` 无 `dependencies`，`uv sync` 默认只同步根项目——工作区包的可编辑安装被**剪除**，随后任何 `import vastacore` 失败。正确命令是 `uv sync --all-packages`。
- 已处置：README 与本记录统一写 `--all-packages`；
- 建议（后续 Story）：根 pyproject 显式声明成员依赖或提供 `vasta` console script 的自包含安装包，消除该坑（SM-5 真实伙伴接入前必须消除——**这是本演练最有价值的产出**）。

**② 契约模板是接入的主要心智负担**
工具作者最容易卡在「prediction.changes / invariants / success_criteria 怎么写」。示例已给最短可用形态；Story 8.4（脚手架）将生成模板骨架，进一步降为填空。

**③ 工具适配器签名有隐性契约**
`execute(self, action, idempotency_key=None)` 的关键字参数是必配（演练首版写成 `credentials=None` 即触发网关 adapter_error→核验偏差→补偿链）。已在示例与 README 标注；协议测试（8.4）会在注册期拦截。

## 复现

```bash
uv sync --all-packages
uv run python examples/onboarding/from_zero.py     # 跑通+回放
uv run pytest tests/test_agent_sdk.py -q           # 接入回归
```

计时脚本口径：`subprocess` 逐命令 `perf_counter` 包裹（本轮实测数字即可复现命令顺序）。
