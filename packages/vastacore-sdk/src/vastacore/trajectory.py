"""轨迹导入：外部历史日志 → 事件族 + CAS（Story 8.2，FR-002 第六种接入形态）。

零侵入接入：已有生产 Agent 的团队把执行日志倒进证据库，即得检索/回放/离线评估。

映射语义（13 族封闭集内，不发明新族）：
- OpenAI messages 风格：user 消息 → observation.external（内容入 CAS）；
  assistant 文本 → observation.decision；tool_calls/tool_call →
  action.contracted + action.executed（结果入 CAS，imported=True 诚实标记）；
- 自定义 JSONL（显式 type）：observation→observation.<kind>、action 同上、
  note→memory.note；

诚实边界：导入动作**不做六段链伪装**——payload 带 ``imported: true``，
audit_six_segment 将其如实分类为非受辖链（历史记录 ≠ VastaCore 执行）。

fail-closed（all-or-nothing）：任一记录非法 → 整体拒入（零事件写入），
错误含记录序号与原因。时间戳为合成确定性（固定基准 + 序号递增，AD-16：
导入器非安全机制，不用墙钟）。
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.envelope import EventEnvelope
from vasta_protocols.errors import VastaError
from vasta_protocols.ids import new_event_id

#: 合成时间戳基准（确定性：与导入时刻无关）。
_BASE_TS = datetime(2026, 1, 1, tzinfo=UTC)

_TENANT = "t-default"
_PROJECT = "p-default"


class ImportSummary(BaseModel):
    """导入结果摘要。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    records: int = Field(ge=0, description="输入记录数")
    events: int = Field(ge=0, description="落库事件数（含 run.created/completed）")
    artifacts: int = Field(ge=0, description="入 CAS 的内容/响应数")
    source_format: str


def _invalid(index: int, reason: str) -> VastaError:
    return VastaError(
        code="trajectory.invalid_record",
        message=f"记录 #{index} 非法：{reason}（整体拒入，未写入任何事件）",
    )


def _load_records(source: Any) -> list[dict[str, Any]]:
    """输入形态归一：list[str | dict] / JSONL 文本（bytes）/ 文件路径。

    评审修复：文件逐行解析错误同样包装为含序号的 trajectory.invalid_record
    （原先裸 JSONDecodeError 无序号）；文件读取容 BOM（utf-8-sig）。"""
    records: list[Any]
    if isinstance(source, (str, Path)):
        text = Path(source).read_text(encoding="utf-8-sig")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        records = []
        for i, ln in enumerate(lines):
            try:
                records.append(json.loads(ln))
            except json.JSONDecodeError as exc:
                raise _invalid(i, f"不是合法 JSON: {exc}") from exc
    elif isinstance(source, bytes):
        decoded = source.decode("utf-8-sig")
        lines = [ln for ln in decoded.splitlines() if ln.strip()]
        records = []
        for i, ln in enumerate(lines):
            try:
                records.append(json.loads(ln))
            except json.JSONDecodeError as exc:
                raise _invalid(i, f"不是合法 JSON: {exc}") from exc
    else:
        records = list(source)
    out: list[dict[str, Any]] = []
    for i, rec in enumerate(records):
        if isinstance(rec, str):
            try:
                rec = json.loads(rec)
            except json.JSONDecodeError as exc:
                raise _invalid(i, f"不是合法 JSON: {exc}") from exc
        if not isinstance(rec, dict):
            raise _invalid(i, f"记录必须是 JSON 对象，得到 {type(rec).__name__}")
        out.append(rec)
    return out


#: 合成事件 type 的 kind 段合法词形（与 EventEnvelope 的 _EVENT_TYPE_RE 对齐：
#: 全小写、字母开头——评审修复：原 isalnum 校验放行大写/数字开头/CJK，
#: 导致非法 kind 在写入阶段才被信封拒绝，击穿 all-or-nothing）。
_KIND_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _check_kind(index: int, kind: str) -> str:
    if not _KIND_RE.match(kind):
        raise _invalid(
            index,
            f"observation.kind {kind!r} 非法（须全小写字母开头，"
            "与事件信封词形一致）",
        )
    return kind


# ---- 记录 → 「待发事件」中间表示（先全量校验后写入）----

