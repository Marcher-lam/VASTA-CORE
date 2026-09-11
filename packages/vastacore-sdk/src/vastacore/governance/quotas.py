"""配额、速率与成本归集（Story 9.8，FR-072/NFR-015，G4）。

- 租户/项目级配额（QuotaSpec）：速率（滑窗 requests/min）、并发上限、
  累计成本预算——配置经 ``run.quota_configured`` 事件留痕；
- 限流（QuotaEnforcer）：超速率/并发/预算即拒（QuotaExceededError——
  retryable=True + retry_after_s，429 语义），每次拒绝落 ``run.throttled``
  事件（reason=rate|concurrency|budget）；
- 成本归集（CostLedger）：``run.cost_recorded`` 事件为唯一真相源，
  Run→项目→租户三级汇总（NFR-015 全档接线——epic8 defer #1 解除：
  路由器实例级 cost_summary 经 ``ingest_router`` 并入台账）；
- 事件族：run（AD-5 13 族封闭集内）；系统流 "quotas"（配置/拒绝）与
  "billing"（成本记录）；
- 进程内限流态（滑窗/并发计数）为单实例假设（与 8.6 熔断同口径——
  多实例部署属 G4 服务化范围）；成本台账跨会话可查（事件流重放）。
"""

from __future__ import annotations

import contextlib
from collections import deque
from collections.abc import AsyncIterator, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

_QUOTAS_RUN = "quotas"
_BILLING_RUN = "billing"


class QuotaSpec(BaseModel):
    """作用域配额（任一项 None = 该维度不限）。"""

    model_config = ConfigDict(extra="forbid")

    requests_per_min: int | None = Field(default=None, ge=1)
    max_concurrent: int | None = Field(default=None, ge=1)
    budget_total: float | None = Field(default=None, ge=0)


class QuotaExceededError(VastaError):
    """限流拒绝（429 语义——retryable + retry_after_s）。"""

    def __init__(self, code: str, message: str, *,
                 retry_after_s: float = 0.0) -> None:
        super().__init__(code=code, message=message, retryable=True)
        self.retry_after_s = retry_after_s


