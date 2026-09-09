"""评测框架、VastaLab 任务集与六组消融（Epic 7，FR-063/064，蓝图 §15）。

- EvaluationConfig：任务/模型/提示/预算/策略/种子/代码版本全固化（FR-063）；
- VastaLab 任务：隐藏规则/布局变化/噪声/偏差注入的网格任务（FR-064 素材）；
- 六组消融 Runner：Baseline/Evidence/Cognition/Contract/Model/Full（AC-07）；
- 平台开销单列（NFR-005 MVP 档）。

评审修复（Epic 4-7 code-review）：
- 任务级 RNG 播种改 crc32（``hash()`` 跨进程不稳定，破坏 FR-063 复现）；
- wind 隐藏规则落地为确定性顺风波（偶数步行 +1），teleport/wind 均有真实转移语义；
- solve() 改为在真实转移函数上 BFS——对全部隐藏规则可证达终局；
- 失败分类（failure_kind）与多种子方差进入报告。
"""

from __future__ import annotations

import random
import zlib
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: 消融六组（蓝图 §15.2）。
ABLATION_GROUPS: tuple[str, ...] = (
    "baseline",
    "evidence",
    "cognition",
    "contract",
    "model",
    "full",
)

#: 六组能力开关（True=启用）——组间仅目标能力差异。
GROUP_FLAGS: dict[str, dict[str, bool]] = {
    "baseline":  {"evidence": False, "cognition": False, "contract": False, "model": False},
    "evidence":  {"evidence": True,  "cognition": False, "contract": False, "model": False},
    "cognition": {"evidence": True,  "cognition": True,  "contract": False, "model": False},
    "contract":  {"evidence": True,  "cognition": True,  "contract": True,  "model": False},
    "model":     {"evidence": True,  "cognition": True,  "contract": False, "model": True},
    "full":      {"evidence": True,  "cognition": True,  "contract": True,  "model": True},
}

#: 失败分类（AC-07 失败分类要求；simulator 可插拔替换时保持枚举）。
FAILURE_KINDS: tuple[str, ...] = (
    "invalid_action",   # 动作被契约/策略拒绝
    "timeout",          # 预算耗尽未达终局
    "no_progress",      # 循环/原地打转
    "wrong_end_state",  # 预算内停在错误状态
)


def task_rng_seed(seed: int, task_id: str) -> int:
    """任务级确定性播种（评审修复：``hash()`` 跨进程不稳定 → crc32）。"""
    return seed + zlib.crc32(task_id.encode("utf-8")) % 10000


class EvaluationConfig(BaseModel):
    """评测配置快照（FR-063：报告可完整还原，缺一即不通过）。"""

    model_config = ConfigDict(extra="forbid")

    task_ids: list[str] = Field(min_length=1)
    model_name: str = "grid-agent-v1"
    prompt_version: str = "p1"
    budget: dict[str, int] = Field(default_factory=lambda: {"max_actions": 50})
    policy: str = "default"
    seed: int = Field(ge=0)
    code_version: str = Field(min_length=1)
    platform_overhead_ms: float = Field(
        default=0.0, ge=0.0, description="平台编排开销（NFR-005，单独测量）"
    )


class TaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    group: str
    success: bool
    actions: int = Field(ge=0)
    overhead_ms: float = Field(default=0.0, ge=0.0)
    failure_kind: str | None = Field(
        default=None, description="失败分类（成功为 None）"
    )


class GroupReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group: str
    results: list[TaskResult]
    success_rate: float = Field(ge=0.0, le=1.0)
    mean_actions: float = Field(ge=0.0)
    mean_overhead_ms: float = Field(default=0.0, ge=0.0)
    seeds_run: int = Field(default=1, ge=1, description="聚合的种子数")
    success_rate_stddev: float = Field(
        default=0.0, ge=0.0, description="多种子成功率标准差（单种子为 0）"
    )

    @property
    def failure_breakdown(self) -> dict[str, int]:
        """失败分类统计（评审修复：原为单一 failed 桶）。"""
        counts: dict[str, int] = {}
        for r in self.results:
            if not r.success:
                kind = r.failure_kind if r.failure_kind in FAILURE_KINDS else "unclassified"
                counts[kind] = counts.get(kind, 0) + 1
        return counts or {"all_passed": len(self.results)}


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: EvaluationConfig
    groups: list[GroupReport]

    @property
    def full_vs_baseline_net_gain(self) -> float:
        """Full 相对 Baseline 的成功率净收益（Stage 1 出门条件之一）。"""
        by_group = {g.group: g for g in self.groups}
        full = by_group.get("full")
        baseline = by_group.get("baseline")
        if not full or not baseline:
            return 0.0
        return full.success_rate - baseline.success_rate

    def to_summary(self) -> dict[str, Any]:
        """评测摘要（AC-07：成功率/动作/开销/失败分类）。"""
        return {
            "config": self.config.model_dump(),
            "groups": [
                {
                    "group": g.group,
                    "success_rate": round(g.success_rate, 4),
                    "mean_actions": round(g.mean_actions, 2),
                    "mean_overhead_ms": round(g.mean_overhead_ms, 3),
                    "failures": g.failure_breakdown,
                    "seeds_run": g.seeds_run,
                    "success_rate_stddev": round(g.success_rate_stddev, 4),
                }
                for g in self.groups
            ],
            "full_vs_baseline_net_gain": round(self.full_vs_baseline_net_gain, 4),
        }


# ---- VastaLab 任务集（Story 7.2）----

_MOVES = ("down", "up", "right", "left")


@dataclass
class VastaLabTask:
    """网格任务：隐藏规则 + 布局 + 可选噪声/偏差注入。

    隐藏机制（Agent 不可见，须从交互中发现；转移语义全部确定性，可回放）：
    - ``teleport``——踩 (1,1) 即传送到 (2,2)；
    - ``wind``——偶数步（1 基）顺风波：该步行坐标额外 +1（受边界钳制）。
    """

    task_id: str
    grid_size: int = 4
    start: tuple[int, int] = (0, 0)
    goal: tuple[int, int] = (3, 3)
    hidden_rule: str = "none"
    noise: float = 0.0
    deviation_injection: bool = False
    seed: int = 0

    def _step(self, pos: tuple[int, int], move: str, step_index: int) -> tuple[int, int]:
        """单步确定性转移（step_index 为 1 基步序，wind 依赖其奇偶）。"""
        r, c = pos
        if move == "down":
            r = min(r + 1, self.grid_size - 1)
        elif move == "up":
            r = max(r - 1, 0)
        elif move == "right":
            c = min(c + 1, self.grid_size - 1)
        elif move == "left":
            c = max(c - 1, 0)
        if self.hidden_rule == "teleport" and (r, c) == (1, 1):
            r, c = 2, 2
        if self.hidden_rule == "wind" and step_index % 2 == 0:
            r = min(r + 1, self.grid_size - 1)
        return r, c

    def _pos_after(self, moves: list[str]) -> tuple[int, int]:
        r, c = self.start
        for i, m in enumerate(moves, start=1):
            r, c = self._step((r, c), m, i)
        return r, c

    def solve(self) -> list[str]:
        """确定性求解器：在真实转移函数（含隐藏规则）上 BFS 求最短路径。

        评审修复：原实现对 teleport 硬编码 4x4 路径且从不经过传送门、
        wind 无转移语义——现在对全部规则可证 ``run_agent(solve())`` 为真。"""
        limit = self.grid_size * self.grid_size * 2 + 4
        queue: deque[tuple[tuple[int, int], int, list[str]]] = deque(
            [(self.start, 1, [])]
        )
        seen: set[tuple[tuple[int, int], int]] = set()
        while queue:
            pos, parity, path = queue.popleft()
            if pos == self.goal:
                return path
            if len(path) >= limit or (pos, parity) in seen:
                continue
            seen.add((pos, parity))
            for m in _MOVES:
                nxt = self._step(pos, m, parity)
                queue.append((nxt, parity + 1, path + [m]))
        # 不可达（防御）：退化为无规则直线路径
        rows = self.goal[0] - self.start[0]
        cols = self.goal[1] - self.start[1]
        return ["down"] * max(rows, 0) + ["right"] * max(cols, 0)

    def run_agent(self, moves: list[str]) -> bool:
        """模拟 Agent 执行——是否到达 goal（确定性，可回放验证）。"""
        return self._pos_after(moves) == self.goal


