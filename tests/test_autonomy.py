"""Story 11.7：动态自治等级（FR-039，G3）。"""

from __future__ import annotations

import pytest

from vasta_storage import SqliteStorage
from vastacore.agents.autonomy import (
    AutonomyInputs,
    AutonomyLevel,
    AutonomyPolicy,
    AutonomyState,
    assess_autonomy,
    compute_score,
    required_approval_for,
    trace_adjustment,
)


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


def inputs(**kw) -> AutonomyInputs:
    base = dict(environment_risk=0.1, tool_risk=0.1,
                operation_risk=0.1, data_sensitivity=0.1)
    base.update(kw)
    return AutonomyInputs(**base)


def state(level=AutonomyLevel.L1_SUGGEST,
          streak=0) -> AutonomyState:
    return AutonomyState(agent_id="a1", level=level,
                         promote_streak=streak)


class TestScoreAndLevel:
    def test_low_risk_maps_l3(self) -> None:
        """低危输入综合分 <0.25 → 目标 L3（从 L3 出发保持）。"""
        policy = AutonomyPolicy()
        assert compute_score(inputs(), policy) < 0.25
        s = assess_autonomy(state(AutonomyLevel.L3_AUTONOMOUS), inputs())
        assert s.level is AutonomyLevel.L3_AUTONOMOUS
        # 从 L1 出发首次达标只蓄势（升档需连胜）
        s1 = assess_autonomy(state(), inputs())
        assert s1.level is AutonomyLevel.L1_SUGGEST  # 未升
        assert s1.promote_streak == 1

    def test_high_risk_maps_l0(self) -> None:
        s = assess_autonomy(state(), inputs(environment_risk=1.0,
                                            tool_risk=1.0,
                                            operation_risk=1.0,
                                            data_sensitivity=1.0))
        assert s.level is AutonomyLevel.L0_OBSERVE

    def test_custom_weights(self) -> None:
        policy = AutonomyPolicy(weights={"environment": 1.0,
                                         "tool": 0.0,
                                         "operation": 0.0,
                                         "data": 0.0})
        # 环境风险独大：0.6 → L1
        s = assess_autonomy(state(), inputs(environment_risk=0.6),
                            policy)
        assert s.level is AutonomyLevel.L1_SUGGEST

    def test_weights_must_sum_one(self) -> None:
        with pytest.raises(ValueError):
            AutonomyPolicy(weights={"environment": 0.5})


class TestAsymmetry:
    def test_demotion_immediate(self) -> None:
        """降级即时（一次即生效）。"""
        s = assess_autonomy(state(AutonomyLevel.L3_AUTONOMOUS, streak=5),
                            inputs(environment_risk=1.0, tool_risk=1.0,
                                   operation_risk=1.0, data_sensitivity=1.0))
        assert s.level is AutonomyLevel.L0_OBSERVE
        assert s.promote_streak == 0

    def test_promotion_needs_streak(self) -> None:
        """升级需连续达标（防抖动）——一次不够。"""
        s1 = assess_autonomy(state(AutonomyLevel.L1_SUGGEST),
                             inputs())  # target L3，streak=1
        assert s1.level is AutonomyLevel.L1_SUGGEST  # 未升
        assert s1.promote_streak == 1
        s2 = assess_autonomy(s1, inputs())  # streak=2 → 升
        assert s2.level is AutonomyLevel.L3_AUTONOMOUS

    def test_promotion_streak_reset_on_miss(self) -> None:
        s1 = assess_autonomy(state(), inputs())  # 达标 streak=1
        s2 = assess_autonomy(s1, inputs(environment_risk=1.0,
                                        tool_risk=1.0,
                                        operation_risk=1.0,
                                        data_sensitivity=1.0))  # 全高危
        assert s2.level is AutonomyLevel.L0_OBSERVE  # 降级即时
        assert s2.promote_streak == 0


class TestApprovalLinkage:
    def test_l0_high_risk_forbidden(self) -> None:
        assert required_approval_for(
            AutonomyLevel.L0_OBSERVE, 0.5) == "forbidden"

    def test_l0_low_risk_required(self) -> None:
        assert required_approval_for(
            AutonomyLevel.L0_OBSERVE, 0.05) == "required"

    def test_l2_mid_free(self) -> None:
        assert required_approval_for(
            AutonomyLevel.L2_ASSIST, 0.3) == "free"

    def test_l2_high_required(self) -> None:
        assert required_approval_for(
            AutonomyLevel.L2_ASSIST, 0.6) == "required"

    def test_l3_free(self) -> None:
        assert required_approval_for(
            AutonomyLevel.L3_AUTONOMOUS, 0.9) == "free"


class TestTrace:
    async def test_adjustment_traced(self, store) -> None:
        old = state(AutonomyLevel.L3_AUTONOMOUS)
        new = assess_autonomy(old, inputs(environment_risk=1.0,
                                          tool_risk=1.0,
                                          operation_risk=1.0,
                                          data_sensitivity=1.0))
        await trace_adjustment(
            store, old, new,
            inputs=inputs(environment_risk=1.0, tool_risk=1.0,
                          operation_risk=1.0, data_sensitivity=1.0),
            tenant_id="t", project_id="p")
        events = [e for e in store.iter_run_events(
            "autonomy", tenant_id="t", project_id="p")
            if e.type == "run.autonomy_adjusted"]
        assert events[-1].payload["from_level"] == "L3"
        assert events[-1].payload["to_level"] == "L0"

    async def test_no_change_no_trace(self, store) -> None:
        s = state(AutonomyLevel.L1_SUGGEST, streak=0)
        await trace_adjustment(store, s, s, inputs=inputs(),
                               tenant_id="t", project_id="p")
        assert not list(store.iter_run_events("autonomy"))
