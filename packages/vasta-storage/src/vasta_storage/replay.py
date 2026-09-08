"""回放投影：因果时间线与偏差定位（FR-060/062，Epic 4）。

全部为纯函数（AD-11：投影可随时删除重建）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.envelope import EVENT_FAMILIES, EventEnvelope

#: 外部变化类事件（区别于工具回读的 observation.external）。
_FAMILY_OF = {f: f for f in EVENT_FAMILIES}


class TimelineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int
    event_id: str
    type: str
    family: str
    depth: int = Field(ge=0, description="因果链深度（根=0）")
    parent_seq: int | None = None
    ts: str
    summary: str = Field(description="payload 摘要（截断）")
    external_change: bool = Field(
        default=False, description="外部变化标记（observation.external 且 source≠tool）"
    )


class Timeline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    entries: list[TimelineEntry]
    total_events: int = Field(ge=0)
    max_depth: int = Field(ge=0)
    families_present: list[str]

    @property
    def covers_all_events(self) -> bool:
        """AC-01：投影覆盖事件流全部条目。"""
        return self.total_events == len(self.entries)


def _summarize(payload: dict[str, Any], limit: int = 80) -> str:
    parts: list[str] = []
    for key in ("tool", "kind", "reason", "decision", "action", "fault_class"):
        if key in payload and payload[key] is not None:
            parts.append(f"{key}={payload[key]}")
    if "contract_ref" in payload and payload["contract_ref"]:
        parts.append(f"ref={str(payload['contract_ref'])[:10]}…")
    if "artifact_refs" in payload and payload["artifact_refs"]:
        parts.append(f"arts={len(payload['artifact_refs'])}")
    text = " ".join(parts) or str(payload)[:limit]
    return text[:limit]


def timeline(events: list[EventEnvelope]) -> Timeline:
    """因果时间线投影（纯函数）。

    - depth 按因果链深度（根=无父项 → 0）；
    - 事件按原序输出（因果序与时间序在引擎逐事件落库时一致）；
    - 同输入同输出——满足 AD-11 可删除重建。
    """
    seq_to_index = {e.seq: i for i, e in enumerate(events)}
    id_to_seq = {e.event_id: e.seq for e in events}
    depth_cache: dict[int, int] = {}

    def depth_of(event: EventEnvelope) -> int:
        if event.seq in depth_cache:
            return depth_cache[event.seq]
        if event.parent_event_id is None:
            depth_cache[event.seq] = 0
            return 0
        parent_seq = id_to_seq.get(event.parent_event_id)
        if parent_seq is None or parent_seq not in seq_to_index:
            depth_cache[event.seq] = 0
            return 0
        d = depth_of(events[seq_to_index[parent_seq]]) + 1
        depth_cache[event.seq] = d
        return d

    entries: list[TimelineEntry] = []
    families: set[str] = set()
    max_depth = 0
    for event in events:
        family = event.type.split(".", 1)[0]
        families.add(family)
        d = depth_of(event)
        max_depth = max(max_depth, d)
        external_change = (
            event.type == "observation.external"
            and "external_source" in event.payload
        )
        entries.append(
            TimelineEntry(
                seq=event.seq,
                event_id=event.event_id,
                type=event.type,
                family=family,
                depth=d,
                parent_seq=(
                    id_to_seq.get(event.parent_event_id)
                    if event.parent_event_id
                    else None
                ),
                ts=event.ts.isoformat(),
                summary=_summarize(event.payload),
                external_change=external_change,
            )
        )
    return Timeline(
        run_id=events[0].run_id if events else "",
        entries=entries,
        total_events=len(events),
        max_depth=max_depth,
        families_present=sorted(families),
    )


def render_text(tl: Timeline, *, width: int = 100) -> str:
    """文本表格（depth 缩进 + 类型 + 摘要）。"""
    lines: list[str] = [
        f"timeline run={tl.run_id} events={tl.total_events} "
        f"depth={tl.max_depth} families={','.join(tl.families_present)}"
    ]
    for entry in tl.entries:
        indent = "  " * entry.depth
        marker = " [外部变化]" if entry.external_change else ""
        line = f"{entry.seq:>4} {indent}{entry.type}{marker}"
        if entry.summary:
            line += f" — {entry.summary}"
        lines.append(line[:width])
    return "\n".join(lines)


__all__ = ["Timeline", "TimelineEntry", "render_text", "timeline"]


# ---- 首偏差定位（FR-060，Story 4.2）----

#: 偏差信号事件类型（发现即定位）。
_DEVIATION_TYPES = frozenset(
    {
        "verification.deviated",
        "verification.errored",
        "action.policy_denied",
        "action.failed",
        "action.approval_requested",
        "incident.opened",
        "run.failed",
    }
)


class DeviationHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int
    type: str
    category: str = Field(description="external_change | verification | policy | execution | supervisor")
    summary: str
    before_seq: int | None = Field(default=None, description="最近的前置观察 seq")
    after_seq: int | None = Field(default=None, description="最近的后续观察 seq")
    contract_ref: str | None = None
    # 上下文窗口（含首偏差的前后各若干事件 seq）
    context_seqs: list[int] = Field(default_factory=list)


def _category_of(event_type: str, payload: dict[str, Any]) -> str:
    if "external_source" in payload:
        return "external_change"
    if event_type.startswith("verification."):
        return "verification"
    if event_type == "action.policy_denied":
        return "policy"
    if event_type in ("action.failed", "run.failed"):
        return "execution"
    return "supervisor"


def first_deviation(events: list[EventEnvelope], *, context_radius: int = 3) -> DeviationHit | None:
    """定位首个偏差信号（UJ-1 核心：分钟级排障入口）。

    外部变化类（observation.external 且 source≠tool）优先按时间序参与
    “首个”判定——环境变了先怀疑环境（区分“改 Agent”与“环境变了”）。
    """
    for index, event in enumerate(events):
        is_dev = event.type in _DEVIATION_TYPES
        is_external = (
            event.type == "observation.external"
            and "external_source" in event.payload
        )
        if not (is_dev or is_external):
            continue
        before = next(
            (e.seq for e in reversed(events[:index])
             if e.type.startswith("observation.")),
            None,
        )
        after = next(
            (e.seq for e in events[index + 1 :]
             if e.type.startswith("observation.")),
            None,
        )
        ctx = [e.seq for e in events
               if abs(e.seq - event.seq) <= context_radius]
        return DeviationHit(
            seq=event.seq,
            type=event.type,
            category=_category_of(event.type, event.payload),
            summary=_summarize(event.payload),
            before_seq=before,
            after_seq=after,
            contract_ref=event.payload.get("contract_ref")
            or _nearest_contract_ref(events, index),
            context_seqs=ctx,
        )
    return None


def _nearest_contract_ref(events: list[EventEnvelope], index: int) -> str | None:
    for event in reversed(events[: index + 1]):
        ref = event.payload.get("contract_ref")
        if ref:
            return str(ref)
    return None


__all__.extend(["DeviationHit", "first_deviation"])
