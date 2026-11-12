"""Domain Studio 初版（Story 9.13，FR-028，G5——UJ-2）。

领域专家不写代码参与治理的只读为主 Web 面：

- 认知图浏览：主张清单（状态/置信/依赖计数）/ 详情（上游/下游）/
  冲突清单；
- 证据下钻：Run 时间线（事件概要 + 证据引用计数）+ 复现包下载
  （Epic 4 export_repro_bundle 复用——不含密钥与无关租户数据）；
- 批量影响分析入口：环境升级受影响清单**预览**（9.11
  impact_analysis 只读调用——预览零副作用，执行走 CLI/服务）；
- 专家写操作（审核/标注）：**经 HTTP 服务走事件留痕——UI 零旁路
  （AD-2）**；审核复用 9.5 批准流（record_approval 五要素 →
  cognition.accept/dispute）；标注 claim.annotated 纯留痕；
- 挂载式装配：``mount_studio(app, store=..., token=...)``——与业务
  服务同 app 同 token（数据面零匿名）；HTML 自包含零构建（Epic 4
  自包含 Replay 同形态）。
"""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response


def mount_studio(
    app: FastAPI, *,
    store: Any,
    token: str,
    tenant_id: str = "t-default",
    project_id: str = "p-default",
    principal_resolver: Any | None = None,
) -> None:
    """把 Studio 路由挂到既有 app（token 与业务面一致——零旁路）。

    Story 10.8：principal_resolver 给定时启用 RBAC（读=cognition:read、
    写=cognition:write——review/annotate 需 operator+；缺省共享 token）。"""
    from vasta_cognition.cognition import CognitionService

    cognition = CognitionService(
        store, tenant_id=tenant_id, project_id=project_id)

    from fastapi import Depends as _Depends

    from ..governance.rbac import require_role as _require_role

    _rbac = principal_resolver is not None
    _read_dep = _Depends(_require_role(
        "cognition", "read", resolver=principal_resolver, store=store,
        tenant_id=tenant_id, project_id=project_id)) if _rbac else None
    _write_dep = _Depends(_require_role(
        "cognition", "write", resolver=principal_resolver, store=store,
        tenant_id=tenant_id, project_id=project_id)) if _rbac else None

    def require_token(request: Request) -> None:
        auth = request.headers.get("Authorization", "")
        # 评审修复 F9：非 ASCII 凭据/token 下 str 比较抛 TypeError→500；
        # 两侧 encode 后 compare_digest（bytes 形态接受任意字节）
        if not hmac.compare_digest(auth.encode("utf-8", "surrogateescape"),
                                   f"Bearer {token}".encode(
                                       "utf-8", "surrogateescape")):
            raise HTTPException(status_code=401, detail="invalid token")

    def _claim_or_404(claim_id: str) -> Any:
        claim = cognition.get(claim_id)
        if claim is None:
            raise HTTPException(
                status_code=404, detail=f"claim {claim_id!r} not found")
        return claim

    # ---- 认知图浏览（只读）----
    @app.get("/studio/api/claims",
             dependencies=[_read_dep or Depends(require_token)])
    async def claims() -> list[dict[str, Any]]:
        cognition.refresh()  # 评审修复 F8：跨实例写入后的投影刷新
        items = []
        for c in cognition._claims.values():  # noqa: SLF001 ——SDK 域只读
            downstream = sum(
                1 for o in cognition._claims.values()  # noqa: SLF001
                if c.claim_id in o.depends_on)
            items.append({
                "claim_id": c.claim_id, "memory_type": c.memory_type,
                "statement": c.statement, "status": c.status,
                "confidence": c.confidence, "version": c.version,
                "scope": c.scope, "depends_on": len(c.depends_on),
                "downstream": downstream,
                "run_id": c.run_id,
            })
        return items

    @app.get("/studio/api/claims/{claim_id}",
             dependencies=[_read_dep or Depends(require_token)])
    async def claim_detail(claim_id: str) -> dict[str, Any]:
        cognition.refresh()
        claim = _claim_or_404(claim_id)
        downstream = [
            o.claim_id for o in cognition._claims.values()  # noqa: SLF001
            if claim_id in o.depends_on]
        return {"claim": claim.model_dump(), "downstream": downstream}

    @app.get("/studio/api/conflicts",
             dependencies=[_read_dep or Depends(require_token)])
    async def conflicts() -> list[dict[str, Any]]:
        """冲突清单（cognition 流重放 claim.conflict_detected）。"""
        found: list[dict[str, Any]] = []
        for event in store.iter_run_events(
                "cognition", tenant_id=tenant_id,
                project_id=project_id):  # 评审修复 H2：租户过滤
            if event.type == "claim.conflict_detected":
                found.append(dict(event.payload))
        return found

    # ---- 证据下钻（只读）----
    @app.get("/studio/api/runs/{run_id}/timeline",
             dependencies=[Depends(require_token)])
    async def run_timeline(run_id: str) -> dict[str, Any]:
        events = list(store.iter_run_events(
            run_id, tenant_id=tenant_id,
            project_id=project_id))  # 评审修复 H2：租户过滤
        if not events:
            raise HTTPException(
                status_code=404, detail=f"run {run_id!r} not found")
        return {
            "run_id": run_id, "total_events": len(events),
            "events": [{
                "seq": e.seq, "type": e.type, "ts": e.ts.isoformat(),
                "artifact_refs": len(e.payload.get("artifact_refs", [])),
                "payload_keys": sorted(e.payload.keys()),
            } for e in events],
        }

    @app.get("/studio/api/runs/{run_id}/repro",
             dependencies=[Depends(require_token)])
    async def run_repro(run_id: str) -> Response:
        """复现包下载（events JSON Lines——Epic 4 导出复用）。"""
        from vasta_storage.replay import export_repro_bundle

        try:
            bundle, bundle_bytes = await export_repro_bundle(
                store, run_id, tenant_id=tenant_id,
                project_id=project_id)
        except Exception as exc:  # noqa: BLE001 ——统一 404 语义
            raise HTTPException(
                status_code=404, detail=str(exc)) from exc
        return Response(
            content=bundle_bytes,
            media_type="application/x-ndjson",
            headers={"Content-Disposition":
                     f'attachment; filename="{run_id}-events.jsonl"'},
        )

    # ---- 批量影响分析入口（只读预览——执行走 revalidate_claims）----
    @app.get("/studio/api/impact",
             dependencies=[_read_dep or Depends(require_token)])
    async def impact_preview(k: str, v: str) -> dict[str, Any]:
        from ..governance.revalidation import impact_analysis

        cognition.refresh()  # 评审修复 F8
        affected = impact_analysis(cognition, {k: v})
        return {
            "affected_scope": {k: v},
            "count": len(affected),
            "claims": [{
                "claim_id": c.claim_id, "statement": c.statement,
                "confidence": c.confidence, "status": c.status,
                "depends_on": c.depends_on,
            } for c in affected],
        }

    # ---- 专家写操作（事件留痕 + 批准流——UI 零旁路）----
    @app.post("/studio/api/claims/{claim_id}/review",
              dependencies=[_write_dep or Depends(require_token)])
    async def review_claim(claim_id: str, body: dict[str, Any],
                           request: Request) -> dict[str, Any]:
        """审核：先落批准（9.5 五要素）再执行 cognition 判定。
        approve → claim.accepted；reject → claim.disputed（理由入
        counterevidence）。终态主张拒审（cognition 状态机守卫）。"""
        from vasta_protocols.errors import VastaError

        from ..governance.approvals import record_approval

        cognition.refresh()  # 终态判定不基于陈旧投影
        _claim_or_404(claim_id)
        decision = body.get("decision")
        # AC：approver 携带真实身份——RBAC 认证主体注入（依赖工厂
        # 写入 request.state.principal；body 省略时取主体、显式传值
        # 须与主体一致防冒名）
        authenticated = getattr(request.state, "principal", None)
        auth_user = getattr(authenticated, "user", None)
        approver = body.get("approver") or auth_user
        if not approver:
            raise HTTPException(status_code=400,
                                detail="approver 必填（RBAC 主体或 body.approver）")
        if auth_user and body.get("approver") and body["approver"] != auth_user:
            raise HTTPException(status_code=403,
                                detail=f"approver 冒名：认证主体为 {auth_user!r}")
        reason = body.get("reason")
        valid = (decision in ("approve", "reject")
                 and isinstance(approver, str) and approver
                 and isinstance(reason, str))
        if not valid:
            # 评审修复 F21：类型校验（非 str 不再 str() 强转入审计流）
            raise HTTPException(
                status_code=400,
                detail="decision 须 approve|reject；approver/reason 须为"
                       "非空字符串")
        approval = await record_approval(
            store, tool="claim.review",
            args={"claim_id": claim_id, "decision": decision,
                  "reason": reason},
            approver=approver, scope=f"{tenant_id}:{project_id}",
            ttl_s=3600, tenant_id=tenant_id, project_id=project_id,
        )
        try:
            if decision == "approve":
                await cognition.accept(claim_id)
            else:
                await cognition.dispute(
                    claim_id, [f"domain-expert:{approver}:{reason}"])
        except VastaError as exc:
            raise HTTPException(
                status_code=409,
                detail=(f"批准已留痕（{approval.approval_id}）但判定"
                        f"被状态机拒绝：{exc.message}"),
            ) from exc
        return {
            "claim_id": claim_id,
            "status": cognition.get(claim_id).status,
            "approval_id": approval.approval_id,
        }

    @app.post("/studio/api/claims/{claim_id}/annotate",
              dependencies=[_write_dep or Depends(require_token)])
    async def annotate_claim(claim_id: str, body: dict[str, Any],
                             request: Request) -> dict[str, Any]:
        """标注：claim.annotated 纯留痕（旁注不是判定——判定走 review）。"""
        from vasta_protocols.errors import VastaError

        cognition.refresh()
        _claim_or_404(claim_id)
        note = body.get("note")
        authenticated = getattr(request.state, "principal", None)
        auth_user = getattr(authenticated, "user", None)
        annotator = body.get("annotator") or auth_user
        valid = (isinstance(note, str) and note
                 and isinstance(annotator, str) and annotator)
        if not valid:
            raise HTTPException(
                status_code=400, detail="note 与 annotator 须为非空字符串")
        if auth_user and body.get("annotator") and                 body["annotator"] != auth_user:
            raise HTTPException(
                status_code=403,
                detail=f"annotator 冒名：认证主体为 {auth_user!r}")
        try:
            await cognition.annotate(claim_id, note, annotator=annotator)
        except VastaError as exc:
            raise HTTPException(status_code=409, detail=exc.message) from exc
        return {"claim_id": claim_id, "annotated": True}

    # ---- 页面（自包含 HTML——零构建）----
    @app.get("/studio/", dependencies=[Depends(require_token)])
    async def studio_page(request: Request) -> Response:
        return Response(content=_render_html(), media_type="text/html")


