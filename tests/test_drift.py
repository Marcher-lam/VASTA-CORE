"""Story 10.4：模型漂移检测与影响告警（FR-067 + FR-049 部分，G1）。

三通道阈值判定；模型级重验证（C4 解除）；告警→incident 联动
（关联真实消费 Run）；影响面报告与处置建议。
"""

from __future__ import annotations

import pytest

from vasta_storage import SqliteStorage
from vastacore.governance.drift import (
    DriftMetrics,
    DriftPolicy,
    affected_runs_of_model,
    evaluate_drift,
    revalidate_model,
    run_drift_check,
)
from vastacore.governance.quotas import CostLedger
from vastacore.governance.versioning import publish_model_version

RULESET = {"rules": {"right": {"add": {"col": 1}}}, "goal_check": "done"}
MANIFEST = {"name": "grid", "version": "1.0", "scope": "grid",
            "unknowns": ["u"], "coverage": ["right"]}


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


async def seeded(store) -> None:
    await publish_model_version(store, "grid", "1.0.0", ruleset=RULESET,
                                manifest=MANIFEST)


def fake_evaluator(passed: bool, score: float):
    calls: list[tuple[str, str, str]] = []

    async def evaluator(kind, name, version, bundle):
        calls.append((kind, name, version))
        assert "ruleset" in bundle  # registry bundle 传入
        return {"passed": passed, "score": score, "details": "test"}

    evaluator.calls = calls  # type: ignore[attr-defined]
    return evaluator


class TestThresholds:
    def test_no_drift_when_all_within(self) -> None:
        ok, breaches = evaluate_drift(
            DriftMetrics(success_rate=0.95, revalidation_fail_rate=0.05,
                         distribution_shift=0.1), DriftPolicy())
        assert ok is False and breaches == []

    def test_each_channel_breaches(self) -> None:
        cases = [
            (DriftMetrics(success_rate=0.80), ["performance"]),
            (DriftMetrics(revalidation_fail_rate=0.5),
             ["revalidation_fail_rate"]),
            (DriftMetrics(distribution_shift=0.9), ["distribution_shift"]),
        ]
        for metrics, expected in cases:
            ok, breaches = evaluate_drift(metrics, DriftPolicy())
            assert ok is True and breaches == expected

    def test_custom_policy(self) -> None:
        ok, _ = evaluate_drift(DriftMetrics(success_rate=0.85),
                               DriftPolicy(success_rate_floor=0.80))
        assert ok is False


