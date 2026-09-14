"""概率/因果/约束/组合世界模型（Story 11.9，FR-042，G4）。

确定性转移之外的不确定性可建模：

- **ProbabilisticWorldModel**：转移分布（dict 状态→概率）——
  seed 注入采样（确定性测试）；归一化校验（概率和≈1 且逐项
  ∈[0,1]——负概率使质量静默转移给其余项）；
- **CausalModel**：干预查询（do 算子简化——干预即固定变量后
  查询后验）；结构最小（变量依赖表 + 干预覆盖）；
- **ConstraintModel**：可行域校验（谓词列表——全部满足即可行）；
- **CompositeModel**：DSL 组件编排（组件间传递状态——复用
  RuleSet 语义）。

四类模型是进程内纯计算类（结构最小 MVP）——生命周期事件留痕已
经 ``extended_tracing`` 接线（Story 12.3：registered/validated/
used）；沙箱执行面接线与 validation.py 静态检查扩展仍为后续接线
（Stage 6 启动裁决改口——见 docs/epics.md Story 11.9 AC 与
docs/reviews/epic11-code-review.md defer 表）。
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError

ModelTransition = Callable[[dict[str, Any], dict[str, Any]],
                           dict[str, Any]]


class ProbabilisticWorldModel:
    """概率世界模型：转移按分布采样（seed 注入可再生）。"""

    def __init__(self, transitions: dict[str, dict[str, float]],
                 *, seed: int | None = None) -> None:
        for state, dist in transitions.items():
            for target, prob in dist.items():
                if not 0.0 <= prob <= 1.0:
                    raise VastaError(
                        code="model_lab.prob_out_of_range",
                        message=(f"状态 {state!r}→{target!r} 概率 "
                                 f"{prob} ∉ [0,1]——负概率使质量"
                                 "静默转移给其余项"),
                    )
            total = sum(dist.values())
            if abs(total - 1.0) > 0.01:
                raise VastaError(
                    code="model_lab.prob_not_normalized",
                    message=f"状态 {state!r} 概率和 {total} ≠ 1",
                )
        self.transitions = transitions
        self._rng = random.Random(seed) if seed is not None \
            else random.Random()

    def sample_next(self, state_key: str) -> str:
        dist = self.transitions.get(state_key)
        if dist is None:
            raise VastaError(
                code="model_lab.prob_unknown_state",
                message=f"概率模型无状态 {state_key!r}",
            )
        roll = self._rng.random()
        cumulative = 0.0
        for target, prob in sorted(dist.items()):
            cumulative += prob
            if roll < cumulative:
                return target
        # 浮点兜底：最后一项
        return sorted(dist.items())[-1][0]

    def transition(self, state: dict[str, Any],
                   action: dict[str, Any]) -> dict[str, Any]:
        key = str(state.get("_state_key", action.get("to", "default")))
        return {**state, "_state_key": self.sample_next(key)}


class CausalModel(BaseModel):
    """因果模型：变量依赖表 + 干预查询（do 算子简化版）。"""

    model_config = ConfigDict(extra="forbid")

    dependencies: dict[str, list[str]] = Field(
        description="变量 → 直接前因清单（结构最小）")
    mechanisms: dict[str, Callable[[dict[str, Any]], Any]] = Field(
        default_factory=dict,
        description="变量 → 机制函数（输入父变量值；缺省直传）")

    def query(self, observed: dict[str, Any],
              interventions: dict[str, Any] | None = None) -> dict[str, Any]:
        """后验查询：do(interventions) 后按拓扑序推全部变量。"""
        values = dict(observed)
        if interventions:
            values.update(interventions)  # do：固定干预变量
        # 拓扑序（依赖先行——Kahn 简化）
        resolved: set[str] = set()
        pending = set(self.dependencies) | set(self.mechanisms)
        while pending:
            progressed = False
            for var in sorted(pending):
                parents = self.dependencies.get(var, [])
                if all(p in resolved or p not in self.dependencies
                       for p in parents):
                    mech = self.mechanisms.get(var)
                    if mech is not None and var not in (
                            interventions or {}):
                        values[var] = mech(values)
                    resolved.add(var)
                    pending.discard(var)
                    progressed = True
            if not progressed:
                break  # 环或外生——保持观测值
        return values


class ConstraintModel(BaseModel):
    """约束模型：谓词列表全部满足即可行。"""

    model_config = ConfigDict(extra="forbid",
                             arbitrary_types_allowed=True)

    constraints: list[Callable[[dict[str, Any]], bool]] = Field(
        default_factory=list)

    def is_feasible(self, state: dict[str, Any]) -> bool:
        return all(c(state) for c in self.constraints)

    def violations(self, state: dict[str, Any]) -> list[int]:
        return [i for i, c in enumerate(self.constraints)
                if not c(state)]


class CompositeModel(BaseModel):
    """组合模型：DSL 组件编排（顺序传递状态）。"""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    component_rules: list[dict[str, Any]] = Field(
        description="组件 RuleSet 形态规则（顺序执行）")

    def transition(self, state: dict[str, Any],
                   action: dict[str, Any]) -> dict[str, Any]:
        """顺序执行组件规则（DSL 语义：set 覆盖/add 增量——
        后组件可覆盖前组件效果）。

        add 目标须为数值（评审修复 P-5——对字符串状态 add 裸
        TypeError 而非受控错误）。"""
        result = dict(state)
        for rules in self.component_rules:
            rule = rules.get(action.get("to", ""), {})
            for key, value in rule.get("set", {}).items():
                result[key] = value
            for key, delta in rule.get("add", {}).items():
                current = result.get(key, 0)
                if not isinstance(current, (int, float)) or \
                        isinstance(current, bool) or \
                        not isinstance(delta, (int, float)) or \
                        isinstance(delta, bool):
                    raise VastaError(
                        code="model_lab.composite_add_type",
                        message=(f"add 目标 {key}={current!r} 与增量 "
                                 f"{delta!r} 须为数值（DSL add 语义"
                                 "仅数值增量）"),
                    )
                result[key] = current + delta
        return result


__all__ = ["CausalModel", "CompositeModel", "ConstraintModel",
           "ProbabilisticWorldModel"]
