"""Story 11.7：动态自治等级（FR-039，G3）。"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.agents.autonomy import (
    AutonomyInputs,
    AutonomyLevel,
    AutonomyPolicy,
    AutonomyState,
    _level_for_score,
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

    def test_promotion_needs_streak_stepwise(self) -> None:
        """升级需连续达标（防抖动）且逐级推进（评审修复 H4——
        一次不够、两次升一级而非跳档）。"""
        s1 = assess_autonomy(state(AutonomyLevel.L1_SUGGEST),
                             inputs())  # target L3，streak=1
        assert s1.level is AutonomyLevel.L1_SUGGEST  # 未升
        assert s1.promote_streak == 1
        s2 = assess_autonomy(s1, inputs())  # streak=2 → 升一级
        assert s2.level is AutonomyLevel.L2_ASSIST  # 不跳 L3
        assert s2.promote_streak == 0
        s3 = assess_autonomy(s2, inputs())  # streak=1 未满
        assert s3.level is AutonomyLevel.L2_ASSIST
        s4 = assess_autonomy(s3, inputs())
        assert s4.level is AutonomyLevel.L3_AUTONOMOUS

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


class TestReviewRegressions:
    """Epic 11 评审修复回归（盲审 H4、边界 A-1/A-2/A-3/A-4、
    验证缺口 G2 阈值边界）。"""

    def test_same_level_readings_do_not_accumulate_streak(self) -> None:
        """H4：同级读数不蓄势——L1 上 N 次同级读数后，单次低危
        读数不可携历史计数跳档。"""
        s = state(AutonomyLevel.L1_SUGGEST)
        # score=0.7 → target L1（同级）——重复任意次
        same = inputs(environment_risk=0.7, tool_risk=0.7,
                      operation_risk=0.7, data_sensitivity=0.7)
        for _ in range(5):
            s = assess_autonomy(s, same)
        assert s.level is AutonomyLevel.L1_SUGGEST
        assert s.promote_streak == 0  # 同级不蓄势
        # 单次低危读数（target L3）：streak=1 < 2 → 不升
        s = assess_autonomy(s, inputs())
        assert s.level is AutonomyLevel.L1_SUGGEST
        assert s.promote_streak == 1

    def test_no_skip_level_promotion(self) -> None:
        """A-4：跨档读数不跳级——L0 上 target=L3 连胜满也只到 L1。"""
        s = state(AutonomyLevel.L0_OBSERVE)
        s = assess_autonomy(s, inputs())  # streak=1
        s = assess_autonomy(s, inputs())  # streak=2 → L1（非 L3）
        assert s.level is AutonomyLevel.L1_SUGGEST

    def test_negative_weight_rejected(self) -> None:
        """A-1：负权重使风险方向反转——构造期拒（12.2 起 VastaError
        统一错误信封口径）。"""
        with pytest.raises(VastaError):
            AutonomyPolicy(weights={"environment": -0.5, "tool": 0.5,
                                    "operation": 0.5, "data": 0.5})

    def test_nan_weight_rejected(self) -> None:
        """A-1：NaN 权重静默失效——构造期拒。"""
        with pytest.raises(VastaError):
            AutonomyPolicy(weights={
                "environment": float("nan"), "tool": 0.3,
                "operation": 0.3, "data": 0.4})

    def test_extra_weight_key_rejected(self) -> None:
        """A-2：多余键不再静默忽略。"""
        with pytest.raises(ValueError):
            AutonomyPolicy(weights={"environment": 0.2, "tool": 0.3,
                                    "operation": 0.3, "data": 0.1,
                                    "bogus": 0.1})

    def test_non_monotonic_thresholds_rejected(self) -> None:
        """A-3：非单调阈值使档位互斥失效——构造期拒。"""
        with pytest.raises(ValueError):
            AutonomyPolicy(thresholds=(0.9, 0.1, 0.5))

    def test_threshold_boundaries(self) -> None:
        """G2：默认阈值边界分数的档位断言（< 语义锚定——
        0.25/0.50/0.75 恰为边界时落入下一档）。"""
        assert _level_for_score(0.25, AutonomyPolicy()) \
            is AutonomyLevel.L2_ASSIST  # 恰 0.25 不属 L3
        assert _level_for_score(0.50, AutonomyPolicy()) \
            is AutonomyLevel.L1_SUGGEST
        assert _level_for_score(0.75, AutonomyPolicy()) \
            is AutonomyLevel.L0_OBSERVE
        assert _level_for_score(0.2499, AutonomyPolicy()) \
            is AutonomyLevel.L3_AUTONOMOUS  # 边界内侧
        assert _level_for_score(0.0, AutonomyPolicy()) \
            is AutonomyLevel.L3_AUTONOMOUS