def _render_html() -> str:
    """自包含单页（原生 fetch；token 由 /studio/?token= 注入会话）。"""
    return """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>VastaCore Domain Studio</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;background:#f6f7f9;color:#1c2430}
header{background:#10233f;color:#fff;padding:12px 20px;font-size:18px}
main{max-width:1100px;margin:16px auto;padding:0 12px}
section{background:#fff;border:1px solid #e3e7ee;border-radius:8px;
padding:14px;margin-bottom:14px}
h2{font-size:15px;margin:0 0 10px;color:#33445c}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #eef1f5}
th{color:#66788f;font-weight:600}
button{cursor:pointer;border:1px solid #c6d0dd;background:#fff;
border-radius:6px;padding:4px 10px;font-size:12px}
button:hover{background:#f0f4f9}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;
font-size:11px;background:#e8eef7}
.badge.accepted{background:#dcf5e3}.badge.disputed{background:#fde8e8}
.badge.refuted{background:#f3d6d6}.badge.proposed{background:#eef1f5}
input{padding:5px 8px;border:1px solid #c6d0dd;border-radius:6px}
.row{display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
pre{background:#f6f7f9;padding:8px;border-radius:6px;font-size:12px;
overflow:auto;max-height:340px}
</style></head><body>
<header>VastaCore Domain Studio <span style="font-size:12px;opacity:.7">
认知图 · 证据下钻 · 影响分析（只读为主；写操作走批准流留痕）</span></header>
<main>
<section><h2>主张（认知图）</h2><div class="row">
<input id="q" placeholder="按 statement 过滤…">
</div><table><thead><tr><th>ID</th><th>类型</th><th>陈述</th>
<th>状态</th><th>置信</th><th>依赖/被依赖</th><th>Run</th></tr></thead>
<tbody id="claims"></tbody></table></section>
<section><h2>冲突</h2><div id="conflicts">（无）</div></section>
<section><h2>影响分析（环境升级预览）</h2><div class="row">
<input id="ik" placeholder="scope 键（如 region）" style="width:160px">
<input id="iv" placeholder="值（如 prod）" style="width:160px">
<button onclick="runImpact()">预览受影响主张</button></div>
<div id="impact"></div></section>
<section><h2>证据下钻</h2><div class="row">
<input id="rid" placeholder="Run ID" style="width:280px">
<button onclick="loadTimeline()">时间线</button>
<button onclick="downloadRepro()">复现包下载</button></div>
<pre id="timeline">—</pre></section>
</main>
<script>
const TOKEN = new URLSearchParams(location.search).get("token") || "";
const H = {"Authorization": "Bearer " + TOKEN};
const api = p => fetch(p, {headers: H}).then(r => {
  if (!r.ok) throw new Error(r.status + " " + p);
  return r.json();
});
// 评审修复 F10：所有插值先转义（statement 等源自模型输出——
// innerHTML 直插是存储型 XSS）
const esc = v => String(v).replace(/[&<>"']/g, c => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
})[c]);
async function loadClaims() {
  const q = document.getElementById("q").value;
  const rows = (await api("/studio/api/claims")).filter(
    c => !q || c.statement.includes(q));
  document.getElementById("claims").innerHTML = rows.map(c => `
    <tr><td>${esc(c.claim_id)}</td><td>${esc(c.memory_type)}</td>
    <td>${esc(c.statement)}</td>
    <td><span class="badge ${esc(c.status)}">${esc(c.status)}</span></td>
    <td>${c.confidence.toFixed(2)}</td>
    <td>${c.depends_on}/${c.downstream}</td>
    <td>${c.run_id ?
      `<button onclick="drill('${esc(c.run_id)}')">${esc(c.run_id)}</button>`
      : "—"}
    </td></tr>`).join("") || "<tr><td colspan=7>（无主张）</td></tr>";
}
async function loadConflicts() {
  const cs = await api("/studio/api/conflicts");
  document.getElementById("conflicts").innerHTML = cs.length
    ? cs.map(c => `<div class="badge disputed">冲突</div>
      ${c.claim_ids.map(esc).join(" vs ")}（scope: ${esc(c.scope_key)}，
      由 ${esc(c.triggered_by)} 触发）`).join("<br>")
    : "（无活跃冲突）";
}
async function runImpact() {
  const k = document.getElementById("ik").value,
        v = document.getElementById("iv").value;
  if (!k || !v) { alert("scope 键值都要填"); return; }
  const r = await api(`/studio/api/impact?k=${k}&v=${v}`);
  document.getElementById("impact").innerHTML = r.count === 0
    ? "（该范围无受影响主张）"
    : `<b>${r.count} 条受影响（含依赖传播）：</b><ul>` +
      r.claims.map(c =>
        `<li>${esc(c.claim_id)} · ${esc(c.statement)} · 置信 ${c.confidence}
         · <span class="badge ${esc(c.status)}">${esc(c.status)}</span></li>`
      ).join("") + "</ul>";
}
function drill(rid) {
  document.getElementById("rid").value = rid;
  loadTimeline();
}
async function loadTimeline() {
  const rid = document.getElementById("rid").value;
  if (!rid) { alert("填 Run ID"); return; }
  try {
    const t = await api(`/studio/api/runs/${rid}/timeline`);
    document.getElementById("timeline").textContent =
      t.events.map(e => `#${e.seq} ${e.type} ` +
        (e.artifact_refs ? `[${e.artifact_refs} 证据] ` : "") +
        e.payload_keys.join(",")).join("\\n");
  } catch (e) { document.getElementById("timeline").textContent =
    "未找到该 Run：" + e.message; }
}
function downloadRepro() {
  const rid = document.getElementById("rid").value;
  if (!rid) { alert("填 Run ID"); return; }
  fetch(`/studio/api/runs/${rid}/repro`, {headers: H})
    .then(r => { if (!r.ok) throw new Error(r.status); return r.blob(); })
    .then(b => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(b);
      a.download = rid + "-events.jsonl"; a.click();
    }).catch(e => alert("导出失败：" + e.message));
}
document.getElementById("q").addEventListener("input", loadClaims);
loadClaims(); loadConflicts();
</script></body></html>"""


__all__ = ["mount_studio"]
