"""Story 11.3：多 Agent 委派契约（FR-050，G1）。"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action
from vasta_storage import SqliteStorage
from vastacore.agents import (
    DelegationContract,
    complete_delegation,
    delegate,
    validate_action,
)


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


def contract(**kw) -> DelegationContract:
    base = dict(
        delegation_id="dlg-1", parent_agent="main", child_agent="worker",
        input_scope={"dataset": "sales-2026"}, permissions=["query", "write_report"],
        budget={"max_actions": 10},
        output_contract={"goal": "生成报告", "success_criteria": ["report_body"]},
    )
    base.update(kw)
    return DelegationContract(**base)


class TestContract:
    def test_empty_permissions_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):  # too_short（fail-closed）
            contract(permissions=[])

    def test_negative_budget_rejected(self) -> None:
        with pytest.raises(VastaError) as e:
            contract(budget={"max_actions": -1})
        assert e.value.code == "delegation.bad_budget"

    def test_missing_success_criteria_rejected(self) -> None:
        with pytest.raises(VastaError) as e:
            contract(output_contract={"goal": "x"})
        assert e.value.code == "delegation.bad_output_contract"


class TestDelegate:
    async def test_created_event_traced(self, store) -> None:
        await delegate(store, contract())
        events = [e for e in store.iter_run_events("delegations")
                  if e.type == "run.delegation_created"]
        assert events[-1].payload["child_agent"] == "worker"
        assert events[-1].payload["permissions"] == ["query", "write_report"]

    async def test_budget_over_parent_rejected(self, store) -> None:
        with pytest.raises(VastaError) as e:
            await delegate(store, contract(budget={"max_actions": 100}),
                           parent_budget={"max_actions": 50})
        assert e.value.code == "delegation.budget_exceeded"

    async def test_within_parent_ok(self, store) -> None:
        await delegate(store, contract(budget={"max_actions": 30}),
                       parent_budget={"max_actions": 50})


class TestValidateAction:
    def test_permitted_tool_ok(self) -> None:
        validate_action(None, contract(), Action(tool="query", args={}))

    def test_unpermitted_tool_rejected(self) -> None:
        with pytest.raises(VastaError) as e:
            validate_action(None, contract(),
                            Action(tool="delete_all", args={}))
        assert e.value.code == "delegation.tool_not_permitted"

    def test_budget_exhausted_rejected(self) -> None:
        with pytest.raises(VastaError) as e:
            validate_action(None, contract(), Action(tool="query", args={}),
                            budget_used={"max_actions": 10})
        assert e.value.code == "delegation.budget_exhausted"

    def test_budget_remaining_ok(self) -> None:
        validate_action(None, contract(), Action(tool="query", args={}),
                        budget_used={"max_actions": 9})


class TestComplete:
    async def test_output_meeting_criteria_passes(self, store) -> None:
        ok = await complete_delegation(
            store, contract(), output={"report_body": "Q3 分析……"})
        assert ok is True
        events = [e for e in store.iter_run_events("delegations")
                  if e.type == "run.delegation_completed"]
        assert events[-1].payload["passed"] is True

    async def test_missing_output_fails_with_detail(self, store) -> None:
        ok = await complete_delegation(store, contract(), output={})
        assert ok is False
        events = [e for e in store.iter_run_events("delegations")
                  if e.type == "run.delegation_completed"]
        assert events[-1].payload["missing"] == ["report_body"]
