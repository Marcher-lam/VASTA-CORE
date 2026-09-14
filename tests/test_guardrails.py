"""Story 12.2：enforcement 面组装接线（Epic 11 复盘 F1/item-22，G0）。

「组件齐、组合碎」三连根治——六个零入向调用的 enforcement 面组装为
单一动作闸门，并被 AgentSession 真实执行路径强制（依赖倒置钩子）。
"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action
from vasta_storage import SqliteStorage
from vastacore.agents.autonomy import AutonomyLevel, AutonomyState
from vastacore.agents.delegation import DelegationContract
from vastacore.agents.guardrails import (
    GuardRailConfig,
    GuardState,
    guard_action,
    make_action_guard,
)
from vastacore.agents.leaderboard import (
    LeaderboardSpec,
    leaderboard_from_tournament,
)
from vastacore.agents.risk_budget import ExposureRecord, RiskBudget
from vastacore.agents.roles import AgentRole, AgentRoleConfig
from vastacore.agents.tournament import Candidate, TournamentSpec, run_tournament


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


def config(role: AgentRole = AgentRole.ACTOR, **kw) -> GuardRailConfig:
    base = dict(
        agent_id="agent-1",
        role_config=AgentRoleConfig(agent_id="agent-1", role=role),
        risk_budget=RiskBudget(
            scope="agent:agent-1", risk_units=10.0, high_risk_ops=10),
    )
    base.update(kw)
    return GuardRailConfig(**base)


def state() -> GuardState:
    return GuardState(
        autonomy=AutonomyState(agent_id="agent-1"),
        exposure=ExposureRecord(scope="agent:agent-1",
                                risk_units_used=0.0,
                                high_risk_ops_used=0))


def contract(**kw) -> DelegationContract:
    base = dict(
        delegation_id="d1", parent_agent="main", child_agent="agent-1",
        input_scope={}, permissions=["set_status"],
        budget={"max_actions": 10},
        output_contract={"success_criteria": ["report"]},
    )
    base.update(kw)
    return DelegationContract(**base)


ACTION = Action(tool="set_status", args={"status": "done"})


class TestGuardAction:
    async def test_role_violation_rejected_and_traced(self, store) -> None:
        """① 角色边界：Observer 执行类动作拒 + run.role_violation 留痕。"""
        with pytest.raises(VastaError) as e:
            await guard_action(store, config(AgentRole.OBSERVER), state(),
                               ACTION, tool_category="action",
                               operation_risk=0.2)
        assert e.value.code == "agent.role_violation"
        events = [ev for ev in store.iter_run_events("agent-roles")
                  if ev.type == "run.role_violation"]
        assert events, "角色越界必须留痕"

    async def test_delegation_contract_enforced(self, store) -> None:
        """② 委派契约：契约外工具在闸门处拒（validate_action 接线）。"""
        cfg = config(contract=contract(permissions=["other_tool"]))
        with pytest.raises(VastaError) as e:
            await guard_action(store, cfg, state(), ACTION,
                               tool_category="action",
                               operation_risk=0.2)
        assert e.value.code == "delegation.tool_not_permitted"

    async def test_autonomy_forbidden_operation_rejected(self, store) -> None:
        """③④ 自治 + 审批矩阵：L0 × 高危操作禁批。"""
        st = state()
        st.autonomy = st.autonomy.model_copy(
            update={"level": AutonomyLevel.L0_OBSERVE})
        with pytest.raises(VastaError) as e:
            await guard_action(store, config(), st, ACTION,
                               tool_category="action",
                               operation_risk=0.5)
        assert e.value.code == "guardrails.operation_forbidden"

    async def test_risk_budget_breach_rejected_and_traced(self, store) -> None:
        """⑤ 风险预算：敞口触顶动作拒 + enforcement 留痕（breached）。"""
        cfg = config(risk_budget=RiskBudget(
            scope="agent:agent-1", risk_units=1.0, high_risk_ops=10))
        st = state()
        st.autonomy = st.autonomy.model_copy(
            update={"level": AutonomyLevel.L2_ASSIST})
        with pytest.raises(VastaError) as e:
            # 0.6：L2 下 required（放行）且高危 → 权重 1.0 触顶
            await guard_action(store, cfg, st, ACTION,
                               tool_category="action",
                               operation_risk=0.6)
        assert e.value.code == "guardrails.risk_budget_breached"
        events = [ev for ev in store.iter_run_events("risk-budgets")
                  if ev.type == "run.risk_budget_enforced"]
        assert events and events[-1].payload["breached"] is True

    async def test_allowed_decision_with_approval_flag(self, store) -> None:
        """放行路径：required 标记 + 自治/敞口状态推进。"""
        st = state()
        st.autonomy = st.autonomy.model_copy(
            update={"level": AutonomyLevel.L1_SUGGEST})
        decision = await guard_action(
            store, config(), st, ACTION, tool_category="action",
            operation_risk=0.4)
        assert decision.allowed
        assert decision.requires_approval  # L1 × 0.4 → required
        assert st.exposure.high_risk_ops_used == 0  # 0.4 非高危


class TestRuntimeEnforced:
    """AC：每个 enforcement 面至少一条**被运行时路径强制**的组合测试
    ——AgentSession.act() 是真实执行路径（闸门拒绝 → 六段链不发生）。"""

    async def test_observer_act_rejected_on_runtime_path(self, tmp_path,
                                                         store) -> None:
        """Observer 角色经 AgentSession.act() 拒——action.executed
        不发生（非函数级拒）。"""
        from tests.test_agent_sdk import STATUS_CONTRACT, SetStatusTool, TodoEnv
        from vastacore.execution.agent import AgentSession

        guard = make_action_guard(
            store, config(AgentRole.OBSERVER), state(),
            tool_category_of=lambda _tool: "action")
        session = await AgentSession.create(
            env=TodoEnv(), tools=[SetStatusTool()],
            contracts={"set_status": STATUS_CONTRACT},
            root=tmp_path / "store", seed=7,
            action_guard=guard)  # 12.2 官方接法——组装层注入
        async with session:
            await session.start()
            await session.reset()
            with pytest.raises(VastaError) as e:
                await session.act(ACTION)
            assert e.value.code == "agent.role_violation"
            types = [ev.type for ev in session.events()]
            assert "action.executed" not in types  # 拒之门外

    async def test_actor_act_passes_gate(self, tmp_path, store) -> None:
        """Actor 角色闸门放行——六段链照常走完（闸不破坏正常路径）。"""
        from tests.test_agent_sdk import STATUS_CONTRACT, SetStatusTool, TodoEnv
        from vastacore.execution.agent import AgentSession

        guard = make_action_guard(
            store, config(AgentRole.ACTOR), state(),
            tool_category_of=lambda _tool: "action")
        session = await AgentSession.create(
            env=TodoEnv(), tools=[SetStatusTool()],
            contracts={"set_status": STATUS_CONTRACT},
            root=tmp_path / "store", seed=7,
            action_guard=guard)
        async with session:
            await session.start()
            await session.reset()
            observations = await session.act(ACTION)
            assert observations
            types = [ev.type for ev in session.events()]
            assert "action.executed" in types


class TestTournamentLeaderboardSeam:
    """AC：tournament→leaderboard 点名缝（11.12 AC 遗留）。"""

    async def test_seam_reads_settled_event(self, store) -> None:
        """聚合缝从 settled 事件回读——条目引用事件 seq（证据引用
        语义），失败候选不入榜。"""
        async def runner(name: str) -> dict[str, float]:
            if name == "broken":
                raise RuntimeError("candidate failed")
            return {"success_rate": 0.9 if name == "alpha" else 0.8}

        report = await run_tournament(store, TournamentSpec(
            tournament_id="t-1",
            candidates=[Candidate(name="alpha"), Candidate(name="beta"),
                        Candidate(name="broken")],
            metrics=["success_rate"]), runner)
        spec = LeaderboardSpec(
            leaderboard_id="lb-seam", metric="success_rate",
            window_start="2026-09-01T00:00:00+00:00",
            window_end="2026-09-30T00:00:00+00:00")
        board = await leaderboard_from_tournament(store, report, spec)
        assert [e.candidate for e in board.entries] == ["alpha", "beta"]
        # 证据引用：两候选条目都指向同一 settled 事件的 seq
        settled_seqs = {
            ev.seq for ev in store.iter_run_events("evaluation")
            if ev.type == "evaluation.tournament_settled"}
        assert {e.evidence_event_seq for e in board.entries} \
            == settled_seqs
        assert all(e.evidence_run == "evaluation" for e in board.entries)

    async def test_seam_without_settled_rejected(self, store) -> None:
        from vastacore.agents.tournament import TournamentReport

        spec = LeaderboardSpec(
            leaderboard_id="lb-x", metric="success_rate",
            window_start="2026-09-01T00:00:00+00:00",
            window_end="2026-09-30T00:00:00+00:00")
        with pytest.raises(VastaError) as e:
            await leaderboard_from_tournament(
                store, TournamentReport(tournament_id="ghost", results=[],
                                        winner=None), spec)
        assert e.value.code == "leaderboard.tournament_not_settled"


class TestFiniteHelperAdoption:
    """AC：require_finite 收口——散布守卫统一（6 处抛出型语义）。"""

    def test_delegation_budget_nan_via_helper(self) -> None:
        import math

        with pytest.raises(VastaError) as e:
            contract(budget={"max_actions": math.nan})
        assert e.value.code == "delegation.bad_budget"

    async def test_risk_weight_negative_via_helper(self, store) -> None:
        from vastacore.agents.risk_budget import record_risk_exposure

        with pytest.raises(VastaError) as e:
            await record_risk_exposure(
                store, ExposureRecord(scope="a", risk_units_used=0.0,
                                      high_risk_ops_used=0),
                risk_weight=-1.0, is_high_risk=True)
        assert e.value.code == "riskbudget.bad_weight"

    def test_guard_config_bad_weight(self) -> None:
        with pytest.raises(VastaError):
            config(risk_weight=float("nan"))
