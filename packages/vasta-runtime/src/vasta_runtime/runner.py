"""RunEngine：Run 生命周期 + 预算 + 因果事件链（FR-004，Story 1.2）。

- 经 `await RunEngine.create(...)` 构造即发 run.created（seq=0，无父项）；
  此后每个事件 parent=上一事件（因果链）。
- 状态转移必经 state.assert_transition，非法转移拒绝。
- step：预算先检 → 环境执行 → 计数 → 采集观察事件；超限转安全停止
  （failed + run.failed payload.safe_stop）后重抛 BudgetExceededError。
- resume：先 env.observe() 再与暂停检查点比对，环境变化显式记入 run.resumed。
- AD-10：StorageAdapter 为异步端口，事件写入全部 await。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from vasta_protocols.envelope import EventEnvelope
from vasta_protocols.errors import VastaError
from vasta_protocols.ids import new_event_id, new_run_id, now_utc
from vasta_protocols.protocols import (
    Action,
    EnvironmentAdapter,
    Observation,
    StorageAdapter,
)

from .budget import Budget, BudgetExceededError, BudgetTracker
from .checkpoint import Checkpoint, ObservationSignature
from .state import RunState, assert_transition


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    tenant_id: str = "t-default"
    project_id: str = "p-default"


@dataclass
class ResumeReport:
    resumed_event: EventEnvelope
    env_changed: bool
    observed: Observation = field(repr=False)


class RunEngine:
    def __init__(
        self,
        *,
        env: EnvironmentAdapter,
        store: StorageAdapter,
        budget: Budget | None = None,
        config: RunConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.env = env
        self.store = store
        self.config = config or RunConfig(run_id=new_run_id())
        self._clock = clock or now_utc
        self.tracker = BudgetTracker(budget or Budget(), clock=self._clock)
        self._state = RunState.CREATED
        self._seq = -1
        self._last_event_id: str | None = None
        self._last_action: Action | None = None
        self._last_signature: ObservationSignature | None = None
        self._checkpoint: Checkpoint | None = None

    @classmethod
    async def create(
        cls,
        *,
        env: EnvironmentAdapter,
        store: StorageAdapter,
        budget: Budget | None = None,
        config: RunConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> RunEngine:
        engine = cls(env=env, store=store, budget=budget, config=config, clock=clock)
        await engine._emit(
            "run.created", {"budget": engine.tracker.snapshot().model_dump()}
        )
        return engine

    # ---- 状态 ----
    @property
    def state(self) -> RunState:
        return self._state

    @property
    def checkpoint(self) -> Checkpoint | None:
        return self._checkpoint

    async def _emit(self, type_: str, payload: dict[str, object]) -> EventEnvelope:
        self._seq += 1
        envelope = EventEnvelope.model_validate(
            {
                "run_id": self.config.run_id,
                "seq": self._seq,
                "type": type_,
                "parent_event_id": self._last_event_id,
                "ts": self._clock(),
                "tenant_id": self.config.tenant_id,
                "project_id": self.config.project_id,
                "event_id": new_event_id(),
                "payload": payload,
            }
        )
        await self.store.append_event(envelope)
        self._last_event_id = envelope.event_id
        return envelope

    # ---- 生命周期 ----
    async def start(self) -> None:
        await self._transition(RunState.STARTED, "run.started")

    async def pause(self) -> Checkpoint:
        cp = Checkpoint(
            run_id=self.config.run_id,
            state=RunState.PAUSED,
            last_event_seq=self._seq,
            last_action=self._last_action,
            active_plans=[],
            budget=self.tracker.snapshot(),
            last_observation=self._last_signature,
        )
        self._checkpoint = cp
        await self._transition(
            RunState.PAUSED,
            "run.paused",
            {"checkpoint": cp.model_dump(mode="json")},
        )
        return cp

    async def resume(self) -> ResumeReport:
        # 恢复语义（FR-004）：先重新观察真实环境，再与检查点比对。
        observed = await self.env.observe()
        signature = ObservationSignature.from_observation(observed)
        env_changed = (
            self._checkpoint is not None
            and self._checkpoint.last_observation is not None
            and signature != self._checkpoint.last_observation
        )
        self._last_signature = signature
        resumed = await self._transition(
            RunState.STARTED,
            "run.resumed",
            {
                "env_changed": env_changed,
                "observed_kind": observed.kind,
                "observed_actions": list(observed.available_actions),
            },
        )
        return ResumeReport(resumed_event=resumed, env_changed=env_changed, observed=observed)

    async def cancel(self) -> None:
        await self._transition(RunState.CANCELLED, "run.cancelled")

    async def complete(self) -> None:
        await self._transition(RunState.COMPLETED, "run.completed")

    async def fail(self, reason: str) -> None:
        await self._safe_stop(reason=reason, safe_stop=False)

    # ---- 执行 ----
    async def observe(self) -> Observation:
        obs = await self.env.observe()
        await self._record_observation(obs)
        return obs

    async def step(self, action: Action) -> list[Observation]:
        if self._state is not RunState.STARTED:
            raise VastaError(
                code="run.not_started",
                message=f"step requires started run, current={self._state.value}",
            )
        try:
            self.tracker.check()  # 预算先检（无余量即拒，超限动作不执行）
        except BudgetExceededError as exc:
            await self._safe_stop(reason=exc.kind.value, safe_stop=True)
            raise
        observations = await self.env.execute(action)
        self.tracker.record_action()
        self._last_action = action
        for obs in observations:
            await self._record_observation(obs)
        return observations

    async def record_model_call(self) -> None:
        """登记一次模型调用：先检余量，无余量即安全停止并抛出。"""
        try:
            self.tracker.check()
        except BudgetExceededError as exc:
            await self._safe_stop(reason=exc.kind.value, safe_stop=True)
            raise
        self.tracker.record_model_call()

    # ---- 内部 ----
    async def _record_observation(self, obs: Observation) -> None:
        self._last_signature = ObservationSignature.from_observation(obs)
        await self._emit(
            f"observation.{obs.kind}",
            {
                "available_actions": list(obs.available_actions),
                "artifact_refs": list(obs.artifact_refs),
            },
        )

    async def _safe_stop(self, *, reason: str, safe_stop: bool) -> None:
        payload: dict[str, object] = {
            "reason": reason,
            "safe_stop": safe_stop,
            "budget": self.tracker.snapshot().model_dump(),
        }
        await self._transition(RunState.FAILED, "run.failed", payload)

    async def _transition(
        self, target: RunState, event_type: str, payload: dict[str, object] | None = None
    ) -> EventEnvelope:
        assert_transition(self._state, target)
        if target is RunState.STARTED and self._state is RunState.CREATED:
            self.tracker.start()
        env = await self._emit(event_type, payload or {})
        self._state = target
        return env