def generate_tasks(
    n_main: int = 20,
    *,
    seed: int = 42,
) -> list[VastaLabTask]:
    """生成 ≥20 主任务 + 变体（合计 ≥40，AC-01 任务基础）。"""
    rng = random.Random(seed)
    tasks: list[VastaLabTask] = []
    rules = ["none", "none", "teleport", "wind"]  # 1/4 隐藏规则密度
    for i in range(n_main):
        size = rng.choice([4, 5])
        goal = (size - 1, size - 1)
        tasks.append(
            VastaLabTask(
                task_id=f"vl-{i:02d}",
                grid_size=size,
                goal=goal,
                hidden_rule=rng.choice(rules),
                seed=rng.randint(0, 10**6),
            )
        )
    # 变体：噪声版 + 偏差注入版（各 n_main/2 以上 → 总数 ≥ 2×n_main）
    for i in range(n_main):
        tasks.append(
            VastaLabTask(
                task_id=f"vl-{i:02d}-noise",
                grid_size=tasks[i].grid_size,
                goal=tasks[i].goal,
                hidden_rule=tasks[i].hidden_rule,
                noise=0.1,
                seed=rng.randint(0, 10**6),
            )
        )
    for i in range(0, n_main, 2):  # 偏差注入变体
        tasks.append(
            VastaLabTask(
                task_id=f"vl-{i:02d}-dev",
                grid_size=tasks[i].grid_size,
                goal=tasks[i].goal,
                hidden_rule=tasks[i].hidden_rule,
                deviation_injection=True,
                seed=rng.randint(0, 10**6),
            )
        )
    return tasks


# ---- 消融 Runner（Story 7.3）----

@dataclass
class AgentSimulator:
    """组差异模拟器——按组开关决定"能力"对成功率的影响。

    这是评测框架的可插拔执行器位：MVP 用确定性模拟；接入真实模型
    适配器（Stage 2）后替换本类，评测框架与消融逻辑不变。"""

    def run_task(
        self, task: VastaLabTask, group: str, *, seed: int = 0
    ) -> TaskResult:
        flags = GROUP_FLAGS[group]
        # 评审修复：crc32 播种——跨进程/跨解释器稳定（FR-063 复现前提）
        rng = random.Random(task_rng_seed(seed, task.task_id))
        base_success = 0.4  # Baseline：无证据/认知/契约/模型的裸成功率
        actions = rng.randint(8, 20)
        overhead = rng.uniform(0.5, 5.0)  # 平台开销（ms，NFR-005）

        if flags["evidence"]:
            base_success += 0.15  # 可回看证据 → 少走弯路
        if flags["cognition"]:
            base_success += 0.10  # 规则记忆跨任务复用
            actions = max(4, actions - 3)
        if flags["contract"]:
            base_success += 0.08  # 偏差拦截 → 不执行错误动作
            overhead += 1.5  # 契约链开销
        if flags["model"]:
            base_success += 0.12  # 验证过的模型 → 规划收益
            actions = max(3, actions - 2)
            overhead += 2.0  # 模型构建/查询开销

        if task.noise > 0:
            base_success -= 0.05
        if task.deviation_injection:
            base_success -= 0.03
            overhead += 0.8

        success = rng.random() < min(base_success, 0.98)
        failure_kind: str | None = None
        if not success:
            # 失败分类（AC-07）：确定性归因，报告侧按桶统计
            failure_kind = FAILURE_KINDS[rng.randrange(len(FAILURE_KINDS))]
        return TaskResult(
            task_id=task.task_id,
            group=group,
            success=success,
            actions=actions,
            overhead_ms=round(overhead, 3),
            failure_kind=failure_kind,
        )


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5


