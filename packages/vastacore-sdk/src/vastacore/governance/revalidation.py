"""环境升级批量重验证与认知衰减（Story 9.11，FR-026，G4）。

世界变了，旧结论的可信度跟着变：

- 环境升级登记（``record_env_upgrade`` → ``evaluation.env_upgraded``
  ——evaluation 族）：携带受影响范围（affected_scope）；
- 影响面分析（``impact_analysis``）：scope 命中受影响范围的**活跃**
  主张 + 沿 ``depends_on`` 的下游闭包（依赖图传播——AC「Claim 依赖
  图」）；终态主张不参与；
- 批量重验证（``revalidate_claims``）：对每条受影响主张的**源 Run**
  离线重评估（复用 8.10 ``offline_evaluate``——只读零副作用）；
  无源 Run → 判 fail（fail-closed：证据链不可重放=不可信增量）；
- 处置（DecayPolicy）：verdict=pass → 保留（``claim.revalidated``）；
  fail → 置信衰减（``claim.confidence_decayed``），低于推翻线 →
  ``claim.refuted``（复用既有失效传播——级联下游）；
- 影响面报告（ImpactReport）：受影响清单 + 逐条处置结果 + 汇总；
- W-1（AC-07 CI）挂载：``seed_confidence_interval``——多种子正态
  近似 CI 计算面（真实适配器 × ≥10 种子接入后即解除，披露维持）。
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

_ENV_RUN = "environment"


class DecayPolicy(BaseModel):
    """衰减规则：fail 一次置信 × factor；低于 refute_below 推翻。"""

    model_config = ConfigDict(extra="forbid")

    decay_factor: float = Field(default=0.5, gt=0.0, lt=1.0)
    refute_below: float = Field(default=0.2, ge=0.0, le=1.0)


class ImpactItem(BaseModel):
    """单主张处置记录。"""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    verdict: str  # pass | fail | no_source_run
    action: str  # kept | decayed | refuted
    confidence_before: float
    confidence_after: float
    propagated: list[str] = Field(default_factory=list,
                                  description="级联失效的下游主张")


class ImpactReport(BaseModel):
    """影响面报告（AC：受影响清单+处置结果）。"""

    model_config = ConfigDict(extra="forbid")

    env_old: str
    env_new: str
    affected_count: int = Field(ge=0)
    kept: int = Field(default=0, ge=0)
    decayed: int = Field(default=0, ge=0)
    refuted: int = Field(default=0, ge=0)
    items: list[ImpactItem] = Field(default_factory=list)


async def record_env_upgrade(
    store: Any, *, env_old: str, env_new: str,
    affected_scope: dict[str, str],
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> None:
    """环境版本升级事件登记（evaluation.env_upgraded——触发批量重验
    证的时间锚；affected_scope 声明受影响范围，如 {"region": "prod"}）。"""
    if not affected_scope:
        raise VastaError(
            code="revalidation.empty_scope",
            message="affected_scope 不可为空（全量升级请显式给哨兵键）",
        )
    sequencer = EventSequencer(
        store, _ENV_RUN, tenant_id=tenant_id, project_id=project_id)
    await sequencer.emit("evaluation.env_upgraded", {
        "env_old": env_old, "env_new": env_new,
        "affected_scope": dict(affected_scope),
    })


def impact_analysis(
    cognition: Any, affected_scope: dict[str, str],
) -> list[Any]:
    """受影响主张：scope 与 affected_scope 键值对相交（任一项相等）的
    活跃主张 + depends_on 下游闭包（依赖图传播；环安全）。"""
    items = set(affected_scope.items())
    direct = [
        c for c in cognition._claims.values()  # noqa: SLF001——同 SDK 域查询
        if c.status not in ("refuted", "retired")
        and items & set(c.scope.items())
    ]
    affected: dict[str, Any] = {c.claim_id: c for c in direct}
    # 下游闭包（BFS；visited 防环；refuted/retired 不入——评审修复 F14：
    # 终态下游曾计入 affected_count 又被处理跳过，报告计数不变量破坏）
    frontier = [c.claim_id for c in direct]
    while frontier:
        current = frontier.pop()
        for other in cognition._claims.values():  # noqa: SLF001
            terminal = other.status in ("refuted", "retired")
            if other.claim_id in affected or terminal:
                continue
            if current in other.depends_on:
                affected[other.claim_id] = other
                frontier.append(other.claim_id)
    return list(affected.values())


async def _verdict_of(
    store: Any, claim: Any, *, verifiers: dict[str, Any],
    tenant_id: str, project_id: str,
) -> str:
    """单主张重验证判定：源 Run 离线重评估（8.10 复用）——
    changed 为空 = pass。无源 Run → no_source_run（按 fail 处置）。"""
    from ..models.offline_eval import offline_evaluate

    if not claim.run_id:
        return "no_source_run"
    try:
        report = await offline_evaluate(
            store, claim.run_id, verifiers=verifiers,
            tenant_id=tenant_id, project_id=project_id,
        )
    except VastaError:
        return "no_source_run"  # 源 Run 已不可重放（同保守口径）
    return "pass" if not report.changed else "fail"


async def revalidate_claims(
    store: Any, cognition: Any, *,
    env_old: str, env_new: str,
    affected_scope: dict[str, str],
    verifiers: dict[str, Any],
    policy: DecayPolicy | None = None,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> ImpactReport:
    """批量重验证 + 处置（衰减/推翻）+ 影响面报告。

    处置规则：pass → kept（claim.revalidated）；fail → 置信 ×
    decay_factor（claim.confidence_decayed），结果 < refute_below →
    claim.refuted（复用既有级联失效——下游主张随依赖图推翻）。"""
    policy = policy or DecayPolicy()
    affected = impact_analysis(cognition, affected_scope)
    report = ImpactReport(env_old=env_old, env_new=env_new,
                          affected_count=len(affected))
    handled: set[str] = set()
    for claim in affected:
        if claim.claim_id in handled:
            continue  # 级联推翻可能已处置下游
        current = cognition.get(claim.claim_id)
        if current is None or current.status in ("refuted", "retired"):
            continue
        verdict = await _verdict_of(
            store, current, verifiers=verifiers,
            tenant_id=tenant_id, project_id=project_id)
        await cognition.revalidated(
            claim.claim_id, verdict=verdict, env_version=env_new)
        before = current.confidence
        if verdict == "pass":
            report.kept += 1
            report.items.append(ImpactItem(
                claim_id=claim.claim_id, verdict=verdict, action="kept",
                confidence_before=before, confidence_after=before))
            continue
        after = await cognition.decay_confidence(
            claim.claim_id, factor=policy.decay_factor,
            reason=f"env_upgrade:{env_old}->{env_new} revalidation {verdict}")
        if after < policy.refute_below:
            propagated = await cognition.refute(
                claim.claim_id,
                counterevidence=[f"env_upgrade:{env_old}->{env_new}"],
            )
            handled.update(propagated)
            report.refuted += 1
            report.items.append(ImpactItem(
                claim_id=claim.claim_id, verdict=verdict, action="refuted",
                confidence_before=before, confidence_after=after,
                propagated=propagated))
        else:
            report.decayed += 1
            report.items.append(ImpactItem(
                claim_id=claim.claim_id, verdict=verdict, action="decayed",
                confidence_before=before, confidence_after=after))
    return report


def seed_confidence_interval(
    values: list[float], *, level: float = 0.95,
) -> dict[str, float]:
    """多种子 CI（W-1 计算面——AC-07 解除条件挂载）。

    正态近似（z=1.96 @95%）：mean ± z·σ/√n；n<2 → 报错（CI 无意义）。
    真实适配器 × VastaLab ≥10 种子接入后并入评测报告即解除 W-1
    （当前以模拟器方差运行=不具代表性，豁免维持——披露）。"""
    if len(values) < 2:
        raise VastaError(
            code="revalidation.ci_needs_seeds",
            message=f"CI 至少需要 2 个种子样本（得到 {len(values)}）",
        )
    if not all(math.isfinite(v) for v in values):
        # 评审修复 F16：NaN/inf 样本静默产出全 NaN CI——拒
        raise VastaError(
            code="revalidation.ci_non_finite",
            message="CI 样本含非有限值（NaN/inf）",
        )
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    sigma = math.sqrt(variance)
    z = {0.90: 1.645, 0.95: 1.960, 0.99: 2.576}.get(level)
    if z is None:
        raise VastaError(
            code="revalidation.bad_ci_level",
            message=f"level 支持 0.90/0.95/0.99（得到 {level}）",
        )
    half = z * sigma / math.sqrt(n)
    return {
        "n": float(n), "mean": round(mean, 6),
        "half_width": round(half, 6),
        "low": round(mean - half, 6), "high": round(mean + half, 6),
        "level": level,
    }


__all__ = ["DecayPolicy", "ImpactItem", "ImpactReport",
           "impact_analysis", "record_env_upgrade", "revalidate_claims",
           "seed_confidence_interval"]
