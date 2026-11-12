"""模型漂移检测与影响告警（Story 10.4，FR-067 + FR-049 部分，G1）。

世界变了，模型结论的可信度跟着变、有人被通知：

- **漂移指标**（DriftMetrics）：性能衰减 / 重验证失败率 / 分布偏移
  三通道，DriftPolicy 阈值判定（任一超阈即 drifted）——
  ``evaluation.model_drift_measured`` 留痕（evaluation 族）；
- **模型级重验证**（C4 解除——9.11 defer 项）：受影响模型跑性质
  测试/离线评估（evaluator 注入——lab ``validate_model`` 形态；
  DSL 模型可从 registry bundle 重建的提供默认路径）——
  ``evaluation.model_revalidated`` 留痕（verdict + score）；
- **告警联动**（9.12 复用）：超阈指标入 MetricsSnapshot.extra 经
  ``evaluate_alerts`` 触发告警规则；drifted → ``declare_incident``
  （关联**使用该模型的 Run**——billing 流真实可查的 run 清单；
  severity 按重验证结果分级：fail=sev1 / pass=sev2）；
- **影响分析**（FR-049 部分）：受影响 Run 清单（成本台账按模型
  反查）+ 受影响计划（plans_of_model 注入）+ 处置建议（挂起/
  回滚候选）；版本内容比较复用 ``compare_shadow``（9.6）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

_EVAL_RUN = "evaluation"

#: 重验证器面：(kind, name, version, bundle) → {"passed", "score",
#: "details"}——测试注入替身；生产接 lab validate_model 形态。
ModelEvaluator = Callable[
    [str, str, str, dict[str, Any]], Awaitable[dict[str, Any]]]


class DriftMetrics(BaseModel):
    """漂移指标快照（三通道——缺省不参与判定）。"""

    model_config = ConfigDict(extra="forbid")

    success_rate: float = Field(default=1.0, ge=0.0, le=1.0,
                                description="近期成功率（性能通道）")
    revalidation_fail_rate: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="重验证失败率（主张/性质测试失败占比）")
    distribution_shift: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="输入/输出分布偏移度（0=无偏移）")


class DriftPolicy(BaseModel):
    """漂移阈值（任一超阈即判定 drifted——fail 方向明确）。"""

    model_config = ConfigDict(extra="forbid")

    success_rate_floor: float = Field(default=0.90, ge=0.0, le=1.0)
    revalidation_fail_rate_ceiling: float = Field(default=0.10, ge=0.0,
                                                  le=1.0)
    distribution_shift_ceiling: float = Field(default=0.20, ge=0.0, le=1.0)


class DriftReport(BaseModel):
    """一次漂移检测的完整报告（AC：影响面报告）。"""

    model_config = ConfigDict(extra="forbid")

    kind: str
    name: str
    version: str
    drifted: bool
    breaches: list[str] = Field(default_factory=list,
                                description="超阈通道清单")
    revalidation_passed: bool | None = Field(
        default=None, description="模型级重验证结论（未跑=None）")
    revalidation_score: float | None = None
    affected_runs: list[str] = Field(default_factory=list)
    affected_plans: list[str] = Field(default_factory=list)
    incident_id: str | None = None
    recommended_action: str = ""  # suspend / rollback-candidate / monitor


def evaluate_drift(
    metrics: DriftMetrics, policy: DriftPolicy,
) -> tuple[bool, list[str]]:
    """阈值判定 → (drifted, 超阈通道清单)。"""
    breaches: list[str] = []
    if metrics.success_rate < policy.success_rate_floor:
        breaches.append("performance")
    if metrics.revalidation_fail_rate > policy.revalidation_fail_rate_ceiling:
        breaches.append("revalidation_fail_rate")
    if metrics.distribution_shift > policy.distribution_shift_ceiling:
        breaches.append("distribution_shift")
    return bool(breaches), breaches


async def default_dsl_evaluator(
    kind: str, name: str, version: str, bundle: dict[str, Any],
) -> dict[str, Any]:
    """默认重验证器：registry bundle 重建 DSL 模型的结构校验
    （RuleSet 可解析即 DSL 完整；完整回放/性质测试需轨迹——
    调用方带轨迹时注入自定义 evaluator 接 lab validate_model）。"""
    ruleset = bundle.get("ruleset")
    if not isinstance(ruleset, dict) or "rules" not in ruleset:
        return {"passed": False, "score": 0.0,
                "details": "bundle 无 ruleset——非 DSL 模型请注入 evaluator"}
    try:
        from vasta_model_lab import RuleSet

        RuleSet.model_validate(ruleset)  # 结构合法性（DSL 可重建）
    except Exception as exc:  # noqa: BLE001 ——校验失败即重验证失败
        return {"passed": False, "score": 0.0,
                "details": f"规则集损坏: {exc}"}
    return {"passed": True, "score": 1.0,
            "details": "DSL 结构校验通过（回放深化请注入 evaluator）"}


async def revalidate_model(
    store: Any, kind: str, name: str, version: str, *,
    evaluator: ModelEvaluator,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> dict[str, Any]:
    """模型级重验证（C4 解除）：registry bundle → evaluator（lab
    validation 形态）→ ``evaluation.model_revalidated`` 留痕。"""
    from .versioning import version_as_of

    record = await version_as_of(store, kind, name, version=version,
                                 tenant_id=tenant_id,
                                 project_id=project_id)
    result = await evaluator(kind, name, version, record.bundle)
    passed = bool(result.get("passed"))
    score = float(result.get("score", 0.0))
    sequencer = EventSequencer(
        store, _EVAL_RUN, tenant_id=tenant_id, project_id=project_id)
    await sequencer.emit("evaluation.model_revalidated", {
        "kind": kind, "name": name, "version": version,
        "passed": passed, "score": round(score, 6),
        "details": str(result.get("details", ""))[:200],
    })
    return {"passed": passed, "score": score}


def affected_runs_of_model(
    store: Any, kind: str, name: str, *,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> list[str]:
    """受影响 Run 清单（FR-049）：billing 流按模型反查（真实消费关系
    ——用过该模型的 run 才受影响）。"""
    from .quotas import CostLedger

    # billing 的 model 字段为模型名（router 形态——如 "grid"）；
    # kind 是资产类别不作匹配键（同名跨类别的歧义由调用方作用域承担）
    runs: list[str] = []
    for row in CostLedger._rows(store, tenant_id=tenant_id,  # noqa: SLF001
                                project_id=project_id):
        if row["model"] == name and row["run_id"] not in runs:
            runs.append(row["run_id"])
    return runs


async def run_drift_check(
    store: Any, kind: str, name: str, version: str,
    metrics: DriftMetrics, *,
    policy: DriftPolicy | None = None,
    evaluator: ModelEvaluator | None = None,
    plans_of_model: Callable[[str], list[str]] | None = None,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> DriftReport:
    """漂移检测主流程：指标留痕 → 阈值判定 → （超阈）模型重验证 →
    告警评估 + incident 联动 → 影响面报告。

    severity 分级：重验证 fail=sev1（模型输出不可信）/ pass=sev2
    （指标漂移但性质仍守）；建议动作：fail→suspend、分布偏移主导→
    rollback 候选、其余→monitor。"""
    # 评审修复 F3：governance 不得依赖 ops——告警/事故原语已下沉本包
    from .alerting import AlertRule, MetricsSnapshot, evaluate_alerts
    from .incidents import declare_incident

    # 评审修复 M5：幻影版本预检（漂移检测对象必须是已注册资产——
    # 曾可为不存在资产制造治理事件与 incident）
    from .versioning import version_as_of as _vao

    try:
        await _vao(store, kind, name, version=version,
                   tenant_id=tenant_id, project_id=project_id)
    except VastaError:
        raise VastaError(
            code="release.version_not_published",
            message=f"{kind} {name!r} v{version} 尚未发布",
        ) from None

    policy = policy or DriftPolicy()
    drifted, breaches = evaluate_drift(metrics, policy)
    alerts_fired: list[dict[str, Any]] = []
    if drifted:
        # 告警联动（9.12 复用）——评审修复 F10/G2(d)：告警结果并入
        # measured 事件 payload（原为无副作用死算，整段可删仍全绿）
        alerts_fired = [
            a.model_dump() for a in evaluate_alerts(
                MetricsSnapshot(extra={f"drift:{kind}:{name}": 1.0}),
                [AlertRule(name="model_drift_detected",
                           metric=f"drift:{kind}:{name}", threshold=0.5,
                           severity="sev2")])]
    sequencer = EventSequencer(
        store, _EVAL_RUN, tenant_id=tenant_id, project_id=project_id)
    await sequencer.emit("evaluation.model_drift_measured", {
        "kind": kind, "name": name, "version": version,
        "metrics": metrics.model_dump(), "drifted": drifted,
        "breaches": breaches, "alerts_fired": alerts_fired,
    })
    report = DriftReport(kind=kind, name=name, version=version,
                         drifted=drifted, breaches=breaches)
    if not drifted:
        report.recommended_action = "none"
        return report

    # 模型级重验证（C4——超阈即跑；evaluator 缺省跳过并如实记 None）
    revalidation: dict[str, Any] | None = None
    if evaluator is not None:
        # 评审修复 M6：evaluator 异常不再断头（measured 已落而 incident
        # 缺失）——异常按重验证失败继续链路（fail 方向处置）
        try:
            revalidation = await revalidate_model(
                store, kind, name, version, evaluator=evaluator,
                tenant_id=tenant_id, project_id=project_id)
        except Exception as exc:  # noqa: BLE001 ——异常=不可信（fail 处置）
            revalidation = {"passed": False, "score": 0.0,
                            "error": f"{type(exc).__name__}: {exc}"[:200]}
        report.revalidation_passed = revalidation["passed"]
        report.revalidation_score = revalidation["score"]

    # 影响面（FR-049）：受影响 Run（billing 反查）+ 计划
    report.affected_runs = affected_runs_of_model(
        store, kind, name, tenant_id=tenant_id, project_id=project_id)
    if plans_of_model is not None:
        report.affected_plans = list(plans_of_model(version))

    # incident 联动（9.12 复用）：关联受影响 Run（无消费记录时以模型
    # 引用为关联键——incident 登记需非空清单）
    severity = "sev1" if revalidation is None or not revalidation["passed"] \
        else "sev2"
    subject = f"{kind}/{name}:{version}"  # 评审修复 F10：不伪装 run id
    report.incident_id = await declare_incident(
        store, f"模型漂移：{kind} {name} v{version}"
        f"（超阈：{','.join(breaches)}）",
        related_runs=report.affected_runs, severity=severity,
        subject=subject,
        tenant_id=tenant_id, project_id=project_id)

    if revalidation is not None and not revalidation["passed"]:
        report.recommended_action = "suspend"
    elif "distribution_shift" in breaches:
        report.recommended_action = "rollback-candidate"
    else:
        report.recommended_action = "monitor"
    return report


__all__ = ["DriftMetrics", "DriftPolicy", "DriftReport",
           "affected_runs_of_model", "default_dsl_evaluator",
           "evaluate_drift", "revalidate_model", "run_drift_check"]
