"""真实适配器驱动评测（Story 12.10，W-1 补齐，G5）。

W-1 解除条件的三要素补齐（11.11 只交付了簿记级接线——task_results
由调用方自备、≥2 种子、CI 独立事件）：

- **run_adapter_tasks**：适配器 × 任务集执行路径——**adapter 真实
  驱动**（逐任务 generate → 注入 judge 判分；seed 入 prompt 元数据
  使各种子为独立采样——评测结果不再由调用方自备）；
- **run_real_seed_eval**：W-1 接线层强制 **≥10 种子**（<10 拒——
  ``real_adapter.needs_ten_seeds``）；逐种子跑任务集 → 成功率集 →
  ``seed_confidence_interval``（9.11 契约）→ 留痕；
- **real_eval_report**：CI **并入评测报告结构**（
  ``OfflineEvalReport.seed_ci`` 字段——非独立事件；事件仅作 trace）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import ModelRequest

#: 任务判分器：(任务描述, 模型回复) → 是否正确。
TaskJudge = Callable[[str, str], Awaitable[bool]]

#: W-1 解除门槛：真实适配器多种子评测至少 10 个种子（豁免复评口径）。
W1_MIN_SEEDS = 10


async def run_adapter_tasks(
    adapter: Any, *, tasks: list[str], judge: TaskJudge, seed: int,
) -> float:
    """单种子执行路径：adapter 逐任务生成 → judge 判分 → 成功率。

    seed 注入 prompt 元数据（独立采样面——各种子结果互不共享）。"""
    if not tasks:
        raise VastaError(
            code="real_eval.empty_tasks",
            message="任务集不可为空（VastaLab 任务集由调用方注入）",
        )
    correct = 0
    for task in tasks:
        response = await adapter.generate(ModelRequest(
            prompt=f"[seed={seed}] {task}"))
        if await judge(task, response.content):
            correct += 1
    return correct / len(tasks)


async def run_real_seed_eval(
    store: Any, adapter: Any, *, tasks: list[str], judge: TaskJudge,
    seeds: list[int], ci_level: float = 0.95,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> dict[str, Any]:
    """W-1 执行路径：≥10 种子强制 → 逐种子成功率 → CI → 留痕。

    返回 CI（seed_confidence_interval 契约：n/mean/half_width/low/
    high/level）。"""
    from vasta_protocols.sequencer import EventSequencer

    from ..governance.revalidation import seed_confidence_interval

    if len(seeds) < W1_MIN_SEEDS:
        raise VastaError(
            code="real_adapter.needs_ten_seeds",
            message=(f"W-1 真实评测需 ≥{W1_MIN_SEEDS} 种子"
                     f"（得到 {len(seeds)}——模拟器方差不具代表性）"),
        )
    if len(set(seeds)) != len(seeds):
        raise VastaError(
            code="real_eval.duplicate_seeds",
            message="种子集含重复项（独立采样要求去重）",
        )
    if ci_level not in (0.90, 0.95, 0.99):
        # 前置校验（评审修复 4-3）：不跑完 10 个种子才在 CI 层拒
        raise VastaError(
            code="revalidation.bad_ci_level",
            message=f"level 支持 0.90/0.95/0.99（得到 {ci_level}）",
        )
    rates = [await run_adapter_tasks(adapter, tasks=tasks, judge=judge,
                                     seed=seed) for seed in seeds]
    ci = seed_confidence_interval(rates, level=ci_level)
    sequencer = EventSequencer(
        store, "evaluation", tenant_id=tenant_id, project_id=project_id)
    await sequencer.emit("evaluation.real_seed_ci", {
        "adapter": getattr(getattr(adapter, "config", None), "name",
                           "adapter"),
        "seeds": list(seeds), "ci": ci,
    })
    return ci


async def real_eval_report(
    store: Any, adapter: Any, *, base_report: Any,
    tasks: list[str], judge: TaskJudge, seeds: list[int],
    ci_level: float = 0.95,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> Any:
    """端到端：适配器 × 任务集 ≥10 种子 → CI 并入评测报告结构。

    返回 ``OfflineEvalReport``（``seed_ci`` 字段携带 CI——报告结构
    一等公民，事件仅 trace）。"""
    from ..models.offline_eval import attach_seed_ci

    ci = await run_real_seed_eval(
        store, adapter, tasks=tasks, judge=judge, seeds=seeds,
        ci_level=ci_level, tenant_id=tenant_id, project_id=project_id)
    return attach_seed_ci(base_report, ci)


__all__ = ["TaskJudge", "W1_MIN_SEEDS", "real_eval_report",
           "run_adapter_tasks", "run_real_seed_eval"]
