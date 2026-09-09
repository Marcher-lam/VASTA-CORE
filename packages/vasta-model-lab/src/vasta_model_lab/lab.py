"""世界模型实验室（Epic 6，FR-040~048，蓝图 §13）。

- WorldModel 协议（蓝图 §13.3 最小接口）与 WorldModelManifest；
- 双形态：规则 DSL（声明式）与受限 Python（沙箱子进程 / 受限 builtins 本地）；
- 沙箱执行器（AD-6/15：MVP 受限子进程，非生产边界）；
- 验证流水线（静态检查 + 历史回放 + 性质测试；激活需人工批准）；
- MetaController 规则版（build/use/repair/bypass/probe/stop 留痕）；
- 受约束规划器（BFS 首版 + 上限终止 + 逐步现实核验钩子）；
- WorldModel 失效桥接（AD-13：claim.refuted → world_model.suspended，
  唯一 owner 在 vastacore-cognition 侧接线）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError

#: 模型实验室工具版本。
MODEL_LAB_VERSION = "vasta-model-lab/0.1"

#: 沙箱 Python 允许的导入白名单（生成代码侧）。
ALLOWED_IMPORTS = frozenset({"json", "math", "itertools", "collections"})

#: 事件发射钩子：(event_type, payload) -> Awaitable[None]（AD-15 留痕）。
EventEmitter = Callable[[str, dict[str, Any]], Awaitable[None]]


class WorldModelManifest(BaseModel):
    """模型清单（FR-043）：声明范围/假设/Unknown/覆盖/版本/依赖。

    unknowns / coverage 为必填且至少一项——「无未知」与「无覆盖」本身
    也是声明，空清单表示模型未做任何覆盖刻画，拒绝（评审修复）。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    scope: str = Field(min_length=1, description="适用环境/机制范围")
    assumptions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(min_length=1, description="显式未知项（必填）")
    coverage: list[str] = Field(min_length=1, description="覆盖的动作/观察（必填）")
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


_FORBIDDEN_PATTERNS = [
    r"\bopen\s*\(",
    r"\b__import__\s*\(",
    r"\bexec\s*\(",
    r"\beval\s*\(",
    r"\bcompile\s*\(",
    r"\bgetattr\s*\(",
    r"\bsetattr\s*\(",
    r"\bvars\s*\(",
    r"\bglobals\s*\(",
    r"\blocals\s*\(",
    r"\bbreakpoint\s*\(",
    r"\binput\s*\(",
    r"\bos\.",
    r"\bsubprocess\.",
    r"\bsocket\.",
    r"\bshutil\.",
    r"\bsys\.",
    r"\bpathlib\.",
    r"\bctypes\.",
    r"\bimportlib\.",
]


