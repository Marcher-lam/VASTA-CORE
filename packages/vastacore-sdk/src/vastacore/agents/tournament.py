"""并行探索与候选竞赛（Story 11.10，FR-056，G4）。

多个候选假设同时验证择优：

- **TournamentSpec**：候选清单（每候选独立配置）+ 任务集 + 评测
  口径（复用 8.7 消融语义——指标集）；
- **run_tournament**：并行执行（asyncio.gather——每候选独立
  executor 调用；executor 注入对接 8.9 批量 Run 形态）；候选间
  预算隔离（单候选超预算/异常只记该候选失败——不毁整赛）；
- **评测对比排序**：候选 × 指标矩阵 → 综合排序（复用消融的
  「报告即证据」语义）+ 胜出标记留痕（``evaluation.tournament_settled``
  ——winner + 全量对比入事件）；
- 竞赛受配额约束（调用方经 9.8 闸——本模块不重复实现）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

_TOURNAMENT_RUN = "evaluation"

#: 候选执行器：async (candidate_name) -> dict（指标名→值；异常即失败）。
CandidateRunner = Callable[[str], Awaitable[dict[str, float]]]


class Candidate(BaseModel):
    """竞赛候选（名称 + 配置描述——执行面由 runner 解释）。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class TournamentSpec(BaseModel):
    """竞赛规格。"""

    model_config = ConfigDict(extra="forbid")

    tournament_id: str = Field(min_length=1)
    candidates: list[Candidate] = Field(min_length=2)
    metrics: list[str] = Field(min_length=1,
                               description="评测指标集（复用消融口径）")
    # higher_is_better per metric（缺省 True）
    metric_direction: dict[str, bool] = Field(
        default_factory=dict,
        description="指标名 → 越大越好（缺省 True）")

    def model_post_init(self, __context: Any) -> None:
        names = [c.name for c in self.candidates]
        if len(set(names)) != len(names):
            duplicates = sorted({n for n in names
                                 if names.count(n) > 1})
            raise ValueError(
                f"候选名不唯一 {duplicates}——winner 归属不可区分")
        if len(set(self.metrics)) != len(self.metrics):
            raise ValueError(
                f"指标集含重复项 {self.metrics}——重复计分权重翻倍")


class CandidateResult(BaseModel):
    """单候选竞赛结果。"""

    model_config = ConfigDict(extra="forbid")

    candidate: str
    metrics: dict[str, float] = Field(default_factory=dict)
    failed: bool = False
    error: str | None = None


class TournamentReport(BaseModel):
    """竞赛报告（排序 + 胜出）。"""

    model_config = ConfigDict(extra="forbid")

    tournament_id: str
    results: list[CandidateResult] = Field(
        description="按综合分降序（失败垫底）")
    winner: str | None = None


def _validate_metrics(result: CandidateResult,
                      spec: TournamentSpec) -> None:
    """指标面核验（评审修复——盲审 M4、边界 T-1/T-2）：

    - 缺任一 spec 指标 → 该候选 failed：缺失静默计 0.0 使「少报
      指标」在越小越好维度必胜（0 是理论最优值）；
    - 非有限值（NaN/inf）→ failed：NaN 与任何数比较恒 False，
      排序未定义（实测 NaN 候选可居首）。
    """
    import math

    missing = [m for m in spec.metrics if m not in result.metrics]
    if missing:
        raise VastaError(
            code="tournament.missing_metrics",
            message=(f"候选 {result.candidate!r} 缺指标 {missing}"
                     "——少报指标即失败（不可静默计 0 分）"),
        )
    for metric, value in result.metrics.items():
        if not isinstance(value, (int, float)) or \
                isinstance(value, bool) or not math.isfinite(value):
            raise VastaError(
                code="tournament.non_finite_metric",
                message=(f"候选 {result.candidate!r} 指标 {metric}="
                         f"{value!r} 非有限数——排序未定义"),
            )


def _composite_score(result: CandidateResult,
                     spec: TournamentSpec) -> float:
    """综合分：各指标按方向归一后求和（失败候选 -inf 垫底）。"""
    if result.failed:
        return float("-inf")
    score = 0.0
    for metric in spec.metrics:
        value = result.metrics[metric]  # _validate_metrics 已保证在
        higher_better = spec.metric_direction.get(metric, True)
        score += value if higher_better else -value
    return score


async def run_tournament(
    store: Any, spec: TournamentSpec,
    runner: CandidateRunner,
    *, tenant_id: str = "t-default", project_id: str = "p-default",
) -> TournamentReport:
    """并行执行 + 预算隔离 + 排序 + 胜出留痕。

    预算隔离：单候选异常/失败只记该候选（其余照常）——gather
    return_exceptions 语义的显式化。"""
    import asyncio

    sequencer = EventSequencer(
        store, _TOURNAMENT_RUN,
        tenant_id=tenant_id, project_id=project_id)
    await sequencer.emit("evaluation.tournament_started", {
        "tournament_id": spec.tournament_id,
        "candidates": [c.name for c in spec.candidates],
        "metrics": list(spec.metrics),
    })

    async def run_one(candidate: Candidate) -> CandidateResult:
        try:
            metrics = await runner(candidate.name)
            result = CandidateResult(candidate=candidate.name,
                                     metrics=dict(metrics))
            _validate_metrics(result, spec)
            return result
        except Exception as exc:  # noqa: BLE001——单候选失败不毁整赛
            return CandidateResult(
                candidate=candidate.name, failed=True,
                error=f"{type(exc).__name__}: {exc}"[:200])

    raw = await asyncio.gather(
        *(run_one(c) for c in spec.candidates))
    ranked = sorted(raw, key=lambda r: _composite_score(r, spec),
                    reverse=True)
    winner = ranked[0].candidate if ranked and not ranked[0].failed \
        else None
    await sequencer.emit("evaluation.tournament_settled", {
        "tournament_id": spec.tournament_id,
        "winner": winner,
        "ranking": [
            {"candidate": r.candidate, "failed": r.failed,
             "metrics": r.metrics, "score": (
                 _composite_score(r, spec)
                 if not r.failed else None)}
            for r in ranked],
    })
    return TournamentReport(tournament_id=spec.tournament_id,
                           results=ranked, winner=winner)


__all__ = ["Candidate", "CandidateResult", "TournamentReport",
           "TournamentSpec", "run_tournament"]
