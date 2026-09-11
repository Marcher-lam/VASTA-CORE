"""Story 11.5：Agent 角色配置（FR-054，G1）。"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.agents.roles import (
    AgentRole,
    AgentRoleConfig,
    configure_agent_role,
    role_tool_categories,
    trace_role_violation,
    validate_role_action,
)


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


def cfg(role: AgentRole, agent="a1") -> AgentRoleConfig:
    return AgentRoleConfig(agent_id=agent, role=role)


class TestRoleCapability:
    def test_observer_readonly(self) -> None:
        """AC：Observer 只读观察——query/observation 面外全拒。"""
        cats = role_tool_categories(AgentRole.OBSERVER)
        assert cats == {"query", "observation"}
        assert "action" not in cats

    def test_actor_full_execution(self) -> None:
        assert "action" in role_tool_categories(AgentRole.ACTOR)

    def test_verifier_verify_face(self) -> None:
        assert "verify" in role_tool_categories(AgentRole.VERIFIER)
        assert "action" not in role_tool_categories(AgentRole.VERIFIER)

    def test_builder_and_curator_faces(self) -> None:
        assert "build" in role_tool_categories(AgentRole.BUILDER)
        assert "publish" in role_tool_categories(AgentRole.CURATOR)


class TestValidation:
    def test_observer_act_rejected(self, store) -> None:
        with pytest.raises(VastaError) as e:
            validate_role_action(store, cfg(AgentRole.OBSERVER),
                                 "set_status", "action")
        assert e.value.code == "agent.role_violation"
        assert "observer" in str(e.value)

    def test_actor_act_ok(self, store) -> None:
        validate_role_action(store, cfg(AgentRole.ACTOR),
                             "set_status", "action")

    def test_verifier_query_ok(self, store) -> None:
        validate_role_action(store, cfg(AgentRole.VERIFIER),
                             "search", "query")

    def test_builder_build_ok(self, store) -> None:
        validate_role_action(store, cfg(AgentRole.BUILDER),
                             "compile_model", "build")


class TestTrace:
    async def test_role_config_traced(self, store) -> None:
        await configure_agent_role(store, cfg(AgentRole.CURATOR),
                                   configured_by="admin")
        events = [e for e in store.iter_run_events("agent-roles")
                  if e.type == "run.agent_role_set"]
        assert events[-1].payload["role"] == "curator"
        assert events[-1].payload["configured_by"] == "admin"

    async def test_violation_traced(self, store) -> None:
        await trace_role_violation(
            store, cfg(AgentRole.OBSERVER), "delete_all", "action",
            error_message="agent.role_violation: …")
        events = [e for e in store.iter_run_events("agent-roles")
                  if e.type == "run.role_violation"]
        assert events[-1].payload["tool"] == "delete_all"
        assert events[-1].payload["role"] == "observer"