class TestDriftCheck:
    async def test_no_drift_no_incident(self, store) -> None:
        """未超阈：指标留痕但零联动（无重验证/无 incident）。"""
        await seeded(store)
        report = await run_drift_check(
            store, "model", "grid", "1.0.0",
            DriftMetrics(success_rate=0.99), evaluator=fake_evaluator(True, 1))
        assert report.drifted is False
        assert report.incident_id is None
        assert report.recommended_action == "none"
        measured = [e for e in store.iter_run_events("evaluation")
                    if e.type == "evaluation.model_drift_measured"]
        assert measured[-1].payload["drifted"] is False  # 留痕含阴性结果

    async def test_drift_revalidation_fail_sev1_suspend(self, store) -> None:
        """超阈 + 重验证失败 → sev1 incident + 建议 suspend（C4 链路）。"""
        await seeded(store)
        evaluator = fake_evaluator(False, 0.2)
        report = await run_drift_check(
            store, "model", "grid", "1.0.0",
            DriftMetrics(success_rate=0.70), evaluator=evaluator)
        assert report.drifted and report.breaches == ["performance"]
        assert report.revalidation_passed is False
        assert report.recommended_action == "suspend"
        assert evaluator.calls == [("model", "grid", "1.0.0")]  # 真跑了
        revalidated = [e for e in store.iter_run_events("evaluation")
                       if e.type == "evaluation.model_revalidated"]
        assert revalidated[-1].payload["passed"] is False
        incidents = [e for e in store.iter_run_events("incidents")
                     if e.type == "incident.declared"]
        assert incidents[-1].payload["severity"] == "sev1"

    async def test_drift_revalidation_pass_sev2_monitor(self, store) -> None:
        """超阈 + 重验证通过 → sev2（指标漂移但性质仍守）+ monitor。"""
        await seeded(store)
        report = await run_drift_check(
            store, "model", "grid", "1.0.0",
            DriftMetrics(success_rate=0.85),
            evaluator=fake_evaluator(True, 0.95))
        assert report.revalidation_passed is True
        assert report.recommended_action == "monitor"
        incidents = [e for e in store.iter_run_events("incidents")
                     if e.type == "incident.declared"]
        assert incidents[-1].payload["severity"] == "sev2"

    async def test_distribution_shift_rollback_candidate(self, store) -> None:
        """分布偏移主导 → rollback 候选（环境变化的典型处置）。"""
        await seeded(store)
        report = await run_drift_check(
            store, "model", "grid", "1.0.0",
            DriftMetrics(distribution_shift=0.8),
            evaluator=fake_evaluator(True, 1.0))
        assert report.recommended_action == "rollback-candidate"

    async def test_incident_associates_consuming_runs(self, store) -> None:
        """incident 关联真实消费 Run（billing 反查——用过才关联）。"""
        await seeded(store)
        await CostLedger.record(store, "run-a", tenant_id="t-default",
                                project_id="p-default", model="grid",
                                calls=3, estimated_cost=0.1, basis="usage")
        await CostLedger.record(store, "run-b", tenant_id="t-default",
                                project_id="p-default", model="other",
                                calls=1, estimated_cost=0.1, basis="usage")
        report = await run_drift_check(
            store, "model", "grid", "1.0.0",
            DriftMetrics(success_rate=0.5), evaluator=fake_evaluator(True, 1))
        assert report.affected_runs == ["run-a"]  # 只关联消费过 grid 的
        incidents = [e for e in store.iter_run_events("incidents")
                     if e.type == "incident.declared"]
        assert incidents[-1].payload["related_runs"] == ["run-a"]

    async def test_plans_included_in_report(self, store) -> None:
        await seeded(store)
        report = await run_drift_check(
            store, "model", "grid", "1.0.0",
            DriftMetrics(success_rate=0.5), evaluator=fake_evaluator(True, 1),
            plans_of_model=lambda v: ["plan-x"] if v == "1.0.0" else [])
        assert report.affected_plans == ["plan-x"]

    async def test_without_evaluator_still_incidents(self, store) -> None:
        """evaluator 缺省：跳过重验证（None 如实记录）但 incident 照发
        （severity=sev1——无重验证证据按不可信处理，fail-closed）。"""
        await seeded(store)
        report = await run_drift_check(
            store, "model", "grid", "1.0.0", DriftMetrics(success_rate=0.5))
        assert report.revalidation_passed is None
        assert report.incident_id is not None
        incidents = [e for e in store.iter_run_events("incidents")
                     if e.type == "incident.declared"]
        assert incidents[-1].payload["severity"] == "sev1"


class TestModelRevalidation:
    async def test_revalidate_emits_event(self, store) -> None:
        """C4 字面：受影响模型跑重验证——事件留痕（verdict+score）。"""
        await seeded(store)
        result = await revalidate_model(
            store, "model", "grid", "1.0.0",
            evaluator=fake_evaluator(True, 0.88))
        assert result == {"passed": True, "score": 0.88}
        events = [e for e in store.iter_run_events("evaluation")
                  if e.type == "evaluation.model_revalidated"]
        assert events[-1].payload["score"] == pytest.approx(0.88)

    async def test_default_dsl_evaluator_structure_check(self, store) -> None:
        """默认 evaluator：DSL bundle 结构校验（损坏规则集→fail）。"""
        from vastacore.governance.drift import default_dsl_evaluator

        result = await default_dsl_evaluator(
            "model", "grid", "1.0.0", {"ruleset": RULESET})
        assert result["passed"] is True
        bad = await default_dsl_evaluator(
            "model", "grid", "1.0.0", {"ruleset": {"no_rules": 1}})
        assert bad["passed"] is False


class TestAffectedRuns:
    async def test_empty_when_no_consumption(self, store) -> None:
        assert affected_runs_of_model(store, "model", "grid") == []
