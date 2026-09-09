"""回放投影：因果时间线与偏差定位（FR-060/062，Epic 4）。

全部为纯函数（AD-11：投影可随时删除重建）。

评审修复（Epic 4-7 code-review）：
- depth 计算改迭代 + 环护（原递归在环/长链上死循环/爆栈）；
- HTML 全量转义（summary/type 原样注入可执行脚本，实测可注入）；
- replay_non_model_events 真正过滤模型交换引用（原 docstring 与实现不符）；
- 复现包配置快照补 seed/policy；RegressionTask 契约上移 vasta-protocols；
- DeviationHit 补 plan_ref（最近 plan.* 上下文）；
- 删除 _FAMILY_OF 死代码。
"""

from __future__ import annotations

import html as _html
import json as _json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.envelope import EventEnvelope
from vasta_protocols.regression import RegressionTask


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
    for key in ("tool", "kind", "reason", "decision", "action", "fault_class",
                "external_source"):
        if key in payload and payload[key] is not None:
            parts.append(f"{key}={payload[key]}")
    if "contract_ref" in payload and payload["contract_ref"]:
        parts.append(f"ref={str(payload['contract_ref'])[:10]}…")
    if "artifact_refs" in payload and payload["artifact_refs"]:
        parts.append(f"arts={len(payload['artifact_refs'])}")
    text = " ".join(parts) or str(payload)[:limit]
    return text[:limit]


def _compute_depths(events: list[EventEnvelope]) -> list[int]:
    """迭代式因果深度（评审修复：环护 + 无递归深度限制）。

    parent 缺失/不在流内 → 视为根（深度 0）；parent 环按 0 锚定收口。"""
    id_to_index = {e.event_id: i for i, e in enumerate(events)}
    depths = [-1] * len(events)  # -1 = 未算

    for start in range(len(events)):
        if depths[start] != -1:
            continue
        # 沿 parent 链上探至已算节点/根/环，再自链尾回填
        chain: list[int] = []
        seen: set[int] = set()
        current = start
        while depths[current] == -1 and current not in seen:
            seen.add(current)
            chain.append(current)
            parent_id = events[current].parent_event_id
            if parent_id is None:
                current = -1  # 根
                break
            parent_index = id_to_index.get(parent_id)
            if parent_index is None:
                current = -1  # parent 不在流内 → 视为根
                break
            current = parent_index
        anchor = 0 if current == -1 or current in seen else depths[current] + 1
        for offset, node in enumerate(reversed(chain)):
            depths[node] = anchor + offset
    return depths


