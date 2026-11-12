"""Story 10.13：用量计费与成本优化（FR-078，G5）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vasta_storage import SqliteStorage
from vastacore.governance.billing import (
    BillingPeriod,
    generate_bill,
    optimization_advice,
)
from vastacore.governance.quotas import CostLedger, QuotaEnforcer, QuotaSpec

PERIOD = BillingPeriod(
    start=datetime(2026, 8, 1, tzinfo=UTC),
    end=datetime(2026, 9, 1, tzinfo=UTC))


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


async def record(store, model: str, cost: float, calls: int = 1,
                 basis: str = "usage", ts: datetime | None = None):
    await CostLedger.record(store, f"run-{model}-{cost}", tenant_id="t",
                            project_id="p", model=model, calls=calls,
                            estimated_cost=cost, basis=basis)
    if ts is not None:
        # 回拨该记录的事件 ts 到指定时刻（UPDATE events.data 里的 ts
        # 不可行——信封不可变。改为直接 UPDATE 流内 ts 列（测试调期）
        import json as _json

        with store._lock, store._conn:  # noqa: SLF001 ——测试调期
            row = store._conn.execute(  # noqa: SLF001
                "SELECT seq, data FROM events WHERE run_id='billing'"
                " ORDER BY seq DESC LIMIT 1").fetchone()
            payload = _json.loads(row[1])
            payload["ts"] = ts.isoformat()
            store._conn.execute(
                "UPDATE events SET data=?, ts=? WHERE run_id='billing'"
                " AND seq=?", (_json.dumps(payload, ensure_ascii=False),
                               ts.isoformat(), row[0]))


class TestBillingPeriod:
    def test_monthly_constructor(self) -> None:
        aug = BillingPeriod.monthly(2026, 8)
        assert aug.start == datetime(2026, 8, 1, tzinfo=UTC)
        assert aug.end == datetime(2026, 9, 1, tzinfo=UTC)
        dec = BillingPeriod.monthly(2026, 12)
        assert dec.end == datetime(2027, 1, 1, tzinfo=UTC)  # 跨年
        feb = BillingPeriod.monthly(2028, 2)
        assert feb.end == datetime(2028, 3, 1, tzinfo=UTC)  # 闰月 29 天


class TestGenerateBill:
    async def test_period_aggregation_with_lines(self, store) -> None:
        """账单分项：按模型聚合窗内记录（窗右开——月末衔接不重计）。"""
        await record(store, "grid", 0.30, calls=3, ts=datetime(
            2026, 8, 15, tzinfo=UTC))
        await record(store, "grid", 0.10, calls=1, ts=datetime(
            2026, 8, 20, tzinfo=UTC))
        await record(store, "other", 0.05, ts=datetime(
            2026, 8, 25, tzinfo=UTC))
        await record(store, "sept", 9.0, ts=datetime(  # 窗外（9 月）
            2026, 9, 2, tzinfo=UTC))
        bill = await generate_bill(store, PERIOD, tenant_id="t",
                                   project_id="p")
        assert bill.total == pytest.approx(0.45)
        assert [ln.model for ln in bill.lines] == ["grid", "other"]
        grid = bill.lines[0]
        assert grid.calls == 4 and grid.amount == pytest.approx(0.40)
        assert bill.bill_version == 1

    async def test_bill_immutable_regen_versions(self, store) -> None:
        """AC：账单不可变——同周期再生成 = 新版本（事件流追加不覆盖，
        重放取最新，旧版本审计可溯）。"""
        await record(store, "m", 0.5, ts=datetime(2026, 8, 10,
                                                  tzinfo=UTC))
        b1 = await generate_bill(store, PERIOD, tenant_id="t",
                                 project_id="p")
        await record(store, "m2", 0.2, ts=datetime(2026, 8, 11,
                                                   tzinfo=UTC))
        b2 = await generate_bill(store, PERIOD, tenant_id="t",
                                 project_id="p")
        assert b1.bill_version == 1
        assert b2.bill_version == 2
        assert b2.total > b1.total
        events = [e for e in store.iter_run_events("billing")
                  if e.type == "run.bill_generated"]
        versions = [e.payload["bill_version"] for e in events]
        assert versions == [1, 2]  # 旧版本在流——审计可溯

    async def test_bill_event_traced(self, store) -> None:
        """AC：账单留痕（billing 流周期闭合事件）。"""
        await record(store, "m", 0.1, ts=datetime(2026, 8, 1, 5,
                                                  tzinfo=UTC))
        bill = await generate_bill(store, PERIOD, tenant_id="t",
                                   project_id="p")
        events = [e for e in store.iter_run_events("billing")
                  if e.type == "run.bill_generated"]
        assert events[-1].payload["bill_id"] == bill.bill_id
        assert events[-1].payload["period_label"] == PERIOD.label()

    async def test_mixed_basis_annotated(self, store) -> None:
        await record(store, "a", 0.1, basis="usage", ts=datetime(
            2026, 8, 2, tzinfo=UTC))
        await record(store, "b", 0.2, basis="chars-estimated",
                     ts=datetime(2026, 8, 3, tzinfo=UTC))
        bill = await generate_bill(store, PERIOD, tenant_id="t",
                                   project_id="p")
        assert bill.basis == "mixed"
        by_model = {ln.model: ln.basis for ln in bill.lines}
        assert by_model == {"a": "usage", "b": "chars-estimated"}


class TestOptimizationAdvice:
    async def test_top_cost_candidate(self, store) -> None:
        await record(store, "expensive", 0.90, ts=datetime(
            2026, 8, 5, tzinfo=UTC))
        await record(store, "cheap", 0.05, ts=datetime(
            2026, 8, 6, tzinfo=UTC))
        report = await optimization_advice(store, PERIOD, tenant_id="t",
                                           project_id="p")
        assert report.total == pytest.approx(0.95)
        kinds = [a.kind for a in report.advice]
        assert "top-cost-candidate" in kinds
        top = [a for a in report.advice
               if a.kind == "top-cost-candidate"][0]
        assert "expensive" in top.detail

    async def test_estimation_heavy(self, store) -> None:
        await record(store, "a", 0.6, basis="chars-estimated",
                     ts=datetime(2026, 8, 7, tzinfo=UTC))
        await record(store, "b", 0.2, basis="usage", ts=datetime(
            2026, 8, 8, tzinfo=UTC))
        report = await optimization_advice(store, PERIOD, tenant_id="t",
                                           project_id="p")
        assert any(a.kind == "estimation-heavy" for a in report.advice)

    async def test_budget_pressure(self, store) -> None:
        enforcer = QuotaEnforcer(store)
        await enforcer.configure("t", "p", QuotaSpec(budget_total=1.0))
        await record(store, "m", 0.85, ts=datetime(2026, 8, 9,
                                                   tzinfo=UTC))
        report = await optimization_advice(store, PERIOD, tenant_id="t",
                                           project_id="p",
                                           budget_total=1.0)
        assert report.utilization == pytest.approx(0.85)
        assert any(a.kind == "budget-pressure" for a in report.advice)

    async def test_no_advice_when_healthy(self, store) -> None:
        # 三模型均衡（34/33/33%——均低于 40% 主导线）+ 全 usage 口径
        await record(store, "a", 0.34, basis="usage", ts=datetime(
            2026, 8, 10, tzinfo=UTC))
        await record(store, "b", 0.33, basis="usage", ts=datetime(
            2026, 8, 11, tzinfo=UTC))
        await record(store, "c", 0.33, basis="usage", ts=datetime(
            2026, 8, 12, tzinfo=UTC))
        report = await optimization_advice(store, PERIOD, tenant_id="t",
                                           project_id="p")
        assert report.advice == []
        assert report.utilization is None  # 无预算配置
