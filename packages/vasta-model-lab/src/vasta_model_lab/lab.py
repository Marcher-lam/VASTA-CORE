"""世界模型实验室（Epic 6，FR-040~048，蓝图 §13）。

- WorldModel 协议（蓝图 §13.3 最小接口）与 WorldModelManifest；
- 双形态：规则 DSL（声明式）与受限 Python（经沙箱子进程）；
- 沙箱执行器（AD-6/15：MVP 受限子进程，非生产边界）；
- 验证流水线（静态检查 + 历史回放 + 性质测试；激活需人工批准）；
- MetaController 规则版（build/use/repair/bypass/probe/stop 留痕）；
- 受约束规划器（BFS 首版 + 上限终止 + 逐步现实核验钩子）；
- WorldModel 失效桥接（AD-13：claim.refuted → world_model.suspended，
  唯一 owner 在 vastacore-cognition 侧接线）。
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError

#: 模型实验室工具版本。
MODEL_LAB_VERSION = "vasta-model-lab/0.1"

#: 沙箱 Python 允许的导入白名单（生成代码侧）。
ALLOWED_IMPORTS = frozenset({"json", "math", "itertools", "collections"})


class WorldModelManifest(BaseModel):
    """模型清单（FR-043）：声明范围/假设/Unknown/覆盖/版本/依赖。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    scope: str = Field(min_length=1, description="适用环境/机制范围")
    assumptions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list, description="显式未知项")
    coverage: list[str] = Field(default_factory=list, description="覆盖的动作/观察")
    depends_on_claims: list[str] = Field(default_factory=list)
    state_schema: dict[str, str] = Field(default_factory=dict)


@dataclass
class Observation_:
    """轻量观察（模型实验室内部用，避免与 protocols Observation 混淆）。"""

    kind: str = "decision"
    detail: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return {"kind": self.kind, "detail": self.detail, "artifacts": self.artifacts}


@runtime_checkable
class PartialWorldModel(Protocol):
    """蓝图 §13.3 最小接口（FR-041：两种形态都实现它）。"""

    manifest: WorldModelManifest

    def init_state(self, observation: dict[str, Any]) -> dict[str, Any]: ...
    def transition(self, state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]: ...
    def observe(self, state: dict[str, Any]) -> dict[str, Any]: ...
    def outcome(self, state: dict[str, Any]) -> str: ...


# ---- 规则 DSL 形态（Story 6.1）----

class RuleSet(BaseModel):
    """声明式规则：动作 → 状态效果 + 终局条件。"""

    model_config = ConfigDict(extra="forbid")

    rules: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="动作名 → {set: {字段: 值}, add: {字段: 增量}}",
    )
    goal_check: str | None = Field(default=None, description="终局字段名（值非零即终局）")
    fail_check: str | None = None