def run_ablation(
    tasks: list[VastaLabTask],
    config: EvaluationConfig,
    *,
    groups: tuple[str, ...] = ABLATION_GROUPS,
    simulator: AgentSimulator | None = None,
    n_seeds: int = 1,
    task_ids: list[str] | None = None,
) -> EvaluationReport:
    """六组消融（AC-07）：自动产出成功率/动作/开销/失败分类。

    评审修复：``n_seeds > 1`` 时以 ``config.seed, config.seed+1, ...``
    逐种子运行并聚合——组报告携带 ``seeds_run`` 与成功率标准差，
    单点净增益不再被当作稳定结论。
    切片（FR-064）：``task_ids`` 限定任务子集（None=全量）——
    配合 :func:`run_ablation_slices` 做维度切分。"""
    if n_seeds < 1:
        raise ValueError("n_seeds 必须 ≥ 1")
    if task_ids is not None:
        wanted = set(task_ids)
        tasks = [t for t in tasks if t.task_id in wanted]
        missing = wanted - {t.task_id for t in tasks}
        if missing:
            raise ValueError(f"task_ids 含未知任务: {sorted(missing)}")
    sim = simulator or AgentSimulator()
    seeds = [config.seed + i for i in range(n_seeds)]
    reports: list[GroupReport] = []
    for group in groups:
        results: list[TaskResult] = []
        per_seed_rates: list[float] = []
        for s in seeds:
            seed_results = [sim.run_task(t, group, seed=s) for t in tasks]
            n = len(seed_results) or 1
            per_seed_rates.append(sum(1 for r in seed_results if r.success) / n)
            results.extend(seed_results)
        n_all = len(results) or 1
        reports.append(
            GroupReport(
                group=group,
                results=results,
                success_rate=sum(1 for r in results if r.success) / n_all,
                mean_actions=sum(r.actions for r in results) / n_all,
                mean_overhead_ms=sum(r.overhead_ms for r in results) / n_all,
                seeds_run=len(seeds),
                success_rate_stddev=_stddev(per_seed_rates),
            )
        )
    return EvaluationReport(config=config, groups=reports)


def run_ablation_slices(
    tasks: list[VastaLabTask],
    config: EvaluationConfig,
    *,
    slice_fn: Callable[[VastaLabTask], str],
    **kwargs: Any,
) -> dict[str, EvaluationReport]:
    """维度切片消融（FR-064「切片」）：按 ``slice_fn(task)`` 标签分组，
    每片独立跑六组——净增益可按任务族（隐藏规则/变体/难度）拆读，
    而不是只剩全池单一数字。"""
    slices: dict[str, list[VastaLabTask]] = {}
    for task in tasks:
        slices.setdefault(slice_fn(task), []).append(task)
    return {
        label: run_ablation(slice_tasks, config, **kwargs)
        for label, slice_tasks in sorted(slices.items())
    }


def make_config(
    *, task_ids: list[str], seed: int, code_version: str = "0.1.0"
) -> EvaluationConfig:
    return EvaluationConfig(
        task_ids=task_ids, seed=seed, code_version=code_version
    )


def verify_config_complete(config: EvaluationConfig) -> bool:
    """FR-063 后果：全部配置字段就位（缺一即不通过）。

    评审修复：补 budget 检查（原实现预算缺失也判 True）。"""
    return bool(
        config.task_ids
        and config.model_name
        and config.prompt_version
        and config.budget
        and all(isinstance(v, int) and v > 0 for v in config.budget.values())
        and config.seed >= 0
        and config.code_version
    )


__all__ = [
    "ABLATION_GROUPS",
    "AgentSimulator",
    "EvaluationConfig",
    "EvaluationReport",
    "FAILURE_KINDS",
    "GROUP_FLAGS",
    "GroupReport",
    "TaskResult",
    "VastaLabTask",
    "generate_tasks",
    "make_config",
    "run_ablation",
    "run_ablation_slices",
    "task_rng_seed",
    "verify_config_complete",
]
