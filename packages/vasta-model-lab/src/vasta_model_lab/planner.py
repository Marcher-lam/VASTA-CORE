"""受约束规划器（Story 6.5，FR-047/048）——BFS + 上限终止。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .manifest import PartialWorldModel


@dataclass
class PlanCaps:
    """规划约束（FR-047：超任一即止——五维：深度/节点/时间/成本/
    风险。风险维为终检补齐（此前四维）。）"""

    max_depth: int = 10
    max_nodes: int = 1000
    max_time_s: float = 2.0
    max_cost: float = float("inf")
    max_risk: float = float("inf")


def plan_bfs(
    model: PartialWorldModel,
    initial_observation: dict[str, Any],
    *,
    actions: list[dict[str, Any]],
    caps: PlanCaps | None = None,
    clock: Any = None,
    cost_fn: Callable[[dict[str, Any]], float] | None = None,
    risk_fn: Callable[[dict[str, Any]], float] | None = None,
) -> list[dict[str, Any]]:
    """BFS 首版：模拟内搜索，超限终止。现实执行由调用方逐步核验（FR-048）。

    clock：AD-15 安全墙钟——默认经供给点（注入供测试）；安全上限属
    强制机制，不挂 seeded 注入时钟。
    cost_fn：单步成本（默认 action["cost"] 或 1.0）；累计成本超
    caps.max_cost 的分支剪除（评审修复：max_cost 原先未生效）。
    评审修复：目标判定先于深度截断——恰好落在 max_depth 的目标路径
    应被接受，而不是被 continue 丢弃。"""

    from ._bookkeeping_stub import default_monotonic

    monotonic = clock or default_monotonic
    caps = caps or PlanCaps()
    cost_of = cost_fn or (lambda a: float(a.get("cost", 1.0)))
    risk_of = risk_fn or (lambda a: float(a.get("risk", 0.0)))
    start = monotonic()
    state0 = model.init_state(initial_observation)
    frontier: list[tuple[dict[str, Any], list[dict[str, Any]], float,
                        float]] = [(state0, [], 0.0, 0.0)]
    nodes = 0
    best: list[dict[str, Any]] = []
    while frontier:
        nodes += 1
        if nodes > caps.max_nodes:
            return best  # 上限即止（返回已达最佳）
        if monotonic() - start > caps.max_time_s:
            return best
        state, path, cost, risk = frontier.pop(0)
        if model.outcome(state) == "goal":
            return path  # 找到目标（含 depth == max_depth 的终态）
        if len(path) >= caps.max_depth:
            continue
        best = path if len(path) > len(best) else best
        for action in actions:
            next_cost = cost + cost_of(action)
            if next_cost > caps.max_cost:
                continue  # 成本剪枝
            next_risk = risk + risk_of(action)
            if next_risk > caps.max_risk:
                continue  # 风险剪枝（FR-047 第五维）
            next_state = model.transition(state, action)
            frontier.append((next_state, path + [action], next_cost,
                             next_risk))
    return best


