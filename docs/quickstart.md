# VastaCore Quickstart（15 分钟首跑）

> 适用版本：vastacore-sdk **0.1.0**（与 `examples/quickstart.py` 同步）

## 前置

- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/) ≥ 0.12

## 三步跑通

```bash
# 1. 安装工作区（十个 vasta-* 包）
uv sync --all-packages

# 2. 运行端到端示例（GridWorld → SQLite 证据库 → L0 全量记录）
uv run python examples/quickstart.py

# 3. 跑测试套件
uv run pytest -q
```

预期输出（示例）：

```text
VastaCore quickstart (vastacore v0.1.0)
  run_id       : run-quickstart
  final_state  : completed
  steps        : 6
  events       : 17
  artifacts    : 14
  goal_reached : True
  store        : .vasta\store
```

## 这个首跑发生了什么

一次 **L0 Observe-only** 的完整 Run：4×4 网格世界从 (0,0) 走到 (3,3)，每条观察
先按 sha256 内容寻址落盘（AD-3），再以事件形式入库并引用证据哈希；事件链携带
因果父项，预算/Supervisor 全程值守。产物都在 `.vasta/store/`：

- `store.db` —— 事件库（`(run_id, seq)` 唯一）+ Artifact 元数据 + 租户引用映射
- `objects/<sha[:2]>/<sha>` —— 原始证据（字节全局去重）

## 在代码里使用

```python
import asyncio
from vastacore import quickstart

summary = asyncio.run(quickstart(".vasta", seed=42, run_id="run-quickstart"))
print(summary.final_state, summary.events, summary.artifacts)
```

## 下一步

- `docs/epics.md` —— Epic 1–7 的完整故事与验收标准
- `docs/architecture/architecture-VastaCore-2026-09-08/ARCHITECTURE-SPINE.md` —— 15 条架构决策（AD）
- 确定性重放（NFR-002）：在**两个不同根目录**用相同 seed + run_id 各跑一次
  （如 `.vasta-a` / `.vasta-b`），事件流逐字节一致；同一根目录复用同一
  run_id 会因 `(run_id, seq)` 唯一约束被拒绝（事件不可变，AD-2）
