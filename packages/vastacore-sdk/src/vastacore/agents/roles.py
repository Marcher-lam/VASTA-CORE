"""Agent 角色配置（Story 11.5，FR-054，G1）。

五类可配置角色——多 Agent 协作中职责显式化：

- **AgentRole**：Actor（执行——全工具面）/ Observer（只读观察——
  仅观察与检索）/ Verifier（核验——核验工具面）/ Builder（构建
  ——模型/工件构建面）/ Curator（维护——认知资产维护面）；
- **角色能力面**：每角色声明可调用工具类别——
  ``validate_role_action`` 超面拒（``run.role_violation`` 留痕）；
  （按角色限制事件发射面的机制未在本 Story 交付——SDK 积木
  形态，接线属后续；见 docs/reviews/epic11-code-review.md 保留项）
- **角色配置留痕**（configure_agent_role → ``run.agent_role_set``）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

_ROLES_RUN = "agent-roles"


class AgentRole(StrEnum):
    ACTOR = "actor"
    OBSERVER = "observer"
    VERIFIER = "verifier"
    BUILDER = "builder"
    CURATOR = "curator"


#: 角色能力面：工具类别白名单（元类别——装配面映射到具体工具）。
_ROLE_TOOL_CATEGORIES: dict[AgentRole, frozenset[str]] = {
    AgentRole.ACTOR: frozenset({
        "action", "query", "observation", "report"}),
    AgentRole.OBSERVER: frozenset({"query", "observation"}),
    AgentRole.VERIFIER: frozenset({"verify", "query"}),
    AgentRole.BUILDER: frozenset({"build", "model", "query"}),
    AgentRole.CURATOR: frozenset({"curate", "publish", "query"}),
}


class AgentRoleConfig(BaseModel):
    """Agent 角色配置（agent_id + 角色 + 作用域）。"""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    role: AgentRole
    tenant_id: str = "t-default"
    project_id: str = "p-default"


async def configure_agent_role(
    store: Any, config: AgentRoleConfig, *,
    configured_by: str,
) -> None:
    """角色配置留痕（run.agent_role_set）。"""
    sequencer = EventSequencer(
        store, _ROLES_RUN,
        tenant_id=config.tenant_id, project_id=config.project_id)
    await sequencer.emit("run.agent_role_set", {
        "agent_id": config.agent_id, "role": config.role.value,
        "configured_by": configured_by,
    })


def role_tool_categories(role: AgentRole) -> frozenset[str]:
    """角色可调用工具类别面。"""
    return _ROLE_TOOL_CATEGORIES[role]


def validate_role_action(
    store: Any | None, config: AgentRoleConfig,
    tool: str, tool_category: str,
) -> None:
    """角色边界校验：工具类别不在角色面即拒（fail-closed）。

    留痕（run.role_violation）由调用方异步接（与 11.3 validate_action
    同模式——同步拒、异步痕）。"""
    allowed = _ROLE_TOOL_CATEGORIES[config.role]
    if tool_category not in allowed:
        raise VastaError(
            code="agent.role_violation",
            message=(f"Agent {config.agent_id!r}（角色 {config.role.value}）"
                     f"不可调用 {tool!r}（类别 {tool_category!r} 不在 "
                     f"{sorted(allowed)}——FR-054 角色边界）"),
        )


async def trace_role_violation(
    store: Any, config: AgentRoleConfig,
    tool: str, tool_category: str, *, error_message: str,
) -> None:
    """越界留痕（run.role_violation）。"""
    import contextlib

    with contextlib.suppress(Exception):
        sequencer = EventSequencer(
            store, _ROLES_RUN,
            tenant_id=config.tenant_id, project_id=config.project_id)
        await sequencer.emit("run.role_violation", {
            "agent_id": config.agent_id, "role": config.role.value,
            "tool": tool, "tool_category": tool_category,
            "error": error_message[:200],
        })


__all__ = ["AgentRole", "AgentRoleConfig", "configure_agent_role",
           "role_tool_categories", "trace_role_violation",
           "validate_role_action"]
