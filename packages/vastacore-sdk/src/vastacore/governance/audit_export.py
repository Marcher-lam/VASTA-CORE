"""企业审计导出（Story 10.6，FR-068，G2）。

JSON 只读导出 + 自包含 HTML 审计报告：

- **JSON 导出**（export_audit_json）：审计系统流逐事件（信封全字段）
  + 工件引用**清单化**（sha 列表——**不含 blob 内容**，AC 字面）；
  时间窗 + 作用域过滤（信封 tenant/project——他租户不入导出）；
- **HTML 报告**（render_audit_html）：五节——时间线 / 批准 /
  访问拒绝 / 事故 / 成本（自包含零构建，Studio 同形态；全部插值
  HTML 转义——9.13 F10 教训）；
- **导出留痕**（AC）：``evaluation.audit_exported``（窗/作用域/
  事件数/引用数/导出人）——导出行为本身可审计；
- 只读：不写任何业务流；run 事件流默认不含（审计面=治理流，
  ``include_runs=True`` 可加）。
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.sequencer import EventSequencer

_EXPORT_RUN = "evaluation"

#: 审计面系统流（治理事件——run 业务流默认不在，include_runs 可加）。
AUDIT_STREAMS: tuple[str, ...] = (
    "approvals", "access", "quotas", "billing", "incidents",
    "lifecycle", "schedules", "environment", "cognition", "registry",
    "evaluation",  # 评审修复 F11：漂移/重验证留痕入企业审计面
)


class AuditExportQuery(BaseModel):
    """审计导出查询（时间窗 + 作用域）。"""

    model_config = ConfigDict(extra="forbid")

    start_ts: datetime
    end_ts: datetime
    tenant_id: str = "t-default"
    project_id: str = "p-default"
    include_runs: bool = False
    exported_by: str = Field(default="operator",
                             description="导出人（留痕用）")


class AuditExport(BaseModel):
    """JSON 只读导出体。"""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    exported_by: str
    window: dict[str, str]
    scope: dict[str, str]
    total_events: int = Field(ge=0)
    streams: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    artifact_refs: list[str] = Field(
        default_factory=list,
        description="引用工件 sha 清单（不含 blob 内容——只读审计面）")


def _in_window(event: Any, start: datetime, end: datetime) -> bool:
    """窗判定（评审修复 F5：查询侧 naive 按 UTC 解释——原裸 TypeError
    崩溃；事件 ts 恒 aware（信封强制），naive 窗是调用方最自然形态）。"""
    from datetime import UTC

    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    ts = event.ts
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return start <= ts <= end


def export_audit_json(
    store: Any, query: AuditExportQuery,
) -> AuditExport:
    """JSON 只读导出（窗 + 作用域过滤；事件逐条信封全字段；
    工件引用清单化）。"""
    from vasta_protocols.ids import now_utc

    streams: dict[str, list[dict[str, Any]]] = {}
    refs: set[str] = set()
    total = 0
    def collect(stream: str) -> None:
        nonlocal total
        events = [
            e for e in store.iter_run_events(
                stream, tenant_id=query.tenant_id,
                project_id=query.project_id)
            if _in_window(e, query.start_ts, query.end_ts)
        ]
        if not events:
            return
        rows = []
        for e in events:
            rows.append(e.model_dump(mode="json"))
            total += 1
            payload_refs = e.payload.get("artifact_refs")
            if isinstance(payload_refs, list):
                refs.update(str(r) for r in payload_refs)
            for key in ("contract_ref", "result_ref"):
                ref = e.payload.get(key)
                if ref:
                    refs.add(str(ref))
        streams[stream] = rows

    for stream in AUDIT_STREAMS:
        collect(stream)
    if query.include_runs:
        # 评审修复 M4/F6：原字段为死旗——实现真实收集（业务 run =
        # 非系统流名的事件流；sqlite 直查 distinct——同 SDK 域模式）
        with store._lock:  # noqa: SLF001——同 SDK 域只读直查
            all_runs = [r[0] for r in store._conn.execute(  # noqa: SLF001
                "SELECT DISTINCT run_id FROM events").fetchall()]
        for run in all_runs:
            if run not in AUDIT_STREAMS:
                collect(run)
    return AuditExport(
        generated_at=now_utc().isoformat(),
        exported_by=query.exported_by,
        window={"start": query.start_ts.isoformat(),
                "end": query.end_ts.isoformat()},
        scope={"tenant_id": query.tenant_id,
               "project_id": query.project_id},
        total_events=total, streams=streams,
        artifact_refs=sorted(refs),
    )


async def export_audit_json_traced(
    store: Any, query: AuditExportQuery,
) -> AuditExport:
    """导出 + 留痕（evaluation.audit_exported——导出行为可审计）。"""
    export = export_audit_json(store, query)
    sequencer = EventSequencer(
        store, _EXPORT_RUN,
        tenant_id=query.tenant_id, project_id=query.project_id)
    await sequencer.emit("evaluation.audit_exported", {
        "exported_by": query.exported_by,
        "window": export.window, "scope": export.scope,
        "total_events": export.total_events,
        "artifact_refs_count": len(export.artifact_refs),
    })
    return export


def _fmt_ts(iso: str) -> str:
    return html.escape(iso.replace("T", " ")[:19])


def render_audit_html(export: AuditExport) -> str:
    """自包含 HTML 审计报告（五节：时间线/批准/访问拒绝/事故/成本）。

    全部插值经 ``html.escape``（9.13 F10 教训——statement/reason 等
    源自数据面输入）。"""
    timeline = sorted(
        (row for rows in export.streams.values() for row in rows),
        key=lambda r: str(r.get("ts", "")))
    approvals = export.streams.get("approvals", [])
    denies = [
        *[e for e in export.streams.get("access", [])
          if e.get("type") == "artifact.access_denied"],
        *[e for e in export.streams.get("quotas", [])
          if e.get("type") == "run.throttled"],
    ]
    incidents = [
        e for e in export.streams.get("incidents", [])
        if e.get("type") in ("incident.declared", "incident.resolved",
                             "incident.opened")
    ]
    billing = export.streams.get("billing", [])
    by_model: dict[str, float] = {}
    for e in billing:
        if e.get("type") != "run.cost_recorded":
            continue
        model = str(e.get("payload", {}).get("model", "?"))
        by_model[model] = by_model.get(model, 0.0) + float(
            e.get("payload", {}).get("estimated_cost", 0.0) or 0.0)
    total_cost = sum(by_model.values())

    def cell(e: dict[str, Any], col: str) -> str:
        value: Any
        if col == "payload":
            import json

            value = json.dumps(e.get("payload", {}), ensure_ascii=False)
        else:
            value = e.get(col, "")
        return html.escape(str(value))[:300]

    def table(events: list[dict[str, Any]], cols: tuple[str, ...]) -> str:
        if not events:
            return '<p class="empty">（本窗无记录）</p>'
        head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
        body = "".join(
            "<tr>" + "".join(f"<td>{cell(e, c)}</td>" for c in cols)
            + "</tr>"
            for e in events)
        return (f"<table><thead><tr>{head}</tr></thead>"
                f"<tbody>{body}</tbody></table>")

    model_rows = "".join(
        f"<tr><td>{html.escape(m)}</td><td>{v:.6f}</td></tr>"
        for m, v in sorted(by_model.items()))
    empty_td = ('<tr><td colspan=2 class="empty">（本窗无记录）'
                "</td></tr>")
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>VastaCore 审计报告</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;color:#1c2430;
background:#f6f7f9}}header{{background:#10233f;color:#fff;
padding:14px 20px}}main{{max-width:1100px;margin:16px auto;padding:0 12px}}
section{{background:#fff;border:1px solid #e3e7ee;border-radius:8px;
padding:14px;margin-bottom:14px}}h2{{font-size:15px;margin:0 0 10px;
color:#33445c}}table{{width:100%;border-collapse:collapse;font-size:12px}}
th,td{{text-align:left;padding:5px 8px;border-bottom:1px solid #eef1f5}}
th{{color:#66788f}}.meta{{font-size:12px;color:#66788f}}
.empty{{color:#99a5b5;font-size:12px}}</style></head><body>
<header>VastaCore 企业审计报告
<div class=meta>窗 {_fmt_ts(export.window['start'])} ~ \
{_fmt_ts(export.window['end'])}｜\
{html.escape(export.scope['tenant_id'])}:\
{html.escape(export.scope['project_id'])}｜\
事件 {export.total_events}｜工件引用 {len(export.artifact_refs)}｜\
导出人 {html.escape(export.exported_by)}｜\
生成于 {_fmt_ts(export.generated_at)}</div></header>
<main>
<section><h2>① 时间线（全审计流按 ts）</h2>
{table(timeline, ('ts', 'type', 'seq', 'payload'))}</section>
<section><h2>② 批准（approvals）</h2>
{table(approvals, ('ts', 'type', 'payload'))}</section>
<section><h2>③ 访问拒绝（access_denied / throttled）</h2>
{table(denies, ('ts', 'type', 'seq'))}</section>
<section><h2>④ 事故（incidents）</h2>
{table(incidents, ('ts', 'type', 'seq'))}</section>
<section><h2>⑤ 成本（billing）</h2>
<p class=meta>总计 {total_cost:.6f}（估算口径 basis 见各记录）</p>
<table><thead><tr><th>模型</th><th>累计成本</th></tr></thead>
<tbody>{model_rows or empty_td}</tbody></table></section>
</main></body></html>"""


__all__ = ["AUDIT_STREAMS", "AuditExport", "AuditExportQuery",
           "export_audit_json", "export_audit_json_traced",
           "render_audit_html"]
