"""vastacore-sdk 一行装配入口：quickstart（Story 1.7，Epic 1 验收演示）。

组装根（AD-1）：唯一允许引用具体适配器的位置。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from vasta_adapters import GridWorldAdapter
from vasta_protocols.ids import new_run_id
from vasta_protocols.protocols import Action
from vasta_runtime import Budget, RunContext, RunEngine
from vasta_storage import SqliteStorage

#: 到达 goal(3,3) 的预置路径：右×3 + 下×3。
_PATH = ["right", "down"] * 3

__version__ = "0.1.0"


class RunSummary(BaseModel):
    """quickstart 结果摘要。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    final_state: str
    steps: int = Field(ge=0)
    events: int = Field(ge=1)
    artifacts: int = Field(ge=0)
    goal_reached: bool
    store_root: str
    vastacore_version: str


async def quickstart(
    root: str | Path = ".vasta",
    *,
    seed: int | None = None,
    run_id: str | None = None,
    max_steps: int = 20,
) -> RunSummary:
    """端到端首跑：GridWorld + SQLite 证据库 + L0 全量记录。

    - 每条观察先落 CAS 再入事件（AD-3，capture_observations=True）；
    - 到达终局后 complete；返回可打印的 RunSummary。
    """
    store_root = Path(root) / "store"
    store = SqliteStorage(store_root)
    effective_run_id = run_id or new_run_id()
    context = RunContext.create(run_id=effective_run_id, seed=seed)
    engine = await RunEngine.create(
        env=GridWorldAdapter(),
        store=store,
        budget=Budget(max_actions=max_steps),
        run_context=context,
        capture_observations=True,
    )
    await engine.start()
    await engine.reset(seed=seed)
    steps = 0
    from vasta_runtime.budget import BudgetExceededError

    try:
        for move in _PATH:
            if engine.collector.episode_ended or engine.state.value != "started":
                break
            await engine.step(Action(tool=move))
            steps += 1
    except BudgetExceededError:
        pass  # 预算安全停止是正常结局之一（Story 1.2 路径）
    goal_reached = engine.collector.episode_ended
    if engine.state.value == "started":
        await engine.complete()

    events = list(store.iter_run_events(effective_run_id))
    artifacts = await store.list_artifacts(context.tenant_id, context.project_id)
    summary = RunSummary(
        run_id=effective_run_id,
        final_state=engine.state.value,
        steps=steps,
        events=len(events),
        artifacts=len(artifacts),
        goal_reached=goal_reached,
        store_root=str(store_root),
        vastacore_version=__version__,
    )
    store.close()
    return summary