def timeline(events: list[EventEnvelope]) -> Timeline:
    """因果时间线投影（纯函数）。

    - depth 按因果链深度（根=无父项 → 0；迭代计算，环安全）；
    - 事件按原序输出（因果序与时间序在引擎逐事件落库时一致）；
    - 同输入同输出——满足 AD-11 可删除重建。
    """
    depths = _compute_depths(events)
    id_to_seq = {e.event_id: e.seq for e in events}
    entries: list[TimelineEntry] = []
    families: set[str] = set()
    max_depth = 0
    for index, event in enumerate(events):
        family = event.type.split(".", 1)[0]
        families.add(family)
        d = depths[index]
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
    category: str = Field(
        description="external_change | verification | policy | execution | supervisor"
    )
    summary: str
    before_seq: int | None = Field(default=None, description="最近的前置观察 seq")
    after_seq: int | None = Field(default=None, description="最近的后续观察 seq")
    contract_ref: str | None = None
    plan_ref: str | None = Field(
        default=None,
        description="最近的 plan.* 上下文标识（评审修复：补计划维度）",
    )
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

    外部变化类（observation.external 且 source≠tool，由发射侧以
    external_source 键编码）优先按时间序参与"首个"判定——环境变了先
    怀疑环境（区分"改 Agent"与"环境变了"）。"""
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
            plan_ref=_nearest_plan_ref(events, index),
            context_seqs=ctx,
        )
    return None


def _nearest_contract_ref(events: list[EventEnvelope], index: int) -> str | None:
    for event in reversed(events[: index + 1]):
        ref = event.payload.get("contract_ref")
        if ref:
            return str(ref)
    return None


def _nearest_plan_ref(events: list[EventEnvelope], index: int) -> str | None:
    """最近的 plan.* 事件标识（plan_id[:step_id]）。"""
    for event in reversed(events[: index + 1]):
        if not event.type.startswith("plan."):
            continue
        plan_id = event.payload.get("plan_id") or event.payload.get("plan_step_id")
        step_id = event.payload.get("step_id") or event.payload.get("plan_step_id")
        if plan_id and step_id and plan_id != step_id:
            return f"{plan_id}:{step_id}"
        return str(plan_id or step_id or event.type)
    return None


__all__.extend(["DeviationHit", "first_deviation"])


# ---- 自包含 HTML Replay 生成器（FR-060，Story 4.3）----

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>VastaCore Replay — {run_id}</title>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #fafafa; }}
 h1 {{ font-size: 1.2rem; }}
 .meta {{ color: #666; font-size: 0.85rem; margin-bottom: 1rem; }}
 .dev {{ background: #fff3cd; border-left: 4px solid #dc3545; padding: 0.5rem 1rem;
        margin: 1rem 0; border-radius: 4px; }}
 .ext {{ background: #d1ecf1; border-left: 4px solid #17a2b8; padding: 0.5rem 1rem;
        margin: 0.5rem 0; border-radius: 4px; }}
 table {{ border-collapse: collapse; width: 100%; font-size: 0.82rem; }}
 th, td {{ border: 1px solid #ddd; padding: 4px 8px; text-align: left; }}
 th {{ background: #e9ecef; }}
 tr.dev-row {{ background: #fff3cd; font-weight: 600; }}
 tr.ext-row {{ background: #d1ecf1; }}
 code {{ background: #eee; padding: 1px 4px; border-radius: 3px; }}
 details {{ margin: 0.3rem 0; }}
</style>
</head>
<body>
<h1>VastaCore Replay — <code>{run_id}</code></h1>
<p class="meta">events={total} depth={max_depth} families={families} ·
generated by vastacore {version}</p>
{deviation_block}
<table>
<tr><th>seq</th><th>depth</th><th>type</th><th>summary</th></tr>
{rows}
</table>
</body>
</html>"""


def render_html(
    tl: Timeline,
    hit: DeviationHit | None = None,
    *,
    version: str = "0.1.0",
) -> bytes:
    """自包含 HTML Replay：时间线 + 首偏差高亮 + 前后证据锚点。

    单文件、无外部资源（AC）；UTF-8。评审修复：全部动态文本经
    html.escape——payload 摘要原样注入 HTML 可执行脚本（实测）。"""
    rows: list[str] = []
    for entry in tl.entries:
        css = ""
        if hit and entry.seq == hit.seq:
            css = ' class="dev-row"'
        elif entry.external_change:
            css = ' class="ext-row"'
        rows.append(
            f"<tr{css}><td>{entry.seq}</td><td>{entry.depth}</td>"
            f"<td>{_html.escape(entry.type)}</td>"
            f"<td>{_html.escape(entry.summary)}</td></tr>"
        )
    dev_block = ""
    if hit:
        label = "外部变化" if hit.category == "external_change" else "首个偏差"
        css_cls = "ext" if hit.category == "external_change" else "dev"
        dev_block = (
            f'<div class="{css_cls}">{_html.escape(label)}: seq={hit.seq} '
            f"{_html.escape(hit.type)} [{_html.escape(hit.category)}] — "
            f"{_html.escape(hit.summary)}<br>"
            f"契约 ref: <code>{_html.escape(hit.contract_ref or '无')}</code> · "
            f"计划 ref: <code>{_html.escape(hit.plan_ref or '无')}</code> · "
            f"前后观察: before={hit.before_seq} after={hit.after_seq}</div>"
        )
    exts = [
        e
        for e in tl.entries
        if e.external_change and (hit is None or e.seq != hit.seq)
    ]
    for ext in exts:
        dev_block += (
            f'<div class="ext">外部变化: seq={ext.seq} '
            f"{_html.escape(ext.type)} — {_html.escape(ext.summary)}</div>"
        )
    html = _HTML_TEMPLATE.format(
        run_id=_html.escape(tl.run_id),
        total=tl.total_events,
        max_depth=tl.max_depth,
        families=_html.escape(",".join(tl.families_present)),
        version=_html.escape(version),
        deviation_block=dev_block,
        rows="\n".join(rows),
    )
    return html.encode("utf-8")


__all__.append("render_html")


# ---- 最小复现包与回归任务（FR-062，Story 4.4）----


