"""Story 9.8：配额、速率与成本归集（FR-072/NFR-015，G4）。

速率/并发/预算三闸 + 429 语义留痕；Router cost_summary 并入台账；
Run→项目→租户三级汇总（epic8 defer #1 解除）。
"""

from __future__ import annotations

import pytest

from vasta_protocols.protocols import (
    ModelAdapter,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
)
from vasta_storage import SqliteStorage
from vastacore.governance.quotas import (
    CostLedger,
    QuotaEnforcer,
    QuotaExceededError,
    QuotaSpec,
)
from vastacore.models.router import ModelRouter


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


class FakeClock:
    """可推进的单调钟（滑窗测试确定性——AD-15）。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class UsageModel(ModelAdapter):
    """带 usage 的假适配器（8.6 成本口径——usage tokens）。"""

    protocol_version = "0.1.0"
    capabilities = ModelCapabilities(structured_output=True)

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            content="ok",
            detail={"usage": {"total_tokens": 1000}},
        )


class TestQuotaSpec:
    def test_negative_and_zero_rejected(self) -> None:
        """spec 校验：速率/并发/预算负值与零速率拒（构造期）。"""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            QuotaSpec(requests_per_min=0)
        with pytest.raises(ValidationError):
            QuotaSpec(max_concurrent=-1)
        with pytest.raises(ValidationError):
            QuotaSpec(budget_total=-0.5)

    def test_none_means_unlimited(self) -> None:
        spec = QuotaSpec()
        assert spec.requests_per_min is None
        assert spec.max_concurrent is None
        assert spec.budget_total is None
        # budget_total=0 合法（零预算=全拒）
        assert QuotaSpec(budget_total=0).budget_total == 0


class TestQuotaConfig:
    async def test_configure_leaves_trace(self, store) -> None:
        """AC：配置租户/项目配额 → run.quota_configured 留痕。"""
        enforcer = QuotaEnforcer(store)
        await enforcer.configure("t-1", "p-1", QuotaSpec(requests_per_min=60,
                                                         max_concurrent=5))
        events = [e for e in store.iter_run_events("quotas")
                  if e.type == "run.quota_configured"]
        assert len(events) == 1
        assert events[0].payload["requests_per_min"] == 60
        assert events[0].payload["max_concurrent"] == 5
        assert enforcer.spec_of("t-1", "p-1") is not None

    async def test_reconfigure_overrides(self, store) -> None:
        enforcer = QuotaEnforcer(store)
        await enforcer.configure("t-1", "p-1", QuotaSpec(requests_per_min=10))
        await enforcer.configure("t-1", "p-1", QuotaSpec(requests_per_min=99))
        assert enforcer.spec_of("t-1", "p-1").requests_per_min == 99


class TestRateLimit:
    async def test_over_rate_throttled_429_semantics(self, store) -> None:
        """AC：超速率被限流——quota.rate_limited（retryable+retry_after，
        429 语义）+ run.throttled 留痕。"""
        clock = FakeClock()
        enforcer = QuotaEnforcer(store, clock=clock)
        await enforcer.configure("t-1", "p-1", QuotaSpec(requests_per_min=3))
        for _ in range(3):
            await enforcer.check_rate("t-1", "p-1")
        with pytest.raises(QuotaExceededError) as excinfo:
            await enforcer.check_rate("t-1", "p-1")
        assert excinfo.value.code == "quota.rate_limited"
        assert excinfo.value.retryable is True  # 429 语义
        assert excinfo.value.retry_after_s > 0
        throttled = [e for e in store.iter_run_events("quotas")
                     if e.type == "run.throttled"]
        assert len(throttled) == 1
        assert throttled[0].payload["reason"] == "rate"

    async def test_window_slides_open_again(self, store) -> None:
        """滑窗：60s 后旧请求滑出窗口 → 放行。"""
        clock = FakeClock()
        enforcer = QuotaEnforcer(store, clock=clock)
        await enforcer.configure("t-1", "p-1", QuotaSpec(requests_per_min=2))
        await enforcer.check_rate("t-1", "p-1")
        await enforcer.check_rate("t-1", "p-1")
        with pytest.raises(QuotaExceededError):
            await enforcer.check_rate("t-1", "p-1")
        clock.advance(61.0)  # 窗口滑出
        await enforcer.check_rate("t-1", "p-1")  # 不再拒

    async def test_unconfigured_scope_passes(self) -> None:
        """未配置作用域：无闸（无事件可留——纯内存路径直通）。"""
        enforcer = QuotaEnforcer()
        for _ in range(100):
            await enforcer.check_rate("t-x", "p-x")


class TestConcurrency:
    async def test_concurrency_limit_enforced(self, store) -> None:
        """AC：超并发被限流——quota.concurrent_limit + 留痕。"""
        enforcer = QuotaEnforcer(store)
        await enforcer.configure("t-1", "p-1", QuotaSpec(max_concurrent=2))
        async with (enforcer.concurrency_scope("t-1", "p-1"),
                    enforcer.concurrency_scope("t-1", "p-1")):
            with pytest.raises(QuotaExceededError) as excinfo:
                async with enforcer.concurrency_scope("t-1", "p-1"):
                    pass
            assert excinfo.value.code == "quota.concurrent_limit"
        throttled = [e for e in store.iter_run_events("quotas")
                     if e.type == "run.throttled"]
        assert any(t.payload["reason"] == "concurrency" for t in throttled)

    async def test_slot_released_after_scope(self, store) -> None:
        """槽位归还：作用域退出后可再进入。"""
        enforcer = QuotaEnforcer(store)
        await enforcer.configure("t-1", "p-1", QuotaSpec(max_concurrent=1))
        async with enforcer.concurrency_scope("t-1", "p-1"):
            pass
        async with enforcer.concurrency_scope("t-1", "p-1"):  # 槽位已归还
            pass

    async def test_slot_released_on_exception(self, store) -> None:
        """块内异常也归还槽位（不留泄漏）。"""
        enforcer = QuotaEnforcer(store)
        await enforcer.configure("t-1", "p-1", QuotaSpec(max_concurrent=1))
        with pytest.raises(RuntimeError):
            async with enforcer.concurrency_scope("t-1", "p-1"):
                raise RuntimeError("boom")
        async with enforcer.concurrency_scope("t-1", "p-1"):  # 归还后可进
            pass


class TestCostLedger:
    async def test_record_and_run_total(self, store) -> None:
        """AC：成本记录落 run.cost_recorded；Run 级汇总。"""
        await CostLedger.record(store, "run-1", tenant_id="t-1",
                                project_id="p-1", model="fake-1",
                                calls=2, estimated_cost=0.02, basis="usage")
        await CostLedger.record(store, "run-1", tenant_id="t-1",
                                project_id="p-1", model="fake-2",
                                calls=1, estimated_cost=0.01,
                                basis="chars-estimated")
        events = [e for e in store.iter_run_events(
            "billing", tenant_id="t-1", project_id="p-1")
            if e.type == "run.cost_recorded"]
        assert len(events) == 2
        total = await CostLedger.run_total(store, "run-1", tenant_id="t-1",
                                           project_id="p-1")
        assert total == pytest.approx(0.03)

    async def test_router_cost_summary_ingested(self, store) -> None:
        """AC：Router cost_summary 并入归集（epic8 defer #1 解除——
        8.6 实例级成本进入三级台账）。"""
        router = ModelRouter(
            {"fake-1": (UsageModel(), 0.01)},
            capability_views={"fake-1": UsageModel.capabilities},
        )
        await router.generate(ModelRequest(prompt="hi"))
        await router.generate(ModelRequest(prompt="again"))
        entries = await CostLedger.ingest_router(
            store, router, "run-42", tenant_id="t-1", project_id="p-1")
        assert entries == 1  # 一个模型一条
        summary = await CostLedger.project_summary(store, tenant_id="t-1",
                                                   project_id="p-1")
        assert summary["runs"]["run-42"]["models"]["fake-1"]["calls"] == 2
        # usage 口径：2 次 × 1000 tokens × $0.01/1k = $0.02
        assert summary["runs"]["run-42"]["models"]["fake-1"][
            "estimated_cost"] == pytest.approx(0.02)
        assert summary["runs"]["run-42"]["models"]["fake-1"]["basis"] == "usage"

    async def test_three_level_rollup(self, store) -> None:
        """AC：run→项目→租户三级汇总（NFR-015 全档）。"""
        for run, project, cost in (("r1", "p-1", 0.1), ("r2", "p-1", 0.2),
                                   ("r3", "p-2", 0.4)):
            await CostLedger.record(store, run, tenant_id="t-1",
                                    project_id=project, model="fake-1",
                                    calls=1, estimated_cost=cost,
                                    basis="usage")
        proj1 = await CostLedger.project_summary(store, tenant_id="t-1",
                                                 project_id="p-1")
        assert proj1["total"] == pytest.approx(0.3)
        assert set(proj1["runs"]) == {"r1", "r2"}  # Run 级分组
        tenant = await CostLedger.tenant_summary(store, tenant_id="t-1")
        assert tenant["projects"]["p-1"] == pytest.approx(0.3)
        assert tenant["projects"]["p-2"] == pytest.approx(0.4)
        assert tenant["total"] == pytest.approx(0.7)  # 租户档总计

    async def test_tenant_isolation(self, store) -> None:
        """租户隔离：t-2 的台账不进 t-1 汇总（作用域 fail-closed）。"""
        await CostLedger.record(store, "r1", tenant_id="t-1",
                                project_id="p-1", model="m",
                                estimated_cost=1.0, basis="usage")
        await CostLedger.record(store, "r2", tenant_id="t-2",
                                project_id="p-1", model="m",
                                estimated_cost=99.0, basis="usage")
        tenant1 = await CostLedger.tenant_summary(store, tenant_id="t-1")
        assert tenant1["total"] == pytest.approx(1.0)


class TestBudgetQuota:
    async def test_budget_exhaustion_throttles(self, store) -> None:
        """预算闸：作用域累计成本达 budget_total → quota.budget_exceeded
        + run.throttled(reason=budget)。"""
        enforcer = QuotaEnforcer(store)
        await enforcer.configure("t-1", "p-1", QuotaSpec(budget_total=0.5))
        await CostLedger.record(store, "r1", tenant_id="t-1",
                                project_id="p-1", model="m",
                                estimated_cost=0.6, basis="usage")
        with pytest.raises(QuotaExceededError) as excinfo:
            await enforcer.check_budget("t-1", "p-1")
        assert excinfo.value.code == "quota.budget_exceeded"
        throttled = [e for e in store.iter_run_events("quotas")
                     if e.type == "run.throttled"]
        assert any(t.payload["reason"] == "budget" for t in throttled)

    async def test_budget_zero_rejects_immediately(self, store) -> None:
        """零预算：任何已记成本（含 0）即拒（budget_total=0 语义）。"""
        enforcer = QuotaEnforcer(store)
        await enforcer.configure("t-1", "p-1", QuotaSpec(budget_total=0))
        with pytest.raises(QuotaExceededError):
            await enforcer.check_budget("t-1", "p-1")

    async def test_budget_cross_project_not_overcounted(self, store) -> None:
        """预算按作用域计：p-2 的成本不挤占 p-1 的预算。"""
        enforcer = QuotaEnforcer(store)
        await enforcer.configure("t-1", "p-1", QuotaSpec(budget_total=1.0))
        await CostLedger.record(store, "r9", tenant_id="t-1",
                                project_id="p-2", model="m",
                                estimated_cost=500.0, basis="usage")
        await enforcer.check_budget("t-1", "p-1")  # p-1 未记 → 放行
