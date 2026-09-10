"""长任务跨进程恢复——接管（Story 9.10，FR-007，G4）。

崩溃（非优雅暂停）后新进程从**事件流**重建引擎接管 Run：

- 状态重放：run.created/started/resumed/paused/completed/failed/
  cancelled 推出悬空态；终态拒（不可接管）；
- 快道对齐：Sequencer 从流尾 resuming（续写不留洞——Story 9.1 快道
  「resume 落后自愈」的接管侧入口）；
- 预算重放：以流内最后一份 budget 快照（run.created 或最近
  run.paused 的 checkpoint）为基线 + 其后 action.executed 计数；
  墙钟不可流恢复——接管后重新计费（安全侧：剩余只多不少）；
- seed 恢复：run.created 的 seed（Story 9.10 起入流）重建
  RunContext——事件 ID 流与幂等键派生跨进程可再生（AD-11：
  idempotency_key 是 run_id+step+tool+args 的纯函数，零进程态）；
- 接管留痕：``run.adopted``（run 族）；接管本身不改写历史事件；
- PAUSED 接管：重建 checkpoint（调用方可 engine.resume()——
  重观察比对既有语义）；CREATED 接管（启动即崩）后调用方 start()。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

from .budget import Budget
from .checkpoint import Checkpoint
from .runcontext import RunContext
from .runner import RunEngine
from .state import RunState

_TERMINAL = {
    "run.completed": RunState.COMPLETED,
    "run.failed": RunState.FAILED,
    "run.cancelled": RunState.CANCELLED,
}


@dataclass
class AdoptionReport:
    """接管结果。"""

    engine: RunEngine
    run_id: str
    state: RunState
    adopted_from_seq: int
    executed_actions: list[tuple[str, int]] = field(default_factory=list)
    seed: int | None = None
    seed_recovered: bool = False


def _replay(events: list[Any]) -> tuple[RunState, dict[str, Any] | None,
                                        dict[str, Any] | None, int,
                                        list[tuple[str, int]]]:
    """重放事件流 → (终态, created payload, 最后 checkpoint, 其 seq,
    已执行动作 [(tool, seq)])。"""
    state = RunState.CREATED
    created: dict[str, Any] | None = None
    checkpoint: dict[str, Any] | None = None
    checkpoint_seq = -1
    executed: list[tuple[str, int]] = []
    for event in events:
        t = event.type
        if t == "run.created":
            created = dict(event.payload)
            state = RunState.CREATED
        elif t in ("run.started", "run.resumed"):
            state = RunState.STARTED
        elif t == "run.paused":
            cp = event.payload.get("checkpoint")
            if isinstance(cp, dict):
                checkpoint, checkpoint_seq = cp, event.seq
            state = RunState.PAUSED
        elif t in _TERMINAL:
            state = _TERMINAL[t]
        elif t == "action.executed":
            executed.append((str(event.payload.get("tool", "?")), event.seq))
    return state, created, checkpoint, checkpoint_seq, executed


def _budget_baseline(
    created: dict[str, Any] | None,
    checkpoint: dict[str, Any] | None, checkpoint_seq: int,
    executed: list[tuple[str, int]],
) -> tuple[Budget, int, int]:
    """预算重建：最后快照基线 + 其后 action 计数（model_calls 无流内
    事件可数——取快照值，低估披露）。"""
    source: dict[str, Any] | None = None
    base_seq = -1
    if checkpoint is not None and "budget" in checkpoint:
        source, base_seq = dict(checkpoint["budget"]), checkpoint_seq
    elif created is not None and "budget" in created:
        source, base_seq = dict(created["budget"]), 0
    if source is None:
        return Budget(), len(executed), 0
    budget = Budget(
        max_actions=source.get("max_actions"),
        max_model_calls=source.get("max_model_calls"),
        max_wall_seconds=source.get("max_wall_seconds"),
    )
    actions = int(source.get("actions_used", 0)) + sum(
        1 for _, seq in executed if seq > base_seq)
    model_calls = int(source.get("model_calls_used", 0))
    return budget, actions, model_calls


async def adopt_run(
    store: Any, run_id: str,
    *,
    env: Any,
    supervisor: Any = None,
    capture_observations: bool = False,
    tool_gateway: Any = None,
    policy_engine: Any = None,
    recovery_policy: Any = None,
    safety_clock: Callable[[], Any] | None = None,
    seed: int | None = None,
) -> AdoptionReport:
    """崩溃/暂停后新进程接管 Run（事件流重建 + run.adopted 留痕）。

    seed 优先取 run.created 入流的 seed（跨进程可再生）；流内缺失时
    用调用方传入值（原 run 无 seed 则幂等键回退非确定派生——披露）。"""
    events = list(store.iter_run_events(run_id))
    if not events:
        raise VastaError(
            code="run.not_found",
            message=f"run {run_id!r} 无事件流（不可接管）",
        )
    state, created, checkpoint, cp_seq, executed = _replay(events)
    if state.terminal:
        raise VastaError(
            code="adoption.already_finished",
            message=(f"run {run_id!r} 已终态（{state.value}）——"
                     "不可接管（重放请只读）"),
        )

    # seed：流内优先（run.created 入流——Story 9.10 起），调用方兜底
    stream_seed = created.get("seed") if created else None
    effective_seed = stream_seed if stream_seed is not None else seed
    seed_recovered = stream_seed is not None
    tenant = events[-1].tenant_id
    project = events[-1].project_id
    context = RunContext.create(
        run_id=run_id, tenant_id=tenant, project_id=project,
        seed=effective_seed,
    )

    budget, actions_used, model_calls_used = _budget_baseline(
        created, checkpoint, cp_seq, executed)
    # 直接构造（不经 RunEngine.create——那会发 run.created 撞流）；
    # 同包内部对齐（sequencer/状态/预算/检查点）
    engine = RunEngine(
        env=env, store=store, budget=budget, run_context=context,
        supervisor=supervisor, capture_observations=capture_observations,
        tool_gateway=tool_gateway, policy_engine=policy_engine,
        recovery_policy=recovery_policy, safety_clock=safety_clock,
    )
    last = events[-1]
    engine._sequencer = EventSequencer.resuming(  # noqa: SLF001——同包接管对齐
        store, run_id,
        last_seq=last.seq, last_event_id=last.event_id,
        tenant_id=tenant, project_id=project,
        clock=context.clock, event_id_factory=context.new_event_id,
    )
    engine._state = state  # noqa: SLF001
    engine.tracker.restore(actions_used, model_calls_used)
    if state is RunState.PAUSED and checkpoint is not None:
        engine._checkpoint = Checkpoint.model_validate(checkpoint)  # noqa: SLF001
    engine.tracker.start()  # 墙钟重新计费（崩溃期间不计——安全侧）
    if state is RunState.PAUSED:
        engine.tracker.pause()  # paused 接管：等待 resume 才计费

    await engine._emit("run.adopted", {  # noqa: SLF001——接管留痕
        "adopted_from_seq": last.seq,
        "state": state.value,
        "executed_actions": len(executed),
        "seed_recovered": seed_recovered,
    })
    return AdoptionReport(
        engine=engine, run_id=run_id, state=state,
        adopted_from_seq=last.seq, executed_actions=executed,
        seed=effective_seed, seed_recovered=seed_recovered,
    )


__all__ = ["AdoptionReport", "adopt_run"]