async def _plan_records(
    records: list[dict[str, Any]], source_format: str
) -> list[dict[str, Any]]:
    """把输入记录解析为事件计划：[{type, payload, cas: bytes|None}]。

    校验失败立即抛（调用方保证此刻零写入）。"""
    plan: list[dict[str, Any]] = []
    # tool_call 结果按 call_id 关联到此前声明的调用
    pending_calls: dict[str, dict[str, Any]] = {}

    for i, rec in enumerate(records):
        rtype = rec.get("type")
        if source_format == "openai":
            if rtype == "message" and rec.get("role") in ("user", "system"):
                content = rec.get("content")
                plan.append({
                    "type": "observation.external",
                    "payload": {"kind": "external", "source": "import",
                                "role": rec.get("role"), "imported": True},
                    "cas": _as_bytes(content),
                })
            elif rtype == "message" and rec.get("role") == "assistant":
                calls = rec.get("tool_calls") or []
                if not isinstance(calls, list):
                    raise _invalid(i, "tool_calls 必须是列表")
                for call in calls:
                    if not isinstance(call, dict) or not call.get("name"):
                        raise _invalid(i, "tool_calls 项缺 name")
                    args = call.get("arguments") or {}
                    if not isinstance(args, dict):
                        raise _invalid(i, "tool_calls.arguments 必须是对象")
                    cid = call.get("id") or f"call_{len(plan)}"
                    pending_calls[cid] = {"tool": call["name"], "args": args}
                    plan.append({
                        "type": "action.contracted",
                        "payload": {"tool": call["name"], "args": args,
                                    "imported": True, "call_id": cid},
                        "cas": None,
                    })
                if calls:
                    continue  # 有工具调用的助手消息不再发文本观察
                content = rec.get("content")
                if content is None:
                    raise _invalid(i, "assistant 消息缺 content 且无 tool_calls")
                plan.append({
                    "type": "observation.decision",
                    "payload": {"kind": "decision", "imported": True},
                    "cas": _as_bytes(content),
                })
            elif rtype == "tool_call":
                cid = rec.get("call_id")
                if not cid or cid not in pending_calls:
                    raise _invalid(i, f"tool_call 缺 call_id 或无对应声明: {cid!r}")
                declared = pending_calls[cid]
                output = rec.get("output") or {}
                plan.append({
                    "type": "action.executed",
                    "payload": {"tool": declared["tool"],
                                "ok": bool(output.get("ok", True)),
                                "imported": True, "call_id": cid},
                    "cas": _as_bytes(rec.get("output")),
                    "result_for": declared["tool"],
                })
            else:
                raise _invalid(i, f"openai 格式不支持 type={rtype!r}")
        elif source_format == "generic":
            if rtype == "observation":
                kind = _check_kind(i, str(rec.get("kind") or "decision"))
                plan.append({
                    "type": f"observation.{kind}",
                    "payload": {"kind": kind, "imported": True,
                                **({"source": rec["source"]} if rec.get("source") else {})},
                    "cas": _as_bytes(rec.get("detail")),
                })
            elif rtype == "action":
                if not rec.get("tool"):
                    raise _invalid(i, "action 记录缺 tool")
                args = rec.get("args") or {}
                if not isinstance(args, dict):
                    raise _invalid(i, "action.args 必须是对象")
                plan.append({
                    "type": "action.contracted",
                    "payload": {"tool": rec["tool"], "args": args, "imported": True},
                    "cas": None,
                })
                plan.append({
                    "type": "action.executed",
                    "payload": {"tool": rec["tool"], "ok": bool(rec.get("ok", True)),
                                "imported": True},
                    "cas": _as_bytes(rec.get("result")),
                    "result_for": rec["tool"],
                })
            elif rtype == "note":
                if not rec.get("text"):
                    raise _invalid(i, "note 记录缺 text")
                plan.append({
                    "type": "memory.note",
                    "payload": {"kind": "note", "imported": True},
                    "cas": _as_bytes(rec.get("text")),
                })
            else:
                raise _invalid(i, f"generic 格式不支持 type={rtype!r}")
        else:
            raise VastaError(
                code="trajectory.unknown_format",
                message=f"未知 source_format {source_format!r}（支持: openai/generic）",
            )
    return plan


def _as_bytes(content: Any) -> bytes | None:
    if content is None:
        return None
    if isinstance(content, bytes):
        return content
    return json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")


async def import_trajectory(
    store: Any,
    source: Any,
    *,
    run_id: str,
    source_format: str = "openai",
    tenant_id: str = _TENANT,
    project_id: str = _PROJECT,
) -> ImportSummary:
    """把外部轨迹导入证据库（all-or-nothing fail-closed）。

    source：记录列表（dict/JSON 字符串）、JSONL 文本、或文件路径。"""
    records = _load_records(source)
    if list(store.iter_run_events(run_id, tenant_id=tenant_id,
                                  project_id=project_id)):
        raise VastaError(
            code="trajectory.run_exists",
            message=f"run {run_id!r} 已有事件，拒绝覆盖导入（事件溯源不可变）",
        )
    plan = await _plan_records(records, source_format)  # 全量校验（此时零写入）

    seq = 0
    parent: str | None = None
    artifact_count = 0

    async def emit(type_: str, payload: dict[str, Any]) -> None:
        nonlocal seq, parent
        envelope = EventEnvelope.model_validate({
            "run_id": run_id, "seq": seq, "type": type_,
            "parent_event_id": parent,
            "ts": _BASE_TS + timedelta(seconds=seq),  # 合成确定性时间戳
            "tenant_id": tenant_id, "project_id": project_id,
            "event_id": new_event_id(),
            "payload": payload,
        })
        await store.append_event(envelope)
        parent = envelope.event_id
        seq += 1

    await emit("run.created", {"imported": True, "source_format": source_format,
                               "records": len(records)})
    for item in plan:
        payload = dict(item["payload"])
        blob = item.get("cas")
        if blob is not None:
            sha = await store.save_artifact(
                blob, mime="application/json", source="trajectory-import",
                classification="imported",
                tenant_id=tenant_id, project_id=project_id,
            )
            artifact_count += 1
            payload["artifact_refs"] = [sha]
            if item.get("result_for"):
                payload["result_ref"] = sha
        await emit(item["type"], payload)
    await emit("run.completed", {"imported": True})

    return ImportSummary(
        run_id=run_id, records=len(records), events=seq,
        artifacts=artifact_count, source_format=source_format,
    )


__all__ = ["ImportSummary", "import_trajectory"]
