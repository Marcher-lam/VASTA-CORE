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


class TestReviewRegressions:
    """Epic 12 评审修复回归（边界 2-1/2-6、盲审 L2、缺口 M09）。"""

    async def test_concurrent_guards_do_not_lose_exposure(
            self, store) -> None:
        """GR-1：同一 GuardState 并发闸门不丢敞口更新（4 并发高危
        动作 → 敞口 4.0，此前交错丢失恒 ≈1——FR-077 绕过）。"""
        import asyncio

        cfg = config(risk_budget=RiskBudget(
            scope="agent:agent-1", risk_units=100.0, high_risk_ops=100))
        st = state()
        st.autonomy = st.autonomy.model_copy(
            update={"level": AutonomyLevel.L3_AUTONOMOUS})

        async def one(i: int):
            return await guard_action(
                store, cfg, st, Action(tool="set_status", args={"i": i}),
                tool_category="action", operation_risk=0.6)

        await asyncio.gather(*(one(i) for i in range(4)))
        assert st.exposure.risk_units_used == pytest.approx(4.0)
        assert st.exposure.high_risk_ops_used == 4

    async def test_rejected_action_does_not_commit_state(
            self, store) -> None:
        """GR-3：被拒动作不推进自治连胜/不计量敞口（此前被拒读数
        蓄势、被拒动作计敞口）。"""
        st = state()
        st.autonomy = st.autonomy.model_copy(
            update={"level": AutonomyLevel.L0_OBSERVE})
        with pytest.raises(VastaError):
            await guard_action(store, config(), st, ACTION,
                               tool_category="action",
                               operation_risk=0.5)  # L0×0.5 → forbidden
        assert st.autonomy.promote_streak == 0  # 被拒不蓄势
        assert st.exposure.risk_units_used == 0.0  # 被拒不计量
        assert st.exposure.high_risk_ops_used == 0

    async def test_inputs_operation_risk_single_source(
            self, store) -> None:
        """GR-3：inputs 给定时 operation_risk 以 inputs 为准（两口径
        合一——此前审批矩阵与自治评估互不校验）。"""
        from vastacore.agents.autonomy import AutonomyInputs

        st = state()
        st.autonomy = st.autonomy.model_copy(
            update={"level": AutonomyLevel.L0_OBSERVE})
        with pytest.raises(VastaError) as e:
            await guard_action(
                store, config(), st, ACTION, tool_category="action",
                operation_risk=0.05,  # 入参低危
                inputs=AutonomyInputs(  # 四维口径高危 → forbidden
                    environment_risk=0.0, tool_risk=0.0,
                    operation_risk=0.5, data_sensitivity=0.0))
        assert e.value.code == "guardrails.operation_forbidden"

    async def test_non_finite_operation_risk_rejected(self, store) -> None:
        """M09（G1）：NaN/负 operation_risk 在闸门入口拒——此前直灌
        审批矩阵使 forbidden 判对 NaN 恒 False（禁批可翻放行）。"""
        for bad in (float("nan"), float("inf"), -0.1):
            with pytest.raises(VastaError) as e:
                await guard_action(store, config(), state(), ACTION,
                                   tool_category="action",
                                   operation_risk=bad)
            assert e.value.code == "guardrails.bad_operation_risk"

    async def test_runtime_guard_rejects_nan_risk(self, tmp_path,
                                                  store) -> None:
        """M09 运行时路径：operation_risk_of 产 NaN → AgentSession
        拒（action.executed 不发生）。"""
        from tests.test_agent_sdk import STATUS_CONTRACT, SetStatusTool, TodoEnv
        from vastacore.execution.agent import AgentSession

        guard = make_action_guard(
            store, config(), state(),
            tool_category_of=lambda _t: "action",
            operation_risk_of=lambda _t: float("nan"))
        session = await AgentSession.create(
            env=TodoEnv(), tools=[SetStatusTool()],
            contracts={"set_status": STATUS_CONTRACT},
            root=tmp_path / "store", seed=7, action_guard=guard)
        async with session:
            await session.start()
            await session.reset()
            with pytest.raises(VastaError):
                await session.act(ACTION)
            assert "action.executed" not in [
                ev.type for ev in session.events()]

    async def test_budget_channel_in_official_guard(self, store) -> None:
        """GR-2：官方接法 make_action_guard 下委派预算腿生效（此前
        该腿无参数通道、永不触发）。"""
        guard = make_action_guard(
            store,
            config(contract=contract(budget={"max_actions": 5})), state(),
            tool_category_of=lambda _t: "action",
            budget_used_of=lambda _t: {"max_actions": 5})  # 已用满
        with pytest.raises(VastaError) as e:
            await guard(ACTION)
        assert e.value.code == "delegation.budget_exhausted"

    async def test_unknown_tool_category_rejected(self, store) -> None:
        """2-5：类别映射缺键 → 受控 VastaError（非裸 KeyError）。"""
        guard = make_action_guard(
            store, config(), state(),
            tool_category_of=lambda tool: {
                "known": "action"}[tool])  # 只有 known
        with pytest.raises(VastaError) as e:
            await guard(Action(tool="unknown", args={}))
        assert e.value.code == "guardrails.bad_tool_category"