class ReproBundle(BaseModel):
    """最小复现包清单——干净环境离线重放非模型事件与核验器（AC-08）。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    tenant_id: str
    project_id: str
    event_count: int = Field(ge=1)
    artifact_refs: list[str] = Field(default_factory=list)
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    bundle_format_version: str = "1.0"


async def export_repro_bundle(
    store: Any,
    run_id: str,
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> tuple[ReproBundle, bytes]:
    """导出复现包：事件 JSON Lines + Artifact 引用清单 + 配置快照。

    - 不含模型密钥与无关租户数据（AC）；
    - bundle JSON（清单）与 events.jsonl（逐行事件）两段由调用方落盘；
    - 配置快照含 budget/seed/policy 与全部契约引用（评审修复：FR-063
      还原要件原缺 seed/policy）。"""
    events = list(
        store.iter_run_events(run_id, tenant_id=tenant_id, project_id=project_id)
    )
    if not events:
        from vasta_protocols.errors import VastaError

        raise VastaError(
            code="repro.run_not_found", message=f"未找到 Run {run_id!r}"
        )
    artifact_refs: set[str] = set()
    for event in events:
        refs = event.payload.get("artifact_refs")
        if isinstance(refs, list):
            artifact_refs.update(str(r) for r in refs)
        ref = event.payload.get("contract_ref")
        if ref:
            artifact_refs.add(str(ref))
        rref = event.payload.get("result_ref")
        if rref:
            artifact_refs.add(str(rref))
    config_snapshot: dict[str, Any] = {}
    for event in events:
        if event.type == "run.created":
            config_snapshot = {"budget": dict(event.payload.get("budget", {}))}
            if event.payload.get("seed") is not None:
                config_snapshot["seed"] = event.payload["seed"]
            if event.payload.get("policy"):
                config_snapshot["policy"] = event.payload["policy"]
        if event.type == "action.contracted":
            config_snapshot.setdefault("contract_refs", []).append(
                event.payload.get("contract_ref")
            )
    bundle = ReproBundle(
        run_id=run_id,
        tenant_id=tenant_id or events[0].tenant_id,
        project_id=project_id or events[0].project_id,
        event_count=len(events),
        artifact_refs=sorted(artifact_refs),
        config_snapshot=config_snapshot,
    )
    lines = "\n".join(e.model_dump_json() for e in events)
    return bundle, lines.encode("utf-8")


def build_regression_task(
    bundle: ReproBundle, event_lines: bytes, *, task_id: str | None = None
) -> RegressionTask:
    """复现包转回归任务（契约格式在 vasta_protocols.regression）。"""
    from ._bookkeeping import utcnow_iso

    events = [
        _json.loads(line)
        for line in event_lines.decode("utf-8").splitlines()
        if line.strip()
    ]
    return RegressionTask(
        task_id=task_id or f"repro-{bundle.run_id}",
        source_run_id=bundle.run_id,
        event_data=events,
        created_at=utcnow_iso(),
    )


def _is_model_exchange_ref(event: EventEnvelope) -> bool:
    """模型交换引用判定：result/artifact 引用指向 model.exchange。"""
    refs: list[str] = []
    rref = event.payload.get("result_ref")
    if rref:
        refs.append(str(rref))
    arefs = event.payload.get("artifact_refs")
    if isinstance(arefs, list):
        refs.extend(str(r) for r in arefs)
    if event.payload.get("kind") == "model.exchange":
        return True
    return any("model.exchange" in r for r in refs)


def replay_non_model_events(event_lines: bytes) -> list[str]:
    """离线重放非模型事件（AC-08 的最小验证：逐条解析 + schema 校验）。

    模型调用事件（含 model.exchange 引用）跳过——重放不重新调用模型
    （评审修复：原实现全量重放，与 docstring 承诺不符）。"""
    replayed: list[str] = []
    for line in event_lines.decode("utf-8").splitlines():
        if not line.strip():
            continue
        event = EventEnvelope.model_validate_json(line)
        if _is_model_exchange_ref(event):
            continue
        replayed.append(f"{event.seq}:{event.type}")
    return replayed


__all__.extend(
    [
        "ReproBundle",
        "RegressionTask",  # 兼容再导出（契约本体在 vasta_protocols.regression）
        "build_regression_task",
        "export_repro_bundle",
        "replay_non_model_events",
    ]
)
