"""规则 DSL 世界模型（Story 6.1）——受限、确定、无代码执行。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .manifest import WorldModelManifest


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


