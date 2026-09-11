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


class _ScopedAction:
    """带输入引用的动作桩（input_scope 校验面——Action 协议无
    inputs 字段时由执行器封装）。"""

    def __init__(self, tool: str, inputs: dict | None = None) -> None:
        self.tool = tool
        self.inputs = inputs


class TestReviewRegressions:
    """Epic 11 评审修复回归（盲审 M1、边界 D-1/D-2/D-3/D-4）。"""

    def test_nan_budget_rejected(self) -> None:
        """D-1：NaN/inf 预算穿透三道校验——构造期拒。"""
        import math

        with pytest.raises(VastaError) as e:
            contract(budget={"max_actions": math.nan})
        assert e.value.code == "delegation.bad_budget"

    async def test_unknown_parent_budget_dimension_rejected(
            self, store) -> None:
        """M1.2：父配额缺维度即拒（fail-closed——原缺键跳过即绕过）。"""
        with pytest.raises(VastaError) as e:
            await delegate(store,
                           contract(budget={"max_wall_seconds": 99999}),
                           parent_budget={"max_actions": 50})
        assert e.value.code == "delegation.budget_dimension_unknown"

    async def test_cumulative_overdraw_rejected(self, store) -> None:
        """M1.1：多份委派合计透支父配额拒（committed_budget 对拍）。"""
        with pytest.raises(VastaError) as e:
            await delegate(store, contract(budget={"max_actions": 40}),
                           parent_budget={"max_actions": 50},
                           committed_budget={"max_actions": 40})
        assert e.value.code == "delegation.budget_exceeded"

    def test_input_scope_enforced(self) -> None:
        """M1.3/D-3：input_scope 执行——契约外输入值拒。"""
        validate_action(None, contract(),
                        _ScopedAction("query", {"dataset": "sales-2026"}))
        with pytest.raises(VastaError) as e:
            validate_action(
                None, contract(),
                _ScopedAction("query", {"dataset": "hr-salaries"}))
        assert e.value.code == "delegation.input_out_of_scope"

    def test_input_scope_unknown_key_rejected(self) -> None:
        """M1.3：契约作用域外的输入键拒。"""
        with pytest.raises(VastaError) as e:
            validate_action(
                None, contract(),
                _ScopedAction("query", {"secret_ref": "prod-db"}))
        assert e.value.code == "delegation.input_out_of_scope"

    def test_success_criteria_type_validated(self) -> None:
        """D-2：success_criteria 非字符串列表——构造期拒。"""
        with pytest.raises(VastaError) as e:
            contract(output_contract={"success_criteria": "report"})
        assert e.value.code == "delegation.bad_output_contract"

    def test_negative_budget_used_rejected(self) -> None:
        """D-4：负/NaN 预算用量拒。"""
        with pytest.raises(VastaError) as e:
            validate_action(None, contract(), Action(tool="query", args={}),
                            budget_used={"max_actions": -3})
        assert e.value.code == "delegation.bad_budget_usage"
