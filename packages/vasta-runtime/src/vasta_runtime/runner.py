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

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from vasta_policy import PolicyEngine
from vasta_protocols.envelope import EventEnvelope
from vasta_protocols.errors import VastaError
from vasta_protocols.ids import new_run_id, now_utc
from vasta_protocols.protocols import (
    Action,
    EnvironmentAdapter,
    Observation,
    StorageAdapter,
)

from .budget import Budget, BudgetExceededError, BudgetTracker
from .checkpoint import Checkpoint, ObservationSignature
from .contracted import ContractedMixin
from .gateway import ToolGateway
from .observation import ObservationCollector, TerminalObservationError
from .runcontext import RunContext
from .state import RunState, assert_transition
from .supervisor import (
    Escalation,
    Supervisor,
    SupervisorEscalationError,
)


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


class RunEngine(ContractedMixin):
    def __init__(
        self,
        *,
        env: EnvironmentAdapter,
        store: StorageAdapter,
        budget: Budget | None = None,
        config: RunConfig | None = None,
        clock: Callable[[], datetime] | None = None,
        run_context: RunContext | None = None,
        supervisor: Supervisor | None = None,
        capture_observations: bool = False,
        safety_clock: Callable[[], datetime] | None = None,
        tool_gateway: ToolGateway | None = None,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self.env = env
        self.store = store
        self.supervisor = supervisor or Supervisor()
        # AD-4：业务工具凭证只存在于网关；引擎不持有任何 ToolAdapter。
        self.tool_gateway = tool_gateway
        self.policy_engine = policy_engine  # 四态策略（3.3；None=默认放行）
        self.capture_observations = capture_observations
        if run_context is not None and (config is not None or clock is not None):
            raise ValueError(
                "ambiguous run identity: pass run_context OR legacy config/clock, not both"
            )
        # Story 1.5：时间/随机/事件 ID/身份统一来自 RunContext（AD-5）；
        # legacy clock/config 参数在此归一为默认 context。
        if run_context is None:
            cfg = config or RunConfig(run_id=new_run_id())
            run_context = RunContext.create(
                run_id=cfg.run_id,
                tenant_id=cfg.tenant_id,
                project_id=cfg.project_id,
                clock=clock,
            )
        self.context = run_context
        self.config = RunConfig(
            run_id=run_context.run_id,
            tenant_id=run_context.tenant_id,
            project_id=run_context.project_id,
        )
        self._clock = run_context.clock
        # AD-15：预算墙钟是安全强制 → 用真实时钟（可注入仅供测试），
        # 不得挂在（seeded/replay 模式下不走的）注入时钟上。
        self.tracker = BudgetTracker(budget or Budget(), clock=safety_clock or now_utc)
        self._state = RunState.CREATED
        self._seq = -1
        self._last_event_id: str | None = None
        self._last_action: Action | None = None
        self._last_signature: ObservationSignature | None = None
        self._checkpoint: Checkpoint | None = None
        self.collector = ObservationCollector()

    @classmethod
    async def create(
        cls,
        *,
        env: EnvironmentAdapter,
        store: StorageAdapter,
        budget: Budget | None = None,
        config: RunConfig | None = None,
        clock: Callable[[], datetime] | None = None,
        run_context: RunContext | None = None,
        supervisor: Supervisor | None = None,
        capture_observations: bool = False,
        safety_clock: Callable[[], datetime] | None = None,
        tool_gateway: ToolGateway | None = None,
        policy_engine: PolicyEngine | None = None,
    ) -> RunEngine:
        engine = cls(
            env=env,
            store=store,
            budget=budget,
            config=config,
            clock=clock,
            run_context=run_context,
            supervisor=supervisor,
            capture_observations=capture_observations,
            safety_clock=safety_clock,
            tool_gateway=tool_gateway,
            policy_engine=policy_engine,
        )
        await engine._emit(
            "run.created", {"budget": engine.tracker.snapshot().model_dump()}
        )
        return engine

    # ---- 状态 ----
    @property
    def state(self) -> RunState:
        return self._state

    @property
    def episode_ended(self) -> bool:
        """公共访问（sdk/下游只读引擎状态，不触内部 collector）。"""
        return self.collector.episode_ended

    @property
    def checkpoint(self) -> Checkpoint | None:
        return self._checkpoint

    async def _emit(self, type_: str, payload: dict[str, object]) -> EventEnvelope:
        # seq 只在写入成功后推进：写失败不留序号空洞（评审修复）。
        envelope = EventEnvelope.model_validate(
            {
                "run_id": self.config.run_id,
                "seq": self._seq + 1,
                "type": type_,
                "parent_event_id": self._last_event_id,
                "ts": self._clock(),
                "tenant_id": self.config.tenant_id,
                "project_id": self.config.project_id,
                "event_id": self.context.new_event_id(),
                "payload": payload,
            }
        )
        await self.store.append_event(envelope)
        self._seq = envelope.seq
        self._last_event_id = envelope.event_id
        return envelope

    # ---- 生命周期 ----
    async def start(self) -> None:
        await self._transition(RunState.STARTED, "run.started")

    async def pause(self) -> Checkpoint:
        assert_transition(self._state, RunState.PAUSED)  # 先验：非法暂停不落 checkpoint
        cp = self._build_checkpoint()
        self._checkpoint = cp
        self.tracker.pause()  # 暂停期间墙钟不计费（评审修复）
        await self._transition(
            RunState.PAUSED,
            "run.paused",
            {"checkpoint": cp.model_dump(mode="json")},
        )
        return cp

    def _build_checkpoint(self) -> Checkpoint:
        return Checkpoint(
            run_id=self.config.run_id,
            state=RunState.PAUSED,
            last_event_seq=self._seq,
            last_action=self._last_action,
            active_plans=[],
            budget=self.tracker.snapshot(),
            last_observation=self._last_signature,
        )

    async def resume(self) -> ResumeReport:
        # 恢复语义（FR-004）：先重新观察真实环境，再与检查点比对；
        # 观察本身也是证据——照常记录（评审修复：不再绕过采集器）。
        if self._state is not RunState.PAUSED:
            raise VastaError(
                code="run.not_paused",
                message=f"resume requires paused run, current={self._state.value}",
            )
        self.context.require_replay_adapter(self.env)  # AD-5：重放守卫
        observed = await self.env.observe()
        await self._record_observation(observed)
        signature = ObservationSignature.from_observation(observed)
        env_changed = (
            self._checkpoint is not None
            and self._checkpoint.last_observation is not None
            and signature != self._checkpoint.last_observation
        )
        self.supervisor.reset_all()  # 人工已审阅恢复：计数清零
        self.tracker.resume()  # 恢复墙钟计费
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
        self._require_started("observe")
        self.context.require_replay_adapter(self.env)  # AD-5：重放守卫
        obs = await self.env.observe()
        await self._record_observation(obs)
        return obs

    async def reset(self, seed: int | None = None) -> Observation:
        """重置环境：先真实重置成功，再记录 reset 标记与首个决策帧
        （评审修复：环境重置失败不留"已重置"的假状态）。"""
        self._require_started("reset")
        self.context.require_replay_adapter(self.env)  # AD-5：重放守卫
        first = await self.env.reset(seed=seed)
        marker = Observation(kind="reset", detail={"seed": seed})
        await self._record_observation(marker)  # collector 同时清除终局态
        self.supervisor.reset_all()  # 新 episode：循环与偏差计数清零
        await self._record_observation(first)
        return first

    async def ingest_external(self, detail: dict[str, object]) -> None:
        """采集外部事件（环境侧推送/外部变化）：observation.external。"""
        self._require_started("ingest_external")
        obs = Observation(kind="external", detail=detail)
        await self._record_observation(obs)

    async def record_model_exchange(
        self, request: BaseModel, response: BaseModel
    ) -> str:
        """模型请求/响应整体 Artifact 化（AD-5）：证据先落盘，再登记预算。"""
        payload = json.dumps(
            {
                "request": request.model_dump(mode="json"),
                "response": response.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        sha = await self.store.save_artifact(
            payload,
            mime="application/json",
            source="model.exchange",
            tenant_id=self.config.tenant_id,
            project_id=self.config.project_id,
        )
        await self.record_model_call()
        return sha

    async def step(self, action: Action) -> list[Observation]:
        self._require_started("step")
        self.context.require_replay_adapter(self.env)  # AD-5：重放守卫
        try:
            self.collector.ensure_actable()  # 性质：终局后不行动（蓝图 §33.1）
        except TerminalObservationError as exc:
            raise VastaError(code="run.terminal", message=str(exc)) from exc
        escalation = self.supervisor.check_loop(self._last_signature, action)
        if escalation is not None:  # 循环先到 → 暂停升级（不执行、不耗预算）
            await self._escalate(escalation)
        try:
            self.tracker.check()  # 预算先检（无余量即拒，超限动作不执行）
        except BudgetExceededError as exc:
            await self._safe_stop(reason=exc.kind.value, safe_stop=True)
            raise
        try:
            observations = await self.env.execute(action)
        except Exception as exc:
            # 环境执行异常：Run 必须落终态事件，不得卡在 STARTED（评审修复）
            await self.fail(f"env_error:{type(exc).__name__}")
            raise
        self.tracker.record_action()
        self._last_action = action
        for obs in observations:
            # 动作维度经参数传递（Story 2.1；评审修复：消共享状态，并发交错不错标）
            await self._record_observation(obs, action=action)
        return observations

    async def note_deviation(self, deviation: bool) -> None:
        """核验结果喂给 Supervisor（Epic 3 接线）：连续 M 次偏差触发升级。"""
        if self._state is not RunState.STARTED:
            raise VastaError(
                code="run.not_started",
                message=f"note_deviation requires started run, current={self._state.value}",
            )
        escalation = self.supervisor.note_deviation(deviation)
        if escalation is not None:
            await self._escalate(escalation)

    async def record_model_call(self) -> None:
        """登记一次模型调用：先检余量，无余量即安全停止并抛出。"""
        self._require_started("record_model_call")
        try:
            self.tracker.check()
        except BudgetExceededError as exc:
            await self._safe_stop(reason=exc.kind.value, safe_stop=True)
            raise
        self.tracker.record_model_call()

    # ---- 内部 ----
    def _require_started(self, op: str) -> None:
        if self._state is not RunState.STARTED:
            raise VastaError(
                code="run.not_started",
                message=f"{op} requires started run, current={self._state.value}",
            )

    async def _escalate(self, escalation: Escalation) -> None:
        """Supervisor 升级：incident.opened → 暂停（含 checkpoint）→ 抛出。

        评审修复：升级暂停同样构建 checkpoint（resume 后的环境变化检测
        依赖它），run.paused payload 统一为 {checkpoint, escalation} 双键。
        """
        await self._emit(
            "incident.opened",
            {"reason": escalation.reason.value, **escalation.detail},
        )
        cp = self._build_checkpoint()
        self._checkpoint = cp
        self.tracker.pause()
        await self._transition(
            RunState.PAUSED,
            "run.paused",
            {
                "checkpoint": cp.model_dump(mode="json"),
                "escalation": {"reason": escalation.reason.value, **escalation.detail},
            },
        )
        raise SupervisorEscalationError(escalation)

    async def _record_observation(
        self, obs: Observation, *, action: Action | None = None
    ) -> None:
        self._last_signature = ObservationSignature.from_observation(obs)
        payload = self.collector.record(obs)
        if action is not None:
            # 动作维度（Story 2.1）：仅 step 产生的观察携带 last_action
            # （参数传递，reset/observe/resume/external 路径天然不携带），
            # 供 payload_equals={"last_action": ...} 检索；非事件族，不与
            # Epic 3 的 action.* 管道冲突。
            payload["last_action"] = action.tool
        if self.capture_observations:
            # AD-3：证据先落盘（哈希校验），事件才引用（artifact_refs）。
            captured = json.dumps(
                {**payload, "detail": obs.detail},
                sort_keys=True,
                separators=(",", ":"),
                default=repr,  # 非 JSON 原生 detail 不至于令采集崩溃
            ).encode("utf-8")
            sha = await self.store.save_artifact(
                captured,
                mime="application/json",
                source="observation.capture",
                tenant_id=self.config.tenant_id,
                project_id=self.config.project_id,
            )
            # 合并（不覆盖）适配器自带的证据引用（评审修复）
            payload["artifact_refs"] = [*payload["artifact_refs"], sha]
        await self._emit(f"observation.{obs.kind}", payload)

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
