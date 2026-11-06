"""Console 最小可用面（Story 10.14，NFR-012/013 收口）。

运维/治理的 HTML 面——服务端渲染、自包含零构建零 JS（Epic 4 自包含
Replay 与 Studio 同形态）：

- **NFR-012 无障碍**：跳转主内容链接（首个可聚焦元素）、全部交互用
  原生元素（a/form/button——键盘原生可达，无 JS 处理器）、表单
  label 显式关联、表格 caption + th scope、语义地标（main/nav）、
  焦点可见样式、WCAG 对比色（近黑/白底）；
- **NFR-013 国际化**：双语目录（zh-CN 缺省 / en）——html lang、
  UI 串、时间格式、数字分组、**事件与策略决定描述目录化**
  （describe_event——事件语义本身不动，展示层本地化）；
- **可读对比**（NFR-012 字面）：同 run 两事件的 payload 按点分路径
  展平——变更/仅左/仅右/相同四组两栏对照（before/after 观察对比）。

装配：``mount_console(app, store=..., token=...)``——与业务面同
token（Authorization 头；零匿名面与 Studio 一致——浏览器直访需
带头部的代理/扩展，认证模型不为此放宽）。
"""

from __future__ import annotations

import hmac
import html as _html
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

#: UI 串目录（NFR-013：UI 可本地化）。
_CATALOGS: dict[str, dict[str, str]] = {
    "zh-CN": {
        "title": "VastaCore 控制台",
        "home": "运行检索",
        "skip": "跳到主内容",
        "run_label": "Run 标识",
        "go": "查看时间线",
        "streams": "系统流入口",
        "timeline": "事件时间线",
        "compare": "可读对比",
        "back_timeline": "返回时间线",
        "back_home": "返回首页",
        "seq": "序号",
        "type": "事件类型",
        "time": "时间",
        "summary": "概要",
        "compare_link": "对比前后",
        "before": "前（before）",
        "after": "后（after）",
        "group_changed": "变更项",
        "group_only_before": "仅前项存在",
        "group_only_after": "仅后项存在",
        "group_same": "相同项",
        "path": "字段路径",
        "lang_switch": "English",
        "footer": "事件语义不随语言切换变化（NFR-013）",
    },
    "en": {
        "title": "VastaCore Console",
        "home": "Run lookup",
        "skip": "Skip to main content",
        "run_label": "Run ID",
        "go": "View timeline",
        "streams": "System streams",
        "timeline": "Event timeline",
        "compare": "Readable comparison",
        "back_timeline": "Back to timeline",
        "back_home": "Back to home",
        "seq": "Seq",
        "type": "Event type",
        "time": "Time",
        "summary": "Summary",
        "compare_link": "Compare before/after",
        "before": "Before",
        "after": "After",
        "group_changed": "Changed",
        "group_only_before": "Only in before",
        "group_only_after": "Only in after",
        "group_same": "Unchanged",
        "path": "Field path",
        "lang_switch": "中文",
        "footer": "Event semantics stay stable across locales (NFR-013)",
    },
}

#: 事件/策略决定描述目录（展示层本地化——事件类型与 payload 不动）。
_EVENT_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "zh-CN": {
        "run.started": "运行启动",
        "run.completed": "运行完成",
        "run.failed": "运行失败",
        "observation.transition": "环境过渡观察",
        "observation.decision": "决策点观察",
        "action.contracted": "动作契约建立（六段链第一段）",
        "action.policy_cleared": "策略放行",
        "action.policy_denied": "策略拒绝",
        "action.executed": "动作已执行",
        "verification.passed": "核验通过",
        "verification.deviated": "核验偏差",
        "action.approval_requested": "请求人工批准",
        "action.approved": "人工已批准",
    },
    "en": {
        "run.started": "Run started",
        "run.completed": "Run completed",
        "run.failed": "Run failed",
        "observation.transition": "Environment transition observed",
        "observation.decision": "Decision point observed",
        "action.contracted": "Action contract established (segment 1/6)",
        "action.policy_cleared": "Policy cleared",
        "action.policy_denied": "Policy denied",
        "action.executed": "Action executed",
        "verification.passed": "Verification passed",
        "verification.deviated": "Verification deviated",
        "action.approval_requested": "Human approval requested",
        "action.approved": "Human approved",
    },
}

_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_CSS = """
body{font-family:system-ui,sans-serif;color:#1a1a1a;background:#ffffff;
     margin:0;line-height:1.5}
a:focus,button:focus,input:focus{outline:3px solid #b35c00;outline-offset:2px}
.skip{position:absolute;left:-9999px}
.skip:focus{position:static}
table{border-collapse:collapse;margin:1rem 0}
th,td{border:1px solid #767676;padding:.4rem .6rem;text-align:left}
caption{font-weight:700;padding:.5rem 0}
nav a{margin-right:1rem}
.changed{background:#fdf3e7}
"""


