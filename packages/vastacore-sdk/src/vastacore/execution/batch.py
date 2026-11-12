"""评测即 Run：VastaLab 任务集经 RunEngine 批量运行（Story 8.9，G4）。

- `VastaLabEnv`：任务即环境——reset 决策观察（位置）；execute 应用任务真实
  转移（teleport/wind 生效）；到 goal 发终局观察（终局后引擎拒再行动）；
- `SolvePolicyStandIn`：确定性替身模型——预解 solve() 路径逐步行进；每步
  模型交换经 record_model_exchange 落 Artifact + 计预算（AD-5）；
- `run_tasks_as_runs`：每任务一个完整 Run（生命周期 + 逐步观察 + 模型交换
  留痕），评测任务与真实 Run 同构——AC-01「≥40 任务可运行并生成完整回放」
  由替身达成，不等真实适配器（Assumption Audit P1 修正）。
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from vasta_eval import VastaLabTask
from vasta_protocols.protocols import (
    Action,
    EnvironmentAdapter,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    Observation,
)
from vasta_runtime import Budget, RunContext, RunEngine
from vasta_storage import SqliteStorage


class VastaLabEnv(EnvironmentAdapter):
    """VastaLab 任务作为五协议环境（转移语义与任务集完全一致）。"""

    protocol_version = "0.1.0"

    def __init__(self, task: VastaLabTask) -> None:
        self.task = task
        self.pos = task.start
        self._step_index = 0

    async def reset(self, seed=None):
        self.pos = self.task.start
        self._step_index = 0
        return Observation(
            kind="decision",
            detail={"row": self.pos[0], "col": self.pos[1],
                    "goal": list(self.task.goal)},
            available_actions=["up", "down", "left", "right"],
        )

    async def observe(self):
        return Observation(kind="decision",
                           detail={"row": self.pos[0], "col": self.pos[1]})

    async def execute(self, action):
        self._step_index += 1
        self.pos = self.task._step(  # noqa: SLF001 ——任务真实转移（含隐藏规则）
            self.pos, action.tool, self._step_index
        )
        obs = [Observation(kind="transition",
                           detail={"row": self.pos[0], "col": self.pos[1]})]
        if self.pos == self.task.goal:
            obs.append(Observation(kind="terminal",
                                    detail={"row": self.pos[0],
                                            "col": self.pos[1]}))
        else:
            obs.append(Observation(kind="decision",
                                   detail={"row": self.pos[0],
                                           "col": self.pos[1]}))
        return obs

    async def status(self):
        class S:
            running = True
        return S()


class SolvePolicyStandIn:
    """确定性替身模型（FakeModel 契约形态）：按预解路径逐步给动作。"""

    protocol_version = "0.1.0"
    capabilities = ModelCapabilities()

    def __init__(self, plan: list[str]) -> None:
        self.plan = list(plan)
        self.cursor = 0

    async def generate(self, request: ModelRequest) -> ModelResponse:
        if self.cursor >= len(self.plan):
            return ModelResponse(content="stop")
        move = self.plan[self.cursor]
        self.cursor += 1
        return ModelResponse(content=move, detail={"step": self.cursor})


class TaskRunResult(BaseModel):
    """单任务运行结果。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    run_id: str
    success: bool
    steps: int = Field(ge=0)
    events: int = Field(ge=0)


class BatchRunSummary(BaseModel):
    """批量运行汇总。"""

    model_config = ConfigDict(extra="forbid")

    results: list[TaskRunResult]
    runs: int = Field(ge=0)
    success_rate: float = Field(ge=0.0, le=1.0)
    total_events: int = Field(ge=0)


async def run_tasks_as_runs(
    tasks: list[VastaLabTask],
    *,
    root: str | Path,
    seed: int = 42,
    max_actions_per_task: int = 64,
    tenant_id: str = "t-default",
    project_id: str = "p-default",
) -> BatchRunSummary:
    """批量：每任务一个完整 RunEngine Run（评测任务与真实 Run 同构）。

    评审修复：任务间故障隔离（预算耗尽/升级只记该任务失败，不毁整批）；
    run_id 预检（重复 task_id 或已存在 run 全量先拒，all-or-nothing）；
    空解路径（start==goal）判成功；驱动循环真正经 policy.generate()
    ——「换 policy 即可」的模型在环形态（原实现直接迭代 .plan 列表）。"""
    from vasta_protocols.errors import VastaError
    from vasta_runtime.budget import BudgetExceededError
    from vasta_runtime.supervisor import SupervisorEscalationError

    # 预检：批内 task_id 唯一 + store 中无同名 run（零写入阶段全拒）
    seen: set[str] = set()
    for task in tasks:
        if task.task_id in seen:
            raise VastaError(
                code="batch.duplicate_task",
                message=f"批内重复 task_id {task.task_id!r}（run_id 将撞键）",
            )
        seen.add(task.task_id)
    store = SqliteStorage(Path(root) / "store")
    try:
        clashes = [
            t.task_id for t in tasks
            if list(store.iter_run_events(f"vlrun-{t.task_id}"))
        ]
        if clashes:
            raise VastaError(
                code="batch.run_exists",
                message=f"以下 run 已存在于 store（重跑请换 root）：{clashes}",
            )
        results: list[TaskRunResult] = []
        for index, task in enumerate(tasks):
            run_id = f"vlrun-{task.task_id}"
            env = VastaLabEnv(task)
            policy = SolvePolicyStandIn(task.solve())
            context = RunContext.create(run_id=run_id, seed=seed + index)
            engine = await RunEngine.create(
                env=env, store=store,
                budget=Budget(max_actions=max_actions_per_task),
                run_context=context, capture_observations=True,
            )
            steps = 0
            failure: str | None = None
            try:
                await engine.start()
                await engine.reset(seed=seed + index)
                # 模型在环：每步经 policy.generate() 取动作（换真实适配器
                # 只需替换 policy，驱动循环零改动）
                while not engine.episode_ended and steps < len(policy.plan):
                    request = ModelRequest(
                        prompt=f"vastalab:{task.task_id} step {steps}",
                        context={"pos": list(env.pos),
                                 "goal": list(task.goal)},
                    )
                    move = (await policy.generate(request)).content
                    if move == "stop":
                        break
                    # 模型交换先落盘（AD-5）再行动
                    await engine.record_model_exchange(
                        request,
                        ModelResponse(content=move, detail={"step": steps}),
                    )
                    await engine.step(Action(tool=move))
                    steps += 1
                if engine.state.value == "started":
                    await engine.complete()
            except (BudgetExceededError, SupervisorEscalationError) as exc:
                # 预算/升级安全停止：该任务失败，整批继续（评审修复）
                failure = f"{type(exc).__name__}"
                if engine.state.value == "started":
                    with contextlib.suppress(Exception):  # 尽力收口终态
                        await engine.complete()
            # 空解（start==goal）即成功；终局观察到达亦成功
            success = engine.episode_ended or (not policy.plan and failure is None)
            events = list(store.iter_run_events(run_id))
            results.append(TaskRunResult(
                task_id=task.task_id, run_id=run_id,
                success=success, steps=steps, events=len(events),
            ))
    finally:
        store.close()
    n = len(results) or 1
    return BatchRunSummary(
        results=results,
        runs=len(results),
        success_rate=sum(1 for r in results if r.success) / n,
        total_events=sum(r.events for r in results),
    )


__all__ = ["BatchRunSummary", "SolvePolicyStandIn", "TaskRunResult",
           "VastaLabEnv", "run_tasks_as_runs"]