class TestSharedReadFace:
    """验收保留项 1 清偿：check_shared_access 官方接线面。"""

    async def test_shared_read_gate_denied_traced(self, store) -> None:
        """越权读共享资产 → 拒 + run.access_denied 留痕（11.6 defer
        #5 部分清偿）。"""
        from vastacore.agents.guardrails import guard_shared_asset_read
        from vastacore.agents.sharing import ShareGrant, Visibility
        from vastacore.governance.rbac import Principal, Role

        grant = ShareGrant(asset_ref="c1", asset_kind="claim",
                           visibility=Visibility.PROJECT,
                           publisher_org="org-a", publisher_agent="a",
                           tenant_id="t", project_id="p-a")
        outsider = Principal(user="x", role=Role.OPERATOR,
                             tenant_id="t", project_id="p-other")
        with pytest.raises(VastaError):
            await guard_shared_asset_read(store, grant, reader=outsider,
                                          reader_org="org-a",
                                          tenant_id="t", project_id="p-a")
        events = [e for e in store.iter_run_events("sharing")
                  if e.type == "run.access_denied"]
        assert events and events[-1].payload["asset_ref"] == "c1"

    async def test_shared_read_gate_allows_authorized(self, store) -> None:
        from vastacore.agents.guardrails import guard_shared_asset_read
        from vastacore.agents.sharing import ShareGrant, Visibility
        from vastacore.governance.rbac import Principal, Role

        grant = ShareGrant(asset_ref="c1", asset_kind="claim",
                           visibility=Visibility.PROJECT,
                           publisher_org="org-a", publisher_agent="a",
                           tenant_id="t", project_id="p-a")
        insider = Principal(user="ok", role=Role.OPERATOR,
                            tenant_id="t", project_id="p-a")
        await guard_shared_asset_read(store, grant, reader=insider,
                                      reader_org="org-a",
                                      tenant_id="t", project_id="p-a")


class TestSessionLevelFourFaces:
    """item-35：enforcement 四面在 AgentSession 真实执行路径的正反例
    （角色面已有——此处补齐委派/自治审批/风险预算三面）。"""

    async def _session(self, tmp_path, store, config, state,
                       operation_risk_of=None):
        from tests.test_agent_sdk import STATUS_CONTRACT, SetStatusTool, TodoEnv
        from vastacore.execution.agent import AgentSession

        guard = make_action_guard(
            store, config, state,
            tool_category_of=lambda _t: "action",
            operation_risk_of=operation_risk_of or (lambda _t: 0.3))
        return await AgentSession.create(
            env=TodoEnv(), tools=[SetStatusTool()],
            contracts={"set_status": STATUS_CONTRACT},
            root=tmp_path / "store", seed=7, action_guard=guard)

    async def test_session_delegation_face(self, tmp_path, store) -> None:
        """委派面：契约外工具经 act() 拒——action.executed 不发生。"""
        cfg = config(contract=contract(permissions=["other_tool"]))
        session = await self._session(tmp_path, store, cfg, state())
        async with session:
            await session.start()
            await session.reset()
            with pytest.raises(VastaError) as e:
                await session.act(ACTION)
            assert e.value.code == "delegation.tool_not_permitted"
            assert "action.executed" not in [
                ev.type for ev in session.events()]

    async def test_session_approval_face(self, tmp_path, store) -> None:
        """自治×审批面：L0 禁批档经 act() 拒。"""
        st = state()
        st.autonomy = st.autonomy.model_copy(
            update={"level": AutonomyLevel.L0_OBSERVE})
        session = await self._session(tmp_path, store, config(), st,
                                      operation_risk_of=lambda _t: 0.5)
        async with session:
            await session.start()
            await session.reset()
            with pytest.raises(VastaError) as e:
                await session.act(ACTION)
            assert e.value.code == "guardrails.operation_forbidden"
            assert "action.executed" not in [
                ev.type for ev in session.events()]

    async def test_session_budget_face(self, tmp_path, store) -> None:
        """风险预算面：敞口触顶经 act() 拒 + breached 留痕。"""
        cfg = config(risk_budget=RiskBudget(
            scope="agent:agent-1", risk_units=1.0, high_risk_ops=10))
        st = state()
        st.autonomy = st.autonomy.model_copy(
            update={"level": AutonomyLevel.L3_AUTONOMOUS})
        session = await self._session(tmp_path, store, cfg, st,
                                      operation_risk_of=lambda _t: 0.6)
        async with session:
            await session.start()
            await session.reset()
            with pytest.raises(VastaError) as e:
                await session.act(ACTION)  # 高危 1.0 → 触顶
            assert e.value.code == "guardrails.risk_budget_breached"
            events = [ev for ev in store.iter_run_events("risk-budgets")
                      if ev.type == "run.risk_budget_enforced"]
            assert events[-1].payload["breached"] is True

    async def test_session_all_faces_pass_path(self, tmp_path,
                                               store) -> None:
        """四面全过：Actor 无契约 L3 低危——六段链照常走完。"""
        st = state()
        st.autonomy = st.autonomy.model_copy(
            update={"level": AutonomyLevel.L3_AUTONOMOUS})
        session = await self._session(tmp_path, store, config(), st)
        async with session:
            await session.start()
            await session.reset()
            observations = await session.act(ACTION)
            assert observations
            assert "action.executed" in [
                ev.type for ev in session.events()]