def _static_check(code: str) -> None:
    """静态检查（FR-044）：导入白名单（含 from-import 形态）+ 危险模式禁用。"""
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
    # from-import 形态同样过白名单（评审修复：原正则漏检）
    for match in re.finditer(r"^\s*from\s+(\w+)", code, re.MULTILINE):
        module = match.group(1)
        if module not in ALLOWED_IMPORTS:
            raise VastaError(
                code="model_lab.forbidden_import",
                message=f"from-import {module!r} 不在白名单 {sorted(ALLOWED_IMPORTS)}",
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


def _sandbox_env() -> dict[str, str]:
    """最小化子进程环境（供给点实现，见 _bookkeeping_stub）。"""
    from ._bookkeeping_stub import sandbox_subprocess_env

    return sandbox_subprocess_env()


class SandboxExecutor:
    """受限子进程沙箱：CPU/内存限额、无网络（MVP）、超时墙钟、最小环境。

    AD-15：超时用真实墙钟（wait_for / subprocess timeout），触发时经
    emitter 落 system.timeout 事件（由调用方注入存储路径）。
    AD-6：MVP 子进程非生产边界（rootless 容器 Stage 3）。"""

    def __init__(
        self,
        *,
        timeout_s: float = 5.0,
        cpu_s: int = 2,
        mem_mb: int = 128,
        emitter: EventEmitter | None = None,
    ) -> None:
        self.timeout_s = timeout_s
        self.cpu_s = cpu_s
        self.mem_mb = mem_mb
        self.emitter = emitter

    def _wrap(self, code: str) -> str:
        _static_check(code)  # 评审修复：子进程路径同样前置静态检查
        return (
            _SANDBOX_WRAPPER
            .replace("__CPU_S__", str(self.cpu_s))
            .replace("__MEM_BYTES__", str(self.mem_mb * 1024 * 1024))
            .replace("__BODY__", code)
        )

    async def _emit_timeout(self, code: str) -> None:
        if self.emitter is not None:
            with contextlib.suppress(Exception):  # 留痕失败不掩盖超时本体
                await self.emitter(
                    "system.timeout",
                    {"source": "sandbox", "timeout_s": self.timeout_s,
                     "code_head": code[:120]},
                )

    async def _emit_incident(self, payload: dict[str, Any]) -> None:
        """越权/异常留痕（AC-06「失败且有审计」；留痕失败不掩盖本体）。"""
        if self.emitter is not None:
            with contextlib.suppress(Exception):
                await self.emitter("incident.opened", payload)

    async def run(self, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            wrapped = self._wrap(code)  # 静态检查在此拒绝越权代码
        except VastaError as exc:
            await self._emit_incident(
                {"source": "sandbox", "reason": exc.code, "code_head": code[:120]}
            )
            raise
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", wrapped,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_sandbox_env(),
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
            await proc.wait()  # 评审修复：回收进程，防僵尸
            await self._emit_timeout(code)
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

    def run_sync(self, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        """同步沙箱路径（供同步 transition 钩子；与 run 同一包装/限额/检查）。"""
        wrapped = self._wrap(code)
        try:
            proc = subprocess.run(  # noqa: S603
                [sys.executable, "-c", wrapped],
                input=json.dumps(payload).encode("utf-8"),
                capture_output=True,
                timeout=self.timeout_s,
                env=_sandbox_env(),
            )
        except subprocess.TimeoutExpired as exc:
            raise VastaError(
                code="sandbox.timeout",
                message=f"沙箱执行超时（>{self.timeout_s}s，真实墙钟）",
            ) from exc
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace")[-300:]
            raise VastaError(
                code="sandbox.execution_failed",
                message=f"沙箱进程退出码 {proc.returncode}: {err}",
            )
        try:
            return json.loads(proc.stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise VastaError(
                code="sandbox.bad_output",
                message=f"沙箱输出不可解析: {exc}",
            ) from exc


# ---- 受限 Python 形态（Story 6.1）----

class PythonWorldModel:
    """受限 Python 世界模型（双执行模式，评审修复后语义与文档一致）：

    - ``sandbox=SandboxExecutor(...)``：每次 transition 经受限子进程
      （AD-6 主路径：静态检查 + 资源限额 + 最小环境 + 超时墙钟）；
    - ``sandbox=None``：受限 builtins 本地直跑（静态检查 + 无 IO/反射
      的内置集；用于快速验证与测试，不是生产边界）。"""

    def __init__(
        self,
        manifest: WorldModelManifest,
        code: str,
        *,
        timeout_s: float = 5.0,
        sandbox: SandboxExecutor | None = None,
    ) -> None:
        self.manifest = manifest
        self.code = code
        self.timeout_s = timeout_s
        self.sandbox = sandbox
        # 静态检查：导入白名单（含 from-import）+ 禁止危险调用
        _static_check(code)

    #: 受限 builtins——数值/容器/基础函数，无 IO/import 反射。
    _SAFE_BUILTINS: dict[str, Any] = {
        "abs": abs, "min": min, "max": max, "sum": sum, "len": len,
        "range": range, "enumerate": enumerate, "zip": zip, "sorted": sorted,
        "reversed": reversed, "any": any, "all": all, "map": map,
        "filter": filter, "round": round, "int": int, "float": float,
        "str": str, "bool": bool, "list": list, "dict": dict, "set": set,
        "tuple": tuple, "isinstance": isinstance, "print": lambda *_: None,
        "True": True, "False": False, "None": None,
    }

    def _run_local(self, payload: dict[str, Any]) -> Any:
        _static_check(self.code)
        scope: dict[str, Any] = {"state": payload["state"], "action": payload["action"]}
        # 显式置空 __builtins__：否则 exec 会向 globals 自动注入全量 builtins
        exec(self.code, {**self._SAFE_BUILTINS, "__builtins__": {}}, scope)  # noqa: S102
        return scope.get("result")

    def _execute(self, payload: dict[str, Any]) -> Any:
        if self.sandbox is not None:
            out = self.sandbox.run_sync(self.code, payload)
            return out.get("result") if isinstance(out, dict) else None
        return self._run_local(payload)

    def init_state(self, observation: dict[str, Any]) -> dict[str, Any]:
        return dict(observation.get("detail", {}))

    def transition(self, state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        result = self._execute({"state": state, "action": action})
        return result if isinstance(result, dict) else dict(state)

    def observe(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"kind": "decision", **{k: v for k, v in state.items() if not k.startswith("_")}}

    def outcome(self, state: dict[str, Any]) -> str:
        return state.get("_outcome", "ongoing")


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
    """静态检查 + 历史回放 + 性质测试（人工批准替代影子期，MVP）。

    回放判定（评审修复）：每条轨迹必须发生至少一次「预测键与实际键
    重叠且相等」的比较——零重叠（预测与观察无交集）视为未验证，不通过。"""
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
        compared = 0
        for i, action in enumerate(traj.actions):
            state = model.transition(state, action)
            predicted = model.observe(state)
            actual = traj.observations[i] if i < len(traj.observations) else {}
            if isinstance(actual, dict):
                for key, value in predicted.items():
                    if key in actual:
                        compared += 1
                        if actual[key] != value:
                            ok = False
        if compared == 0:
            ok = False  # 无任何键可比 → 回放空转（评审修复）
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
    """规则版元决策（可解释；学习版需离线门禁，蓝图 §13.4）。

    评审修复：补 STOP 可达路径——持续预测失败且无可修模型（建/修/探
    都无收益）时停止并上抛，避免无限探针循环。"""
    if signals.repeated_prediction_failure >= 5 and not signals.has_validated_model:
        return MetaDecision.STOP
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


async def emit_meta_decision(
    store: Any,
    decision: MetaDecision,
    signals: MetaSignals,
    *,
    reason: str,
) -> None:
    """元决策留痕（FR-040，评审修复：决策不落事件 → 统一写 world_model.meta_decision）。"""
    from ._bookkeeping_stub import emit_world_model_event  # 延迟防环

    await emit_world_model_event(
        store,
        "world_model.meta_decision",
        {
            "decision": str(decision),
            "reason": reason,
            "signals": {
                "planning_horizon": signals.planning_horizon,
                "real_action_risk": signals.real_action_risk,
                "mechanism_reuse": signals.mechanism_reuse,
                "repeated_prediction_failure": signals.repeated_prediction_failure,
                "hypothesis_conflict": signals.hypothesis_conflict,
                "has_validated_model": signals.has_validated_model,
            },
        },
    )


# ---- 受约束规划器（Story 6.5）----

@dataclass
class PlanCaps:
    """规划约束（FR-047：超任一即止）。"""

    max_depth: int = 10
    max_nodes: int = 1000
    max_time_s: float = 2.0
    max_cost: float = float("inf")


def plan_bfs(
    model: PartialWorldModel,
    initial_observation: dict[str, Any],
    *,
    actions: list[dict[str, Any]],
    caps: PlanCaps | None = None,
    clock: Any = None,
    cost_fn: Callable[[dict[str, Any]], float] | None = None,
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
    start = monotonic()
    state0 = model.init_state(initial_observation)
    frontier: list[tuple[dict[str, Any], list[dict[str, Any]], float]] = [(state0, [], 0.0)]
    nodes = 0
    best: list[dict[str, Any]] = []
    while frontier:
        nodes += 1
        if nodes > caps.max_nodes:
            return best  # 上限即止（返回已达最佳）
        if monotonic() - start > caps.max_time_s:
            return best
        state, path, cost = frontier.pop(0)
        if model.outcome(state) == "goal":
            return path  # 找到目标（含 depth == max_depth 的终态）
        if len(path) >= caps.max_depth:
            continue
        best = path if len(path) > len(best) else best
        for action in actions:
            next_cost = cost + cost_of(action)
            if next_cost > caps.max_cost:
                continue  # 成本剪枝
            next_state = model.transition(state, action)
            frontier.append((next_state, path + [action], next_cost))
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
    "PythonWorldModel",
    "RuleSet",
    "SandboxExecutor",
    "Trajectory",
    "ValidationReport",
    "WorldModelManifest",
    "WorldModelBridge",
    "decide_meta",
    "emit_meta_decision",
    "plan_bfs",
    "validate_model",
]