class QuotaEnforcer:
    """速率/并发/预算三闸（租户:项目作用域；未配置=该维度放行）。

    时钟可注入（滑窗测试确定性——AD-15 合成钟惯例）。"""

    def __init__(
        self, store: Any = None,
        *, clock: Callable[[], float] | None = None,
    ) -> None:
        import time

        self._store = store
        self._clock = clock or time.monotonic
        self._specs: dict[tuple[str, str], QuotaSpec] = {}
        self._windows: dict[tuple[str, str], deque[float]] = {}
        self._inflight: dict[tuple[str, str], int] = {}

    # ---- 配置 ----
    async def configure(
        self, tenant_id: str, project_id: str, spec: QuotaSpec,
    ) -> None:
        """配额配置（覆盖式）+ 留痕（run.quota_configured）。"""
        self._specs[(tenant_id, project_id)] = spec
        if self._store is not None:
            sequencer = EventSequencer(
                self._store, _QUOTAS_RUN,
                tenant_id=tenant_id, project_id=project_id,
            )
            await sequencer.emit("run.quota_configured", {
                "tenant_id": tenant_id, "project_id": project_id,
                **spec.model_dump(),
            })

    def spec_of(self, tenant_id: str, project_id: str) -> QuotaSpec | None:
        return self._specs.get((tenant_id, project_id))

    # ---- 速率（滑动窗口）----
    async def check_rate(self, tenant_id: str, project_id: str) -> None:
        """速率闸：窗口内请求数超限即拒（+留痕 run.throttled）。"""
        spec = self._specs.get((tenant_id, project_id))
        if spec is None or spec.requests_per_min is None:
            return
        key = (tenant_id, project_id)
        now = self._clock()
        window = self._windows.setdefault(key, deque())
        while window and now - window[0] >= 60.0:
            window.popleft()  # 滑出窗口
        if len(window) >= spec.requests_per_min:
            retry_after = max(0.0, 60.0 - (now - window[0]))
            await self._throttled(
                tenant_id, project_id, "rate",
                message=(f"速率超限：{len(window)}/{spec.requests_per_min}"
                         f" req/min（{retry_after:.0f}s 后重试）"),
                retry_after_s=retry_after,
            )
        window.append(now)

    # ---- 并发 ----
    @contextlib.asynccontextmanager
    async def concurrency_scope(
        self, tenant_id: str, project_id: str,
    ) -> AsyncIterator[None]:
        """并发闸：超限即拒（run.throttled + quota.concurrent_limit）；
        块内异常也归还槽位（不留泄漏）。"""
        spec = self._specs.get((tenant_id, project_id))
        key = (tenant_id, project_id)
        if spec is not None and spec.max_concurrent is not None \
                and self._inflight.get(key, 0) >= spec.max_concurrent:
            await self._throttled(
                tenant_id, project_id, "concurrency",
                message=(f"并发超限：{self._inflight.get(key, 0)}/"
                         f"{spec.max_concurrent} in-flight"),
            )
        self._inflight[key] = self._inflight.get(key, 0) + 1
        try:
            yield
        finally:
            self._inflight[key] = max(0, self._inflight.get(key, 0) - 1)

    # ---- 预算 ----
    async def check_budget(self, tenant_id: str, project_id: str) -> None:
        """预算闸：作用域累计成本（CostLedger 台账）达 budget_total 即拒。"""
        spec = self._specs.get((tenant_id, project_id))
        if spec is None or spec.budget_total is None or self._store is None:
            return
        total = await CostLedger.project_total(
            self._store, tenant_id=tenant_id, project_id=project_id)
        if total >= spec.budget_total:
            await self._throttled(
                tenant_id, project_id, "budget",
                message=(f"预算耗尽：累计 {total:.4f} / 上限 "
                         f"{spec.budget_total:.4f}（成本台账 billing 流）"),
            )

    # ---- 内部 ----
    async def _throttled(
        self, tenant_id: str, project_id: str, reason: str, *,
        message: str, retry_after_s: float = 0.0,
    ) -> None:
        """拒绝 + 留痕（留痕失败不掩盖拒绝本体——router 同策略）。"""
        code = {
            "rate": "quota.rate_limited",
            "concurrency": "quota.concurrent_limit",
            "budget": "quota.budget_exceeded",
        }[reason]
        if self._store is not None:
            with contextlib.suppress(Exception):
                sequencer = EventSequencer(
                    self._store, _QUOTAS_RUN,
                    tenant_id=tenant_id, project_id=project_id,
                )
                await sequencer.emit("run.throttled", {
                    "tenant_id": tenant_id, "project_id": project_id,
                    "reason": reason,
                })
        raise QuotaExceededError(code, message,
                                 retry_after_s=retry_after_s)


