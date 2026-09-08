"""策略引擎四态与 fail-closed（FR-033，AD-12，Story 3.3）。

- 四态：allow / deny / request_approval / degrade（+ basis 依据 + degraded 标志）；
- 默认风险映射（蓝图 §12.4）：R0/R1→allow（自动执行并记录）、R2→allow
  （经策略核）、R3→request_approval（参数级批准）、R4→deny（默认禁止）；
- 自定义规则：首个返回非 None 的规则优先于默认映射；
- 引擎侧 decide 为纯函数；fail-closed 回退在 runtime 接线处实现
  （策略不可用 → R2+ 拒、R0/R1 放行且事件记 degraded）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from vasta_contracts import ActionContract

Decision = Literal["allow", "deny", "request_approval", "degrade"]

#: 蓝图 §12.4 默认风险映射。
DEFAULT_RISK_POLICY: dict[str, Decision] = {
    "R0": "allow",
    "R1": "allow",
    "R2": "allow",
    "R3": "request_approval",
    "R4": "deny",
}


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Decision
    basis: str = ""
    degraded: bool = Field(default=False, description="降级路径标记（事件必录）")


class ApprovalRequestedError(Exception):
    """策略要求人工批准（运行已暂停等待确认）。"""

    def __init__(self, tool: str, risk: str, basis: str) -> None:
        super().__init__(
            f"动作 {tool!r}（{risk}）需要人工批准：{basis}；Run 已暂停"
        )
        self.tool = tool
        self.risk = risk
        self.basis = basis


#: 规则：(contract, effective_risk) -> PolicyDecision | None（None = 不适用）。
Rule = Callable[[ActionContract, str], "PolicyDecision | None"]


class PolicyEngine:
    """四态策略引擎（规则优先，默认按风险映射）。"""

    def __init__(self, rules: list[Rule] | None = None) -> None:
        self.rules = rules or []

    def decide(self, contract: ActionContract, effective_risk: str) -> PolicyDecision:
        for rule in self.rules:
            outcome = rule(contract, effective_risk)
            if outcome is not None:
                return outcome
        default = DEFAULT_RISK_POLICY.get(effective_risk)
        if default is None:
            return PolicyDecision(
                decision="deny", basis=f"未知风险级别 {effective_risk!r}（fail-closed）"
            )
        return PolicyDecision(decision=default, basis=f"默认风险映射 {effective_risk}")


def fail_closed_fallback(effective_risk: str, *, read_only: bool = False) -> PolicyDecision:
    """AD-12：策略引擎不可用时的回退——R2+ 一律拒，低风险**只读**放行并记降级。"""
    if effective_risk in {"R2", "R3", "R4"} or effective_risk not in DEFAULT_RISK_POLICY:
        return PolicyDecision(
            decision="deny",
            basis="策略引擎不可用（fail-closed，AD-12）",
        )
    if not read_only:
        return PolicyDecision(
            decision="deny",
            basis="策略引擎不可用，低风险写动作不放行（AD-12：仅只读可放行）",
        )
    return PolicyDecision(
        decision="allow",
        basis="策略引擎不可用，低风险只读放行（降级路径）",
        degraded=True,
    )


__all__ = [
    "ApprovalRequestedError",
    "DEFAULT_RISK_POLICY",
    "Decision",
    "PolicyDecision",
    "PolicyEngine",
    "Rule",
    "fail_closed_fallback",
]