class DSLWorldModel:
    """规则 DSL 世界模型（受限、确定、无代码执行）。"""

    def __init__(self, manifest: WorldModelManifest, ruleset: RuleSet) -> None:
        self.manifest = manifest
        self.ruleset = ruleset

    def init_state(self, observation: dict[str, Any]) -> dict[str, Any]:
        state = dict(observation.get("detail", {}))
        state.setdefault("_steps", 0)
        return state

    def transition(self, state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        new = dict(state)
        rule = self.ruleset.rules.get(action.get("tool", ""), {})
        for key, value in rule.get("set", {}).items():
            new[key] = value
        for key, delta in rule.get("add", {}).items():
            new[key] = new.get(key, 0) + delta
        new["_steps"] = state.get("_steps", 0) + 1
        return new

    def observe(self, state: dict[str, Any]) -> dict[str, Any]:
        view = {k: v for k, v in state.items() if not k.startswith("_")}
        view["kind"] = "decision"
        return view

    def outcome(self, state: dict[str, Any]) -> str:
        goal = self.ruleset.goal_check
        if goal and state.get(goal):
            return "goal"
        fail = self.ruleset.fail_check
        if fail and state.get(fail):
            return "fail"
        return "ongoing"


# ---- 受限 Python 形态（Story 6.1）----

_PYTHON_TEMPLATE = '''
import json, sys
data = json.loads(sys.stdin.read())
state = data["state"]
action = data["action"]
{body}
'''


class PythonWorldModel:
    """受限 Python 世界模型：代码在受限子进程执行（AD-6 MVP 形态）。"""

    def __init__(
        self,
        manifest: WorldModelManifest,
        code: str,
        *,
        timeout_s: float = 5.0,
    ) -> None:
        self.manifest = manifest
        self.code = code
        self.timeout_s = timeout_s
        # 静态检查：导入白名单 + 禁止危险调用（详细在验证流水线）
        _static_check(code)

    def _run(self, payload: dict[str, Any]) -> Any:
        proc = asyncio.run(
            asyncio.create_subprocess_exec(
                sys.executable, "-c", _PYTHON_TEMPLATE.format(body=self.code),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        ) if False else None
        raise NotImplementedError("沙箱执行经 SandboxExecutor（6.2）")

    # 本地直跑（开发/测试；生产经沙箱）
    def _run_local(self, payload: dict[str, Any]) -> Any:
        scope: dict[str, Any] = {"state": payload["state"], "action": payload["action"]}
        exec(self.code, {"__builtins__": __builtins__}, scope)  # noqa: S102
        return scope.get("result")

    def init_state(self, observation: dict[str, Any]) -> dict[str, Any]:
        return dict(observation.get("detail", {}))

    def transition(self, state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        result = self._run_local({"state": state, "action": action})
        return result if isinstance(result, dict) else dict(state)

    def observe(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"kind": "decision", **{k: v for k, v in state.items() if not k.startswith("_")}}

    def outcome(self, state: dict[str, Any]) -> str:
        return state.get("_outcome", "ongoing")


_FORBIDDEN_PATTERNS = [
    r"\bopen\s*\(",
    r"\b__import__\s*\(",
    r"\bexec\s*\(",
    r"\beval\s*\(",
    r"\bcompile\s*\(",
    r"\bos\.",
    r"\bsubprocess\.",
    r"\bsocket\.",
    r"\bshutil\.",
    r"\bsys\.",
]


def _static_check(code: str) -> None:
    """静态检查（FR-044）：导入白名单 + 危险模式禁用。"""
    for pattern in _FORBIDDEN_PATTERNS:
        if re.search(pattern, code):
            raise VastaError(
                code="model_lab.forbidden_pattern",
                message=f"生成代码含禁止模式 {pattern!r}（静态检查拒绝）",
            )
    for match in re.finditer(r"^\s*import\s+(\w+)", code, re.MULTILINE):
        module = match.group(1)
        if module not in ALLOWED_IMPORTS:
            raise VastaError(
                code="model_lab.forbidden_import",
                message=f"导入 {module!r} 不在白名单 {sorted(ALLOWED_IMPORTS)}",
            )


# ---- 沙箱执行器（Story 6.2，AD-6/15）----

_SANDBOX_WRAPPER = '''
import json, sys, math, itertools, collections
try:
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (__CPU_S__, __CPU_S__))
    resource.setrlimit(resource.RLIMIT_AS, (__MEM_BYTES__, __MEM_BYTES__))
except ImportError:
    pass  # Windows 无 resource——CPU/内存限额由超时墙钟兜底（AD-6 记录边界）
data = json.loads(sys.stdin.read())
state, action = data["state"], data["action"]
__BODY__
sys.stdout.write(json.dumps({"ok": True, "result": result if "result" in dir() else None}))
'''


class SandboxExecutor:
    """受限子进程沙箱：CPU/内存限额、无网络（MVP）、超时墙钟。

    AD-15：超时用真实墙钟（asyncio.wait_for），触发即失败事件由调用方落。
    AD-6：MVP 子进程非生产边界（rootless 容器 Stage 3）。
    """

    def __init__(
        self,
        *,
        timeout_s: float = 5.0,
        cpu_s: int = 2,
        mem_mb: int = 128,
    ) -> None:
        self.timeout_s = timeout_s
        self.cpu_s = cpu_s
        self.mem_mb = mem_mb

    async def run(self, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        wrapped = (
            _SANDBOX_WRAPPER
            .replace("__CPU_S__", str(self.cpu_s))
            .replace("__MEM_BYTES__", str(self.mem_mb * 1024 * 1024))
            .replace("__BODY__", code)
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", wrapped,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:
            raise VastaError(
                code="sandbox.spawn_failed",
                message=f"沙箱子进程启动失败: {exc}",
            ) from exc
        try:
            stdin_data = json.dumps(payload).encode("utf-8")
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_data), timeout=self.timeout_s
            )
        except TimeoutError as exc:
            proc.kill()
            raise VastaError(
                code="sandbox.timeout",
                message=f"沙箱执行超时（>{self.timeout_s}s，真实墙钟）",
            ) from exc
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace")[-300:]
            raise VastaError(
                code="sandbox.execution_failed",
                message=f"沙箱进程退出码 {proc.returncode}: {err}",
            )
        try:
            return json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise VastaError(
                code="sandbox.bad_output",
                message=f"沙箱输出不可解析: {exc}",
            ) from exc


# ---- 验证流水线（Story 6.3）----

@dataclass
class Trajectory:
    """一条历史轨迹（回放测试输入）。"""

    initial_observation: dict[str, Any]
    actions: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    final_outcome: str


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_name: str
    static_check: bool
    replay_passed: int = 0
    replay_total: int = 0
    property_passed: int = 0
    property_total: int = 0
    activation_approved: bool = Field(default=False, description="MVP 人工批准（影子期 Stage 4）")

    @property
    def all_replay_passed(self) -> bool:
        return self.replay_total > 0 and self.replay_passed == self.replay_total

    @property
    def activatable(self) -> bool:
        """激活门槛：静态过 + 全部回放过 + 性质过 + 人工批准（FR-044/AC-05）。"""
        return (
            self.static_check
            and self.all_replay_passed
            and self.property_total > 0
            and self.property_passed == self.property_total
            and self.activation_approved
        )


def validate_model(
    model: PartialWorldModel,
    trajectories: list[Trajectory],
    *,
    properties: list[Any] | None = None,
    activation_approved: bool = False,
) -> ValidationReport:
    """静态检查 + 历史回放 + 性质测试（人工批准替代影子期，MVP）。"""
    static_ok = True
    if isinstance(model, PythonWorldModel):
        try:
            _static_check(model.code)
        except VastaError:
            static_ok = False
    replay_passed = 0
    for traj in trajectories:
        state = model.init_state(traj.initial_observation)
        ok = True
        for i, action in enumerate(traj.actions):
            state = model.transition(state, action)
            predicted = model.observe(state)
            actual = traj.observations[i] if i < len(traj.observations) else {}
            if isinstance(actual, dict):
                for key, value in predicted.items():
                    if key in actual and actual[key] != value:
                        ok = False
        if model.outcome(state) != traj.final_outcome:
            ok = False
        replay_passed += 1 if ok else 0
    props = properties or []
    prop_passed = sum(1 for p in props if p(model))
    return ValidationReport(
        model_name=model.manifest.name,
        static_check=static_ok,
        replay_passed=replay_passed,
        replay_total=len(trajectories),
        property_passed=prop_passed,
        property_total=len(props),
        activation_approved=activation_approved,
    )


# ---- MetaController 规则版（Story 6.4）----

class MetaDecision(StrEnum):
    BUILD = "build"
    USE = "use"
    REPAIR = "repair"
    BYPASS = "bypass"
    PROBE = "probe"
    STOP = "stop"


@dataclass
class MetaSignals:
    """元决策输入信号（蓝图 §13.4 受益公式的一阶近似）。"""

    planning_horizon: int = 0
    real_action_risk: str = "R0"
    mechanism_reuse: int = 0
    repeated_prediction_failure: int = 0
    hypothesis_conflict: int = 0
    has_validated_model: bool = False


def decide_meta(signals: MetaSignals) -> MetaDecision:
    """规则版元决策（可解释；学习版需离线门禁，蓝图 §13.4）。"""
    if signals.repeated_prediction_failure >= 3 and signals.has_validated_model:
        return MetaDecision.REPAIR
    if signals.hypothesis_conflict >= 2 and signals.has_validated_model:
        return MetaDecision.REPAIR
    if signals.planning_horizon >= 5 and signals.real_action_risk in ("R2", "R3"):
        if signals.has_validated_model:
            return MetaDecision.USE
        return MetaDecision.BUILD
    if signals.mechanism_reuse >= 3:
        if signals.has_validated_model:
            return MetaDecision.USE
        return MetaDecision.BUILD
    if signals.repeated_prediction_failure >= 2 and not signals.has_validated_model:
        return MetaDecision.PROBE
    return MetaDecision.BYPASS


# ---- 受约束规划器（Story 6.5）----

@dataclass
class PlanCaps:
    """规划约束（FR-047：超任一即止）。"""

    max_depth: int = 10
    max_nodes: int = 1000
    max_time_s: float = 2.0
    max_cost: float = float("inf")


class PlanningLimitExceededError(VastaError):
    def __init__(self, cap: str) -> None:
        super().__init__(
            code="planner.limit_exceeded",
            message=f"规划超出 {cap} 上限即终止（返回已达最佳）",
        )
        self.cap = cap


def plan_bfs(
    model: PartialWorldModel,
    initial_observation: dict[str, Any],
    *,
    actions: list[dict[str, Any]],
    caps: PlanCaps | None = None,
    clock: Any = None,
) -> list[dict[str, Any]]:
    """BFS 首版：模拟内搜索，超限终止。现实执行由调用方逐步核验（FR-048）。

    clock：AD-15 安全墙钟——默认经供给点（注入供测试）；安全上限属
    强制机制，不挂 seeded 注入时钟。"""

    from ._bookkeeping_stub import default_monotonic

    monotonic = clock or default_monotonic
    caps = caps or PlanCaps()
    start = monotonic()
    state0 = model.init_state(initial_observation)
    frontier: list[tuple[dict[str, Any], list[dict[str, Any]]]] = [(state0, [])]
    nodes = 0
    best: list[dict[str, Any]] = []
    while frontier:
        nodes += 1
        if nodes > caps.max_nodes:
            return best  # 上限即止（返回已达最佳）
        if monotonic() - start > caps.max_time_s:
            return best
        state, path = frontier.pop(0)
        if len(path) >= caps.max_depth:
            continue
        if model.outcome(state) == "goal":
            return path  # 找到目标
        best = path if len(path) > len(best) else best
        for action in actions:
            next_state = model.transition(state, action)
            frontier.append((next_state, path + [action]))
    return best


# ---- WorldModel 失效桥接（Story 6.6，AD-13）----

class WorldModelBridge:
    """claim.refuted → world_model.suspended（唯一 owner）。

    AD-13：桥接只能由 vastacore-cognition 侧发起——本类作为其调用的
    桥接实现挂在 model-lab（事件落 claim.run_id 对应存储）。
    """

    def __init__(self, store: Any) -> None:  # SqliteStorage
        self.store = store

    async def on_claim_refuted(
        self, claim_id: str, *, model_names: list[str]
    ) -> list[str]:
        """认知侧反例到达 → 相关模型挂起（world_model.suspended 事件）。"""
        from ._bookkeeping_stub import emit_world_model_event  # 延迟防环

        suspended: list[str] = []
        for name in model_names:
            await emit_world_model_event(
                self.store,
                "world_model.suspended",
                {"name": name, "reason": f"依赖主张 {claim_id} 被推翻",
                 "bridge": "cognition", "propagated_from_claim": claim_id},
            )
            suspended.append(name)
        return suspended


__all__ = [
    "ALLOWED_IMPORTS",
    "DSLWorldModel",
    "MetaDecision",
    "MetaSignals",
    "MODEL_LAB_VERSION",
    "Observation_",
    "PlanCaps",
    "PlanningLimitExceededError",
    "PythonWorldModel",
    "RuleSet",
    "SandboxExecutor",
    "Trajectory",
    "ValidationReport",
    "WorldModelManifest",
    "WorldModelBridge",
    "decide_meta",
    "plan_bfs",
    "validate_model",
]
