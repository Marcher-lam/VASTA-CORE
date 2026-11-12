"""模型五维能力探测（Story 8.5，FR-003，G3）。

行为探测，不信任自声明：每个能力用可验证的探测请求打真实 generate()，
按应答判定；探测异常 fail-closed（按无该能力处理，不猜测）。
声明与行为不一致 → 行为胜出且差异入报告。

五维与方法（协议 v0.1 面内的诚实边界）：
- vision：图像密标回显（image-marker-echo）
- structured_output：严格 JSON 往返（json-roundtrip）
- tool_calling：工具 schema 产出（tool-schema-emit）
- streaming：可选 generate_stream 分块（协议 v0.1 无流式面——可选方法探测）
- context：短程针探（needle-short）+ 声明窗口交叉记录（非全窗口扫描）
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.protocols import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
)

#: 探测密标（vision 用；渲染进**真实 PNG 像素**——真 VLM 从图里读出；
#: 替身从 context['marker'] 模拟回显——context 是适配器侧管线数据，
#: 不进 prompt，真实模型拿不到提示）。
_MARKER = "VASTA-VISION-7Q4"

#: 密标字符集的 5×7 点阵字形（同源 evidence.engines._FONT5X7 的子集
#: 就地内嵌——models 与 evidence 子包互独立，10.1 层契约不许跨引）。
_GLYPHS: dict[str, tuple[str, ...]] = {
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "N": ("10001", "10001", "11001", "10101", "10011", "10001", "10001"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
}


def _marker_png_b64() -> str:
    """渲染含密标的真实 PNG（白底黑字、左下角、3× 点阵放大）。

    真实可解码——区别于历史形态（伪 b64 尾缀回显，仅替身可答）；
    确定性（无字体/时间依赖）。"""
    import base64
    import io

    from PIL import Image

    scale, gap = 3, 3
    text_w = len(_MARKER) * (5 * scale + gap)
    img = Image.new("RGB", (max(text_w + 8, 160), 48), "white")
    x0, y0 = 4, 48 - 7 * scale - 4  # 左下角
    for i, ch in enumerate(_MARKER):
        glyph = _GLYPHS.get(ch)
        if glyph is None:
            continue
        gx = x0 + i * (5 * scale + gap)
        for r in range(7):
            for c in range(5):
                if glyph[r][c] == "1":
                    for dy in range(scale):
                        for dx in range(scale):
                            img.putpixel(
                                (gx + c * scale + dx, y0 + r * scale + dy),
                                (0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

_PROBE_NAMES = ("vision", "structured_output", "tool_calling",
                "streaming", "context")


class ProbeOutcome(BaseModel):
    """单维探测结果（三态 + 方法 + 置信度 + 证据摘要）。"""

    model_config = ConfigDict(extra="forbid")

    capability: str
    status: str = Field(description="detected | not_detected | probe_failed")
    supported: bool
    method: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = Field(default="", description="证据摘要（截断）")


class CapabilityReport(BaseModel):
    """五维能力清单 + 声明交叉核对。"""

    model_config = ConfigDict(extra="forbid")

    declared: ModelCapabilities
    probes: dict[str, ProbeOutcome]
    discrepancies: list[str] = Field(default_factory=list)

    def effective_capabilities(self) -> ModelCapabilities:
        """有效能力视图：以行为为准（fail-closed）。"""
        declared = self.declared.model_dump()
        declared["vision"] = self.probes["vision"].supported
        declared["structured_output"] = self.probes["structured_output"].supported
        declared["tool_calling"] = self.probes["tool_calling"].supported
        declared["streaming"] = self.probes["streaming"].supported
        return ModelCapabilities.model_validate(declared)


def _detected(capability: str, method: str, evidence: str,
              agree_with_declaration: bool) -> ProbeOutcome:
    return ProbeOutcome(
        capability=capability, status="detected", supported=True, method=method,
        confidence=0.9 if agree_with_declaration else 0.7,
        evidence=evidence[:160],
    )


def _not_detected(capability: str, method: str, evidence: str) -> ProbeOutcome:
    return ProbeOutcome(
        capability=capability, status="not_detected", supported=False,
        method=method, confidence=0.0, evidence=evidence[:160],
    )


def _failed(capability: str, method: str, error: BaseException) -> ProbeOutcome:
    return ProbeOutcome(
        capability=capability, status="probe_failed", supported=False,
        method=method, confidence=0.0,
        evidence=f"{type(error).__name__}: {error}"[:160],
    )


async def _ask(adapter: Any, prompt: str, context: dict[str, Any],
               timeout_s: float = 10.0) -> ModelResponse:
    import asyncio

    return await asyncio.wait_for(
        adapter.generate(ModelRequest(prompt=prompt, context=context)),
        timeout=timeout_s,
    )


async def _probe_vision(adapter: Any, declared: bool) -> ProbeOutcome:
    resp = await _ask(
        adapter,
        "读出图中左下角标记并以 marker=<标记> 形式回答",
        {"probe": "vision", "image_b64": _marker_png_b64(),
         "image_mime": "image/png", "marker": _MARKER},
    )
    ok = _MARKER in resp.content
    return (
        _detected("vision", "image-marker-echo", f"content={resp.content!r}", declared)
        if ok else
        _not_detected("vision", "image-marker-echo", f"content={resp.content!r}")
    )


async def _probe_structured(adapter: Any, declared: bool) -> ProbeOutcome:
    resp = await _ask(
        adapter,
        '只输出严格 JSON：{"ok": true, "n": 7}，不要任何其他文字',
        {"probe": "structured", "schema": {"ok": "boolean", "n": "integer"}},
    )
    try:
        payload = json.loads(resp.content)
        ok = payload.get("ok") is True and payload.get("n") == 7
    except (json.JSONDecodeError, AttributeError):
        ok = False
    return (
        _detected("structured_output", "json-roundtrip",
                  f"parsed={payload if ok else resp.content[:60]!r}", declared)
        if ok else
        _not_detected("structured_output", "json-roundtrip",
                      f"unparseable={resp.content[:60]!r}")
    )


async def _probe_tool_call(adapter: Any, declared: bool) -> ProbeOutcome:
    resp = await _ask(
        adapter,
        "调用工具 probe_tool 计算 x=1，只输出 JSON："
        '{"tool": "probe_tool", "args": {"x": 1}}',
        {"probe": "tool_call",
         "tools": [{"name": "probe_tool", "parameters": {"x": "int"}}]},
    )
    try:
        payload = json.loads(resp.content)
        ok = payload.get("tool") == "probe_tool"
    except (json.JSONDecodeError, AttributeError):
        ok = False
    return (
        _detected("tool_calling", "tool-schema-emit",
                  f"call={payload.get('tool')!r}", declared)
        if ok else
        _not_detected("tool_calling", "tool-schema-emit",
                      f"content={resp.content[:60]!r}")
    )


async def _probe_streaming(adapter: Any, declared: bool) -> ProbeOutcome:
    stream = getattr(adapter, "generate_stream", None)
    if stream is None:
        return _not_detected(
            "streaming", "optional-generate_stream",
            "适配器未提供可选方法 generate_stream（协议 v0.1 无流式面）",
        )
    chunks = 0
    try:
        async for _chunk in stream(
            ModelRequest(prompt="stream probe", context={})
        ):
            chunks += 1
            if chunks >= 2:
                break
    except Exception as exc:  # noqa: BLE001 ——中途损坏不是"支持流式"
        return _failed("streaming", "optional-generate_stream", exc)
    return (
        _detected("streaming", "optional-generate_stream",
                  "chunks>=2", declared)
        if chunks >= 2 else
        _not_detected("streaming", "optional-generate_stream", f"chunks={chunks}")
    )


async def _probe_context(adapter: Any, declared: bool) -> ProbeOutcome:
    filler = "\n".join(f"filler line {i}: 无关内容" for i in range(64))
    needle = "NEEDLE-9Z8"
    resp = await _ask(
        adapter,
        f"下文藏有一个 needle 标记，只回答 needle=<标记>：\n{filler}\n"
        f"第 32 行后插入标记 {needle}\n结束。",
        {"probe": "context", "needle": needle},
    )
    ok = needle in resp.content
    return (
        _detected("context", "needle-short",
                  f"needle_found={ok}", declared)
        if ok else
        _not_detected("context", "needle-short", f"content={resp.content[:60]!r}")
    )


_PROBES = {
    "vision": (_probe_vision, "vision"),
    "structured_output": (_probe_structured, "structured_output"),
    "tool_calling": (_probe_tool_call, "tool_calling"),
    "streaming": (_probe_streaming, "streaming"),
    "context": (_probe_context, None),  # context_window 是声明值，非布尔探测
}


async def probe_capabilities(
    adapter: Any, *, probe_timeout_s: float = 10.0
) -> CapabilityReport:
    """五维行为探测（fail-closed；不信任自声明）。

    评审修复：每维探测经 wait_for 超时（原先挂起的 provider 会永久阻塞）；
    capabilities 属性缺失/形态异常 → 全维 fail-closed（原先裸 AttributeError）。
    诚实边界：vision 探测载荷为**真实渲染 PNG**（密标在像素内——真 VLM
    可解码读出；替身从 context['marker'] 模拟回显）；context 维无布尔
    声明可交叉，置信度固定 0.9 为单侧口径。"""
    try:
        declared: ModelCapabilities = adapter.capabilities
    except Exception as exc:  # noqa: BLE001 ——适配器自声明面异常也 fail-closed
        all_failed = {
            name: _failed(name, "adapter-declared", exc) for name in _PROBE_NAMES
        }
        return CapabilityReport(
            declared=ModelCapabilities(), probes=all_failed,
            discrepancies=["declared: 适配器 capabilities 属性不可读"],
        )
    declared_map = {
        "vision": declared.vision,
        "structured_output": declared.structured_output,
        "tool_calling": declared.tool_calling,
        "streaming": declared.streaming,
    }
    probes: dict[str, ProbeOutcome] = {}
    import asyncio

    for name, (fn, declared_key) in _PROBES.items():
        try:
            probes[name] = await asyncio.wait_for(
                fn(adapter,
                   declared_map[declared_key] if declared_key else True),
                timeout=probe_timeout_s,
            )
        except Exception as exc:  # noqa: BLE001 ——fail-closed：异常/超时=无能力
            probes[name] = _failed(name, _method_of(fn), exc)

    discrepancies: list[str] = []
    for name, declared_flag in declared_map.items():
        if declared_flag and not probes[name].supported:
            discrepancies.append(
                f"{name}: 自声明支持但行为探测未证实（行为胜出，fail-closed）"
            )
        elif not declared_flag and probes[name].supported:
            discrepancies.append(f"{name}: 自声明不支持但行为探测证实（低估）")
    return CapabilityReport(
        declared=declared, probes=probes, discrepancies=discrepancies,
    )


def _method_of(fn: Any) -> str:
    return {
        _probe_vision: "image-marker-echo",
        _probe_structured: "json-roundtrip",
        _probe_tool_call: "tool-schema-emit",
        _probe_streaming: "optional-generate_stream",
        _probe_context: "needle-short",
    }[fn]


async def save_capability_report(
    store: Any, report: CapabilityReport, *,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> str:
    """报告 JSON 入 CAS 留痕（AD-3）；返回 sha256。"""
    return await store.save_artifact(
        report.model_dump_json().encode("utf-8"),
        mime="application/json", source="capability-probe",
        classification="capability-probe",
        tenant_id=tenant_id, project_id=project_id,
    )


__all__ = ["CapabilityReport", "ProbeOutcome", "probe_capabilities",
           "save_capability_report"]
