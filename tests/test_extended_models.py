"""Story 11.9：概率/因果/约束/组合模型（FR-042，G4）。"""

from __future__ import annotations

import pytest

from vasta_model_lab.extended_models import (
    CausalModel,
    CompositeModel,
    ConstraintModel,
    ProbabilisticWorldModel,
)
from vasta_protocols.errors import VastaError


class TestProbabilistic:
    def test_seed_reproducible(self) -> None:
        """AC：采样可注入 seed（确定性测试）。"""
        t = {"s0": {"s1": 0.7, "s2": 0.3},
             "s1": {"s0": 1.0}, "s2": {"s0": 1.0}}
        a = ProbabilisticWorldModel(t, seed=42)
        b = ProbabilisticWorldModel(t, seed=42)
        seq_a = [a.sample_next("s0") for _ in range(20)]
        seq_b = [b.sample_next("s0") for _ in range(20)]
        assert seq_a == seq_b  # 同 seed 同序列

    def test_distribution_respected(self) -> None:
        t = {"s0": {"s1": 0.7, "s2": 0.3}}
        m = ProbabilisticWorldModel(t, seed=7)
        counts = {"s1": 0, "s2": 0}
        for _ in range(1000):
            counts[m.sample_next("s0")] += 1
        assert 600 < counts["s1"] < 800  # ≈70%

    def test_not_normalized_rejected(self) -> None:
        with pytest.raises(VastaError) as e:
            ProbabilisticWorldModel({"s0": {"s1": 0.5}})
        assert e.value.code == "model_lab.prob_not_normalized"

    def test_unknown_state_rejected(self) -> None:
        m = ProbabilisticWorldModel({"s0": {"s1": 1.0}})
        with pytest.raises(VastaError):
            m.sample_next("ghost")

    def test_transition(self) -> None:
        m = ProbabilisticWorldModel(
            {"s0": {"s1": 1.0}, "s1": {"s0": 1.0}}, seed=1)
        out = m.transition({"_state_key": "s0"}, {})
        assert out["_state_key"] == "s1"


class TestCausal:
    def test_intervention_fixed(self) -> None:
        """AC：干预查询（do 算子——干预变量固定不被机制覆写）。"""
        model = CausalModel(
            dependencies={"y": ["x"], "z": ["y"]},
            mechanisms={"y": lambda v: (v.get("x", 0)) * 2,
                        "z": lambda v: (v.get("y", 0)) + 1})
        base = model.query({"x": 3})
        assert base["y"] == 6 and base["z"] == 7
        do = model.query({"x": 3}, interventions={"y": 100})
        assert do["y"] == 100  # do 固定
        assert do["z"] == 101  # 下游按干预值推

    def test_observed_passthrough(self) -> None:
        model = CausalModel(dependencies={})
        assert model.query({"a": 1}) == {"a": 1}

    def test_cycle_terminates(self) -> None:
        """环依赖不死循环（保持观测值）。"""
        model = CausalModel(
            dependencies={"a": ["b"], "b": ["a"]})
        out = model.query({"a": 1, "b": 2})
        assert out == {"a": 1, "b": 2}


class TestConstraint:
    def test_feasible(self) -> None:
        c = ConstraintModel(constraints=[
            lambda s: s["x"] >= 0, lambda s: s["x"] <= 10])
        assert c.is_feasible({"x": 5}) is True

    def test_infeasible_with_indices(self) -> None:
        c = ConstraintModel(constraints=[
            lambda s: s["x"] >= 0, lambda s: s["x"] <= 10])
        assert c.is_feasible({"x": 15}) is False
        assert c.violations({"x": 15}) == [1]  # 第 2 条违例


class TestComposite:
    def test_sequential_components(self) -> None:
        """AC：组件编排（DSL set/add 语义——后组件覆盖）。"""
        comp = CompositeModel(component_rules=[
            {"right": {"set": {"score": 1}, "add": {"steps": 1}}},
            {"right": {"add": {"score": 10}}},  # 第二组件叠加
        ])
        out = comp.transition({"score": 0, "steps": 0},
                             {"to": "right"})
        assert out["score"] == 11  # 1(set) + 10(add)
        assert out["steps"] == 1

    def test_no_matching_rule_passthrough(self) -> None:
        comp = CompositeModel(component_rules=[{"right": {"set": {"x": 1}}}])
        assert comp.transition({"x": 0}, {"to": "left"}) == {"x": 0}