class CostLedger:
    """成本归集台账（run.cost_recorded 事件为唯一真相源——
    记录面与查询面均走事件流，跨会话可查、零内存态）。"""

    @staticmethod
    async def record(
        store: Any, run_id: str, *,
        tenant_id: str, project_id: str,
        model: str, calls: int = 1, estimated_cost: float = 0.0,
        basis: str = "",
    ) -> None:
        """记一笔成本（模型粒度；估算口径 basis 透传——NFR-015）。"""
        import math

        cost = float(estimated_cost)
        if not math.isfinite(cost) or cost < 0:
            # 评审修复 F4/F13：NaN/inf 经 JSON 落 null 毒化全部汇总
            # （append-only 不可修复）；负成本可"充值"预算——一律拒
            raise VastaError(
                code="billing.bad_cost",
                message=(f"estimated_cost 须为非负有限数"
                         f"（得到 {estimated_cost!r}——退款请显式建模）"),
            )
        sequencer = EventSequencer(
            store, _BILLING_RUN,
            tenant_id=tenant_id, project_id=project_id,
        )
        await sequencer.emit("run.cost_recorded", {
            "run_id": run_id, "model": model, "calls": calls,
            "estimated_cost": round(cost, 10),
            "basis": basis,
        })

    @staticmethod
    async def ingest_router(
        store: Any, router: Any, run_id: str, *,
        tenant_id: str, project_id: str,
    ) -> int:
        """路由器 cost_summary 并入台账（AC：Router cost_summary 并入
        归集——epic8 defer #1 解除）。返回并入条数。"""
        entries: int = 0
        for model, entry in router.cost_summary().items():
            await CostLedger.record(
                store, run_id, tenant_id=tenant_id, project_id=project_id,
                model=model, calls=entry.get("calls", 0),
                estimated_cost=entry.get("estimated_cost", 0.0),
                basis=entry.get("basis", ""),
            )
            entries += 1
        return entries

    # ---- 查询面（事件流重放）----
    @staticmethod
    def _rows(store: Any, *, tenant_id: str | None = None,
              project_id: str | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for event in store.iter_run_events(
                _BILLING_RUN, tenant_id=tenant_id,
                project_id=project_id):
            if event.type != "run.cost_recorded":
                continue
            p = event.payload
            rows.append({
                "run_id": p["run_id"], "model": p["model"],
                "calls": p.get("calls", 0),
                "estimated_cost": p.get("estimated_cost", 0.0),
                "basis": p.get("basis", ""),
                "ts": event.ts.isoformat(),  # 10.13：周期窗过滤
            })
        return rows

    @staticmethod
    async def run_total(
        store: Any, run_id: str, *,
        tenant_id: str, project_id: str,
    ) -> float:
        """单 Run 成本总计。"""
        return sum(r["estimated_cost"] for r in CostLedger._rows(
            store, tenant_id=tenant_id, project_id=project_id)
            if r["run_id"] == run_id and r["estimated_cost"] is not None)

    @staticmethod
    async def project_total(
        store: Any, *, tenant_id: str, project_id: str,
    ) -> float:
        """项目（作用域）累计成本——预算闸的判定口径。"""
        return sum(r["estimated_cost"] for r in CostLedger._rows(
            store, tenant_id=tenant_id, project_id=project_id)
            if r["estimated_cost"] is not None)

    @staticmethod
    async def project_summary(
        store: Any, *, tenant_id: str, project_id: str,
    ) -> dict[str, Any]:
        """项目级汇总：按 Run 分组 + 模型分项 + 总计（NFR-015 项目档）。"""
        rows = CostLedger._rows(store, tenant_id=tenant_id,
                                project_id=project_id)
        by_run: dict[str, dict[str, Any]] = {}
        for r in rows:
            entry = by_run.setdefault(
                r["run_id"], {"total": 0.0, "models": {}})
            if r["estimated_cost"] is not None:  # 毒化行（历史）不崩汇总
                entry["total"] += r["estimated_cost"]
            model = entry["models"].setdefault(
                r["model"], {"calls": 0, "estimated_cost": 0.0,
                             "basis": r["basis"]})
            model["calls"] += r["calls"]
            model["estimated_cost"] += r["estimated_cost"]
            if model["basis"] != r["basis"]:
                model["basis"] = "mixed"
        return {"runs": by_run,
                "total": sum(e["total"] for e in by_run.values())}

    @staticmethod
    async def tenant_summary(
        store: Any, *, tenant_id: str,
    ) -> dict[str, Any]:
        """租户级汇总：跨项目（NFR-015 租户档——run→项目→租户三级）。
        项目归属按事件 envelope 作用域分组（作用域是真相源；
        租户级查询不带 project 过滤——iter 全流后按信封过滤）。"""
        by_project: dict[str, float] = {}
        for event in store.iter_run_events(_BILLING_RUN):
            if event.type != "run.cost_recorded" \
                    or event.tenant_id != tenant_id:
                continue
            cost = event.payload.get("estimated_cost")
            if cost is not None:  # 毒化行（历史）不崩汇总
                by_project[event.project_id] = (
                    by_project.get(event.project_id, 0.0) + cost)
        return {"projects": by_project,
                "total": sum(by_project.values())}


__all__ = ["CostLedger", "QuotaEnforcer", "QuotaExceededError",
           "QuotaSpec"]
