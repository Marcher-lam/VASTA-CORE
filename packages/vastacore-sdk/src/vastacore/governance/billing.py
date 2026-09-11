"""用量计费与成本优化（Story 10.13，FR-078，G5）。

用量可计费、成本可归因可优化：

- **BillingPeriod**：计费周期（月度构造器 / 自定义窗）；
- **generate_bill**：CostLedger（9.8）周期聚合 → **Bill**（按模型
  分项 + 总计 + basis 口径延续 + 调用数）→ ``run.bill_generated``
  留痕（billing 流周期闭合事件）；
- **账单不可变**：同周期再生成 = **新版本**（bill_version 递增，
  事件流追加不覆盖——重放取最新版本；旧版本审计可溯）；
- **optimization_advice**：预算使用率（接 9.8 QuotaEnforcer 配置
  的 budget_total）+ 成本结构建议——最高成本模型候选（替换/降级
  评估）、低效路由信号（basis=chars-estimated 占比高——未用 usage
  计量的调用多）、预算余量预警。
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.sequencer import EventSequencer

_BILLING_RUN = "billing"


class BillingPeriod(BaseModel):
    """计费周期（闭区间）。"""

    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime

    @classmethod
    def monthly(cls, year: int, month: int) -> BillingPeriod:
        """自然月周期（UTC——2 月等月长自动正确）。"""
        start = datetime(year, month, 1, tzinfo=UTC)
        end_month = month % 12 + 1
        end_year = year + (1 if month == 12 else 0)
        end = datetime(end_year, end_month, 1, tzinfo=UTC)
        return cls(start=start, end=end)

    def label(self) -> str:
        return f"{self.start.strftime('%Y%m%d')}-{self.end.strftime('%Y%m%d')}"


class BillLine(BaseModel):
    """账单分项（按模型）。"""

    model_config = ConfigDict(extra="forbid")

    model: str
    calls: int = Field(ge=0)
    amount: float = Field(ge=0.0)
    basis: str = Field(default="", description="口径延续（usage/"
                                               "chars-estimated/mixed）")


class Bill(BaseModel):
    """账单（不可变——再生成即新版本）。"""

    model_config = ConfigDict(extra="forbid")

    bill_id: str
    period_start: datetime
    period_end: datetime
    tenant_id: str
    project_id: str
    bill_version: int = Field(ge=1, description="同周期再生成递增——"
                                                "旧版本审计可溯")
    lines: list[BillLine] = Field(default_factory=list)
    total: float = Field(default=0.0, ge=0.0)
    basis: str = Field(default="", description="混合口径标注")


def _bill_versions(
    store: Any, period: BillingPeriod, *,
    tenant_id: str, project_id: str,
) -> int:
    """该周期已生成的最高账单版本（重放 billing 流）。"""
    label = period.label()
    highest = 0
    for event in store.iter_run_events(
            _BILLING_RUN, tenant_id=tenant_id, project_id=project_id):
        if event.type != "run.bill_generated":
            continue
        if event.payload.get("period_label") != label:
            continue
        highest = max(highest, int(event.payload.get("bill_version", 0)))
    return highest


async def generate_bill(
    store: Any, period: BillingPeriod, *,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> Bill:
    """生成账单（周期聚合 + 留痕 + 版本递增——不可变）。

    窗过滤：事件 ts ∈ [start, end)（右开——月度衔接不重计）。"""
    from .quotas import CostLedger

    versions = _bill_versions(store, period, tenant_id=tenant_id,
                              project_id=project_id)
    by_model: dict[str, dict[str, float]] = {}
    for row in CostLedger._rows(store, tenant_id=tenant_id,  # noqa: SLF001
                                project_id=project_id):
        raw_ts = row.get("ts", "")
        try:
            ts = datetime.fromisoformat(raw_ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
        except ValueError:
            continue  # 无时间戳的记录不进周期
        if not (period.start <= ts < period.end):
            continue
        entry = by_model.setdefault(
            row["model"], {"calls": 0.0, "amount": 0.0, "bases": set()})
        cost = row.get("estimated_cost")
        if cost is None:
            continue
        entry["calls"] += row.get("calls", 0)
        entry["amount"] += cost
        if row.get("basis"):
            entry["bases"].add(row["basis"])

    lines = [BillLine(
        model=model, calls=int(v["calls"]), amount=round(v["amount"], 10),
        basis="/".join(sorted(v["bases"])) or "")
        for model, v in sorted(by_model.items())]
    bases = {ln.basis for ln in lines if ln.basis}
    overall_basis = next(iter(bases)) if len(bases) == 1 else (
        "mixed" if len(bases) > 1 else "")
    bill = Bill(
        bill_id=f"bill-{period.label()}-{tenant_id}-{project_id}",
        period_start=period.start, period_end=period.end,
        tenant_id=tenant_id, project_id=project_id,
        bill_version=versions + 1, lines=lines,
        total=round(sum(ln.amount for ln in lines), 10),
        basis=overall_basis)
    sequencer = EventSequencer(
        store, _BILLING_RUN, tenant_id=tenant_id, project_id=project_id)
    await sequencer.emit("run.bill_generated", {
        "bill_id": bill.bill_id, "bill_version": bill.bill_version,
        "period_label": period.label(),
        "period_start": period.start.isoformat(),
        "period_end": period.end.isoformat(),
        "total": bill.total, "lines": [ln.model_dump(mode="json")
                                        for ln in bill.lines],
    })
    return bill


class AdviceItem(BaseModel):
    """优化建议项。"""

    model_config = ConfigDict(extra="forbid")

    kind: str  # top-cost-candidate | estimation-heavy | budget-pressure
    detail: str


class OptimizationReport(BaseModel):
    """成本优化报告（只读）。"""

    model_config = ConfigDict(extra="forbid")

    period: str
    total: float = Field(ge=0.0)
    budget_total: float | None = None
    utilization: float | None = Field(
        default=None, ge=0.0, description="预算使用率（无预算=None）")
    advice: list[AdviceItem] = Field(default_factory=list)


async def optimization_advice(
    store: Any, period: BillingPeriod, *,
    tenant_id: str = "t-default", project_id: str = "p-default",
    budget_total: float | None = None,
) -> OptimizationReport:
    """成本优化建议（router 成本面复用）：

    - top-cost-candidate：最高成本模型（≥总额 40% 且有替代空间）；
    - estimation-heavy：chars-estimated 口径占比高（usage 计量缺失
      ——精度可改善）；
    - budget-pressure：预算使用率 ≥ 80%（接 9.8 budget_total 配置）。"""
    from .quotas import CostLedger

    bill = await generate_bill.__wrapped__(store, period) \
        if False else None  # 占位防误用——真实实现见下
    # 重新聚合（不落新账单版本——advice 是只读报告）
    by_model: dict[str, dict[str, float]] = {}
    for row in CostLedger._rows(store, tenant_id=tenant_id,  # noqa: SLF001
                                project_id=project_id):
        raw_ts = row.get("ts", "")
        try:
            ts = datetime.fromisoformat(raw_ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
        except ValueError:
            continue  # 无时间戳的记录不进周期
        if not (period.start <= ts < period.end):
            continue
        entry = by_model.setdefault(row["model"],
                                    {"amount": 0.0, "est": 0.0})
        cost = row.get("estimated_cost")
        if cost is None:
            continue
        entry["amount"] += cost
        if row.get("basis") == "chars-estimated":
            entry["est"] += cost
    total = round(sum(v["amount"] for v in by_model.values()), 10)

    advice: list[AdviceItem] = []
    if by_model:
        top_model, top = max(by_model.items(), key=lambda kv: kv[1]["amount"])
        if total > 0 and top["amount"] / total >= 0.4 and len(by_model) > 1:
            advice.append(AdviceItem(
                kind="top-cost-candidate",
                detail=(f"模型 {top_model} 占周期成本 "
                        f"{top['amount'] / total:.0%}"
                        f"（{top['amount']:.4f}/{total:.4f}）——评估"
                        "替代或降级（router 价格面排序候选）")))
    est_total = sum(v["est"] for v in by_model.values())
    if total > 0 and est_total / total >= 0.5:
        advice.append(AdviceItem(
            kind="estimation-heavy",
            detail=(f"chars-estimated 口径占 {est_total / total:.0%}"
                    "——usage 计量接入可改善成本精度"
                    "（router usage 透传）")))
    if budget_total is not None:
        utilization = round(total / budget_total, 4) if budget_total else 0.0
        if utilization >= 0.8:
            advice.append(AdviceItem(
                kind="budget-pressure",
                detail=f"预算使用率 {utilization:.0%}"
                       f"（{total:.4f}/{budget_total:.4f}）——接近触顶，"
                       "限流将启用（9.8 budget 闸）"))
    else:
        utilization = None

    return OptimizationReport(
        period=period.label(), total=total,
        budget_total=budget_total, utilization=utilization,
        advice=advice)


__all__ = ["AdviceItem", "Bill", "BillLine", "BillingPeriod",
           "OptimizationReport", "generate_bill", "optimization_advice"]
