"""vastacore-sdk 一行装配入口：quickstart（Story 1.7，Epic 1 验收演示）。

组装根（AD-1）：唯一允许引用具体适配器的位置。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from vasta_adapters import GridWorldAdapter
from vasta_protocols.errors import DuplicateEventError, VastaError
from vasta_protocols.ids import new_run_id
from vasta_protocols.protocols import Action
from vasta_runtime import Budget, RunContext, RunEngine
from vasta_runtime.budget import BudgetExceededError
from vasta_runtime.supervisor import SupervisorEscalationError
from vasta_storage import SqliteStorage

from ._version import __version__

#: 到达 goal(3,3) 的预置路径：右/下交替 ×3（等价于右×3 + 下×3）。
_PATH = ["right", "down"] * 3


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
    - 预算安全停止与 Supervisor 升级均接为正常结局；
    - 同一 store 根目录复用同一 run_id 重跑会因 (run_id, seq) 唯一约束
      失败（确定性重放请用两个不同根目录，见 docs/quickstart.md）。
    """
    store_root = Path(root) / "store"
    store = SqliteStorage(store_root)
    try:
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
        try:
            for move in _PATH:
                if engine.episode_ended or engine.state.value != "started":
                    break
                await engine.step(Action(tool=move))
                steps += 1
        except (BudgetExceededError, SupervisorEscalationError):
            pass  # 预算安全停止 / 循环升级暂停均为正常结局
        goal_reached = engine.episode_ended
        if engine.state.value == "started":
            await engine.complete()

        events = await store.aiter_run_events(effective_run_id)
        artifacts = await store.list_artifacts(context.tenant_id, context.project_id)
        return RunSummary(
            run_id=effective_run_id,
            final_state=engine.state.value,
            steps=steps,
            events=len(events),
            artifacts=len(artifacts),
            goal_reached=goal_reached,
            store_root=str(store_root),
            vastacore_version=__version__,
        )
    except DuplicateEventError as exc:
        raise VastaError(
            code="quickstart.rerun_conflict",
            message=(
                f"run {exc.run_id} already exists in {store_root}; "
                "rerun the deterministic demo with a different root or run_id"
            ),
        ) from exc
    finally:
        store.close()