def _t(locale: str, key: str) -> str:
    return _CATALOGS.get(locale, _CATALOGS["zh-CN"])[key]


def format_ts(ts: str, locale: str) -> str:
    """时间本地化（stdlib 手工格式化——不依赖系统 locale）。"""
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return str(ts)
    if locale == "en":
        return (f"{dt.day:02d} {_MONTHS_EN[dt.month - 1]} {dt.year}, "
                f"{dt.hour % 12 or 12:02d}:{dt.minute:02d}:{dt.second:02d} "
                f"{'AM' if dt.hour < 12 else 'PM'}")
    return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d} " \
           f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"


def format_number(value: int, locale: str) -> str:
    """数字本地化（千位分组机制位——locale 差异由目录承载）。"""
    return f"{value:,}"


def describe_event(event_type: str, locale: str) -> str:
    """事件/策略描述本地化：目录命中给本地话术，未命中回退原始类型
    （事件语义稳定——本层只做展示转换，NFR-013）。"""
    return _EVENT_DESCRIPTIONS.get(locale, {}) \
        .get(event_type, event_type)


def _esc(value: Any) -> str:
    return _html.escape(str(value), quote=True)


def _layout(locale: str, title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="{_esc(locale)}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title><style>{_CSS}</style></head>
<body>
<a class="skip" href="#main">{_esc(_t(locale, "skip"))}</a>
<main id="main">
{body}
</main>
</body>
</html>"""


def render_home(locale: str, *, run_hint: str = "") -> str:
    go = _t(locale, "go")
    body = f"""
<h1>{_esc(_t(locale, "title"))}</h1>
<nav aria-label="{_esc(_t(locale, "home"))}">
  <a href="/console?lang={_esc(locale)}">{_esc(_t(locale, "home"))}</a>
  <a href="/console?lang={'en' if locale == 'zh-CN' else 'zh-CN'}"
     hreflang="{'en' if locale == 'zh-CN' else 'zh-CN'}"
     >{_esc(_t(locale, "lang_switch"))}</a>
</nav>
<form method="get" action="/console/runs/__lookup__">
  <label for="run-id">{_esc(_t(locale, "run_label"))}</label>
  <input id="run-id" name="run_id" value="{_esc(run_hint)}" required>
  <button type="submit">{_esc(go)}</button>
</form>
<p>{_esc(_t(locale, "footer"))}</p>"""
    return _layout(locale, _t(locale, "title"), body)


def render_timeline(locale: str, run_id: str, events: list[Any]) -> str:
    t = _t(locale, "title")
    body = f"""
<h1>{_esc(_t(locale, 'timeline'))}</h1>
<nav aria-label="{_esc(_t(locale, 'back_home'))}">
  <a href="/console?lang={_esc(locale)}">{_esc(_t(locale, 'back_home'))}</a>
</nav>
<p>run: <strong>{_esc(run_id)}</strong></p>
<table>
<caption>{_esc(_t(locale, 'timeline'))} — {format_number(len(events), locale)}</caption>
<thead><tr>
  <th scope="col">{_esc(_t(locale, 'seq'))}</th>
  <th scope="col">{_esc(_t(locale, 'type'))}</th>
  <th scope="col">{_esc(_t(locale, 'time'))}</th>
  <th scope="col">{_esc(_t(locale, 'summary'))}</th>
  <th scope="col">{_esc(_t(locale, 'compare'))}</th>
</tr></thead>
<tbody>"""
    for e in events:
        described = describe_event(e.type, locale)
        compare = ""
        if e.type.startswith("action.executed") or \
                e.type.startswith("verification."):
            compare = (f'<a href="/console/runs/{_esc(run_id)}'
                       f'/compare?before={e.seq - 1}&after={e.seq}'
                       f'&amp;lang={_esc(locale)}">'
                       f'{_esc(_t(locale, "compare_link"))}</a>')
        body += (f"<tr><td>{e.seq}</td><td>{_esc(e.type)}</td>"
                 f"<td>{_esc(format_ts(e.ts, locale))}</td>"
                 f"<td>{_esc(described)}</td><td>{compare}</td></tr>")
    body += "</tbody></table>"
    return _layout(locale, f"{t} — {run_id}", body)


def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    else:
        out[prefix or "value"] = obj
    return out


def render_compare(locale: str, run_id: str,
                   before: Any, after: Any) -> str:
    a = _flatten(before.payload if hasattr(before, "payload") else before)
    b = _flatten(after.payload if hasattr(after, "payload") else after)
    shared = a.keys() & b.keys()
    changed = {k for k in shared if a[k] != b[k]}
    same = shared - changed
    only_a = a.keys() - b.keys()
    only_b = b.keys() - a.keys()

    def section(key: str, rows: list[tuple[str, Any, Any]]) -> str:
        if not rows:
            return ""
        label = _t(locale, key)
        body_rows = "".join(
            f"<tr class=\"{'changed' if key == 'group_changed' else ''}\">"
            f"<th scope=\"row\">{_esc(path)}</th>"
            f"<td>{_esc(va)}</td><td>{_esc(vb)}</td></tr>"
            for path, va, vb in rows)
        return (f"<table><caption>{_esc(label)}</caption>"
                f"<thead><tr><th scope=\"col\">{_esc(_t(locale, 'path'))}</th>"
                f"<th scope=\"col\">{_esc(_t(locale, 'before'))}</th>"
                f"<th scope=\"col\">{_esc(_t(locale, 'after'))}</th></tr></thead>"
                f"<tbody>{body_rows}</tbody></table>")

    body = f"""
<h1>{_esc(_t(locale, 'compare'))}</h1>
<nav aria-label="{_esc(_t(locale, 'back_timeline'))}">
  <a href="/console/runs/{_esc(run_id)}?lang={_esc(locale)}">
    {_esc(_t(locale, 'back_timeline'))}</a>
</nav>
{section("group_changed", [(k, a[k], b[k]) for k in sorted(changed)])}
{section("group_only_before", [(k, a[k], "—") for k in sorted(only_a)])}
{section("group_only_after", [(k, "—", b[k]) for k in sorted(only_b)])}
{section("group_same", [(k, a[k], b[k]) for k in sorted(same)])}"""
    return _layout(locale, f"{_t(locale, 'compare')} — {run_id}", body)


def mount_console(
    app: FastAPI, *,
    store: Any,
    token: str,
    tenant_id: str = "t-default",
    project_id: str = "p-default",
) -> None:
    """把 Console HTML 路由挂到既有 app（token 与业务面一致——零旁路）。"""

    def require_token(request: Request) -> None:
        auth = request.headers.get("Authorization", "")
        if not hmac.compare_digest(auth.encode("utf-8", "surrogateescape"),
                                   f"Bearer {token}".encode(
                                       "utf-8", "surrogateescape")):
            raise HTTPException(status_code=401, detail="invalid token")

    guarded = Depends(require_token)

    def _locale(request: Request) -> str:
        lang = request.query_params.get("lang", "zh-CN")
        return lang if lang in _CATALOGS else "zh-CN"

    def _events_or_404(run_id: str) -> list[Any]:
        events = list(store.iter_run_events(
            run_id, tenant_id=tenant_id, project_id=project_id))
        if not events:
            raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
        return events

    @app.get("/console", dependencies=[guarded],
             response_class=HTMLResponse)
    async def console_home(request: Request) -> str:
        return render_home(_locale(request))

    @app.get("/console/runs/__lookup__", dependencies=[guarded])
    async def console_lookup(request: Request):
        """原生表单落点：run_id 查询参数 → 重定向到时间线路由。"""
        from fastapi.responses import RedirectResponse

        run_id = request.query_params.get("run_id", "").strip()
        locale = _locale(request)
        if not run_id:
            return RedirectResponse(
                f"/console?lang={locale}", status_code=303)
        return RedirectResponse(
            f"/console/runs/{run_id}?lang={locale}", status_code=303)

    @app.get("/console/runs/{run_id}", dependencies=[guarded],
             response_class=HTMLResponse)
    async def console_timeline(run_id: str, request: Request) -> str:
        return render_timeline(_locale(request), run_id,
                               _events_or_404(run_id))

    @app.get("/console/runs/{run_id}/compare", dependencies=[guarded],
             response_class=HTMLResponse)
    async def console_compare(run_id: str, request: Request) -> str:
        events = _events_or_404(run_id)
        try:
            before = next(e for e in events
                          if e.seq == int(request.query_params["before"]))
            after = next(e for e in events
                         if e.seq == int(request.query_params["after"]))
        except (KeyError, StopIteration, ValueError) as exc:
            raise HTTPException(
                status_code=404, detail="before/after seq 不在此 run") from exc
        return render_compare(_locale(request), run_id, before, after)


__all__ = [
    "describe_event",
    "format_number",
    "format_ts",
    "mount_console",
    "render_compare",
    "render_home",
    "render_timeline",
]
