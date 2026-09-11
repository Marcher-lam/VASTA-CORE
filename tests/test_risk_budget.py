"""Story 11.8：组织级风险预算（FR-077，G3）。"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.agents.autonomy import AutonomyLevel
from vastacore.agents.risk_budget import (
    ExposureRecord,
    RiskBudget,
    configure_budget,
    enforce_budget,
    record_risk_exposure,
    trace_enforcement,
    validate_hierarchy,
)


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


def budget(scope="org:o1", **kw) -> RiskBudget:
    base = dict(scope=scope, risk_units=100.0, high_risk_ops=10)
    base.update(kw)
    return RiskBudget(**base)


def exposure(scope="org:o1", units=0.0, ops=0) -> ExposureRecord:
    return ExposureRecord(scope=scope, risk_units_used=units,
                          high_risk_ops_used=ops)


class TestHierarchy:
    def test_child_within_parent_ok(self) -> None:
        validate_hierarchy(budget("project:p1", risk_units=50,
                                  high_risk_ops=5), budget())

    def test_child_units_over_parent_rejected(self) -> None:
        with pytest.raises(VastaError) as e:
            validate_hierarchy(budget("project:p1", risk_units=200),
                               budget())
        assert e.value.code == "riskbudget.hierarchy_violation"

    def test_child_ops_over_parent_rejected(self) -> None:
        with pytest.raises(VastaError):
            validate_hierarchy(budget("project:p1", high_risk_ops=20),
                               budget())

    def test_child_ceiling_over_parent_rejected(self) -> None:
        parent = budget(autonomy_ceiling=AutonomyLevel.L2_ASSIST)
        with pytest.raises(VastaError):
            validate_hierarchy(
                budget("project:p1",
                       autonomy_ceiling=AutonomyLevel.L3_AUTONOMOUS),
                parent)


class TestExposure:
    async def test_high_risk_weighted(self, store) -> None:
        rec = exposure()
        rec = await record_risk_exposure(
            store, rec, risk_weight=2.5, is_high_risk=True,
            tenant_id="t", project_id="p")
        assert rec.risk_units_used == pytest.approx(2.5)
        assert rec.high_risk_ops_used == 1
        events = [e for e in store.iter_run_events(
            "risk-budgets", tenant_id="t", project_id="p")
            if e.type == "run.risk_exposure_recorded"]
        assert events[-1].payload["total_units"] == pytest.approx(2.5)

    async def test_low_risk_no_units(self, store) -> None:
        rec = await record_risk_exposure(
            store, exposure(), risk_weight=0.5, is_high_risk=False,
            tenant_id="t", project_id="p")
        assert rec.risk_units_used == 0.0
        assert rec.high_risk_ops_used == 0


class TestEnforcement:
    def test_within_budget_ceiling(self) -> None:
        allowed = enforce_budget(exposure(units=50, ops=5),
                                 budget(autonomy_ceiling=AutonomyLevel.L2_ASSIST))
        assert allowed is AutonomyLevel.L2_ASSIST

    def test_units_breach_demotes_l0(self) -> None:
        allowed = enforce_budget(exposure(units=100, ops=5), budget())
        assert allowed is AutonomyLevel.L0_OBSERVE

    def test_ops_breach_demotes_l0(self) -> None:
        allowed = enforce_budget(exposure(units=50, ops=10), budget())
        assert allowed is AutonomyLevel.L0_OBSERVE


class TestTrace:
    async def test_config_traced(self, store) -> None:
        await configure_budget(store, budget(), configured_by="cfo")
        events = [e for e in store.iter_run_events("risk-budgets")
                  if e.type == "run.risk_budget_configured"]
        assert events[-1].payload["risk_units"] == 100.0

    async def test_enforcement_traced_with_breach_flag(self, store) -> None:
        await trace_enforcement(
            store, exposure(units=100, ops=5), budget(),
            allowed=AutonomyLevel.L0_OBSERVE,
            tenant_id="t", project_id="p")
        events = [e for e in store.iter_run_events(
            "risk-budgets", tenant_id="t", project_id="p")
            if e.type == "run.risk_budget_enforced"]
        assert events[-1].payload["breached"] is True
        assert events[-1].payload["allowed_level"] == "L0"


class TestRiskBudgetReviewRegressions:
    """Epic 11 评审修复回归（盲审 M2、边界 R-1）。"""

    async def test_negative_risk_weight_rejected(self, store) -> None:
        """R-1：负权重洗白触顶敞口——拒。"""
        from vastacore.agents.risk_budget import ExposureRecord

        exposure = ExposureRecord(scope="agent:a",
                                  risk_units_used=100.0,
                                  high_risk_ops_used=100)
        with pytest.raises(VastaError) as e:
            await record_risk_exposure(
                store, exposure, risk_weight=-99.0, is_high_risk=True)
        assert e.value.code == "riskbudget.bad_weight"

    async def test_nan_risk_weight_rejected(self, store) -> None:
        """R-1：NaN 权重使预算闸永不触顶——拒。"""
        from vastacore.agents.risk_budget import ExposureRecord

        exposure = ExposureRecord(scope="agent:a", risk_units_used=0.0,
                                  high_risk_ops_used=0)
        with pytest.raises(VastaError):
            await record_risk_exposure(
                store, exposure, risk_weight=float("nan"),
                is_high_risk=True)

    def test_enforce_budget_nonfinite_fail_closed(self) -> None:
        """R-1：非有限敞口（万一入账）→ fail-closed 降 L0。"""
        from vastacore.agents.autonomy import AutonomyLevel
        from vastacore.agents.risk_budget import (
            ExposureRecord,
            RiskBudget,
            enforce_budget,
        )

        # model_construct 绕过校验构造毒记录（模拟历史脏账——
        # enforce 面对非有限值须自身 fail-closed）
        poisoned = ExposureRecord.model_construct(
            scope="agent:a", risk_units_used=float("nan"),
            high_risk_ops_used=0)
        budget = RiskBudget(scope="org:o", risk_units=100.0,
                            high_risk_ops=100)
        assert enforce_budget(poisoned, budget) \
            is AutonomyLevel.L0_OBSERVE
