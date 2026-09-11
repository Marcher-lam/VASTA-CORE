"""跨模型/环境排行榜（Story 11.12，FR-069，G5）。

候选竞赛与评测结果可跨 Run 聚合比较：

- **LeaderboardSpec**：任务集 + 指标 + 时间窗 + 可见性
  （public/private——复用 11.6 共享边界语义）；
- **LeaderboardEntry**：模型/配置/口径 + **证据引用**（Run id
  可溯——引用评测事件而非复制数值：条目不可篡改的机制保证）；
- **generate_leaderboard**：跨 Run 聚合评测事件
  （``evaluation.tournament_settled`` 与离线评测报告面）→ 排序
  条目 → ``evaluation.leaderboard_generated`` 留痕；
- 可见性校验：private 榜按作用域（RBAC evaluate_access）；
  public 榜开放读。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

_LEADERBOARD_RUN = "evaluation"


class LeaderboardSpec(BaseModel):
    """排行榜规格。"""

    model_config = ConfigDict(extra="forbid")

    leaderboard_id: str = Field(min_length=1)
    metric: str = Field(min_length=1,
                        description="排序指标（越高越好）")
    visibility: str = Field(pattern="^(public|private)$",
                            default="public")
    window_start: datetime
    window_end: datetime
    tenant_id: str = "t-default"
    project_id: str = "p-default"


class LeaderboardEntry(BaseModel):
    """榜单条目（证据引用——不复制数值）。"""

    model_config = ConfigDict(extra="forbid")

    candidate: str
    score: float
    evidence_run: str = Field(description="评测 Run id（证据可溯）")
    evidence_event_seq: int = Field(ge=0,
                                    description="评测事件 seq")


class Leaderboard(BaseModel):
    """排行榜（生成即留痕——不可变快照）。"""

    model_config = ConfigDict(extra="forbid")

    leaderboard_id: str
    metric: str
    visibility: str
    entries: list[LeaderboardEntry] = Field(
        description="按指标降序")


async def generate_leaderboard(
    store: Any, spec: LeaderboardSpec,
    *, results: list[tuple[str, float, str, int]],
) -> Leaderboard:
    """从评测结果（candidate, score, run_id, event_seq）生成榜单。

    results 由调用方从评测事件聚合（保持证据引用语义——本函数
    只排序留痕）。≥1 条目。"""
    if not results:
        raise VastaError(
            code="leaderboard.no_entries",
            message="榜单至少一条结果（无结果的榜不生成）",
        )
    entries = sorted(
        (LeaderboardEntry(candidate=c, score=s, evidence_run=r,
                          evidence_event_seq=q)
         for c, s, r, q in results),
        key=lambda e: e.score, reverse=True)
    board = Leaderboard(
        leaderboard_id=spec.leaderboard_id, metric=spec.metric,
        visibility=spec.visibility, entries=entries)
    sequencer = EventSequencer(
        store, _LEADERBOARD_RUN,
        tenant_id=spec.tenant_id, project_id=spec.project_id)
    await sequencer.emit("evaluation.leaderboard_generated", {
        "leaderboard_id": spec.leaderboard_id,
        "metric": spec.metric, "visibility": spec.visibility,
        "window": {"start": spec.window_start.isoformat(),
                   "end": spec.window_end.isoformat()},
        "entries": [e.model_dump(mode="json") for e in entries],
    })
    return board


def check_leaderboard_access(
    board: Leaderboard, *,
    tenant_id: str, project_id: str,
    principal: Any = None,
) -> None:
    """可见性校验：public 开放；private 按作用域（principal 给定
    时 RBAC 评估——否则作用域字符串比对）。fail-closed。"""
    if board.visibility == "public":
        return
    if principal is not None:
        from ..governance.rbac import evaluate_access

        decision = evaluate_access(
            principal, "cognition", "read",
            tenant_id=tenant_id, project_id=project_id)
        if not decision.allowed:
            raise VastaError(
                code="access.denied",
                message=f"私有榜——{decision.reason}",
            )
        return
    # 无 principal：仅同作用域（fail-closed 缺省）
    raise VastaError(
        code="access.denied",
        message="私有榜——需认证主体（无 principal 即拒）",
    )


__all__ = ["Leaderboard", "LeaderboardEntry", "LeaderboardSpec",
           "check_leaderboard_access", "generate_leaderboard"]
