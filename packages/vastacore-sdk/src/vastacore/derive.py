"""多模态按需派生（Story 8.12，FR-015/016，G5）——要时才算，不默认全量。

- `DeriverRegistry` + `derive_on_demand`：显式请求才派生；派生经
  `save_derived`（血缘 + CAS，按需触发即留痕）；同 (source, kind, params)
  幂等同址、异参数不误去重；未注册 kind fail-closed、源缺失 fail-fast。
- 零依赖 deriver 四件（真实 OCR/ASR/Embedding 模型随 GUI Pack 接入，
  结构零变更——注册即用）：
  - `text_summary`：抽取式摘要（前 N 句）
  - `text_embedding`：确定性哈希词袋向量（演示级，非语义模型——如实标注）
  - `text_extract`：正则状态抽取
  - `media_window`：视频/音频清单时间窗切片 + 对齐键保留（多模态对齐的
    清单形态；不引入编解码依赖）
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict

from vasta_protocols.errors import VastaError

#: deriver：源字节 + 参数 → 派生字节（确定性要求——同输入同输出）。
Deriver = Callable[[bytes, dict[str, Any]], Awaitable[bytes]]


class DerivedRef(BaseModel):
    """派生结果引用。"""

    model_config = ConfigDict(extra="forbid")

    derived_sha256: str
    source_sha256: str
    kind: str
    params: dict[str, Any]


class DeriverRegistry:
    """派生器注册表（kind → deriver）。"""

    def __init__(self) -> None:
        self._derivers: dict[str, Deriver] = {}

    def register(self, kind: str, deriver: Deriver) -> None:
        if kind in self._derivers:
            raise VastaError(
                code="derive.duplicate_kind",
                message=f"deriver {kind!r} 已注册（不可覆盖）",
            )
        self._derivers[kind] = deriver

    def kinds(self) -> list[str]:
        return sorted(self._derivers)

    def get(self, kind: str) -> Deriver:
        deriver = self._derivers.get(kind)
        if deriver is None:
            raise VastaError(
                code="derive.unregistered_kind",
                message=(
                    f"派生类型 {kind!r} 未注册（fail-closed）——"
                    f"已注册: {self.kinds()}"
                ),
            )
        return deriver


async def derive_on_demand(
    store: Any,
    source_sha256: str,
    kind: str,
    params: dict[str, Any],
    *,
    registry: DeriverRegistry | None = None,
    transformer_version: str = "0.1.0",
    tenant_id: str = "t-default",
    project_id: str = "p-default",
) -> DerivedRef:
    """显式请求派生（不请求不派生）。"""
    reg = registry or default_registry()
    try:
        json.dumps(params, sort_keys=True, ensure_ascii=False)
    except TypeError as exc:
        raise VastaError(
            code="derive.bad_params",
            message=f"params 含不可 JSON 序列化的值: {exc}",
        ) from exc
    source = await store.get_artifact(
        source_sha256, tenant_id=tenant_id, project_id=project_id
    )  # 源缺失 → get_artifact fail-fast
    deriver = reg.get(kind)  # 未注册 → fail-closed
    payload = await deriver(source, dict(params))
    derived_sha = await store.save_derived(
        payload,
        source_sha256=source_sha256,
        transform=kind,
        params=dict(params),
        transformer_version=transformer_version,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    return DerivedRef(
        derived_sha256=derived_sha, source_sha256=source_sha256,
        kind=kind, params=dict(params),
    )


# ---- 零依赖 deriver ----

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VastaError(code="derive.bad_params", message=message)


async def _text_summary(payload: bytes, params: dict[str, Any]) -> bytes:
    """抽取式摘要：按句切分取前 N 句（确定性）。"""
    text = payload.decode("utf-8", errors="replace")
    max_sentences = int(params.get("max_sentences", 2))
    _require(max_sentences >= 1, f"max_sentences 须 ≥1，得到 {max_sentences}")
    sentences = [s.strip() for s in re.split(r"(?<=[。！？.!?\n])", text) if s.strip()]
    picked = sentences[:max_sentences]
    return "".join(picked).encode("utf-8")


async def _text_embedding(payload: bytes, params: dict[str, Any]) -> bytes:
    """确定性哈希词袋向量（演示级——非语义模型；同输入同输出）。"""
    dim = int(params.get("dim", 64))
    _require(dim >= 1, f"dim 须 ≥1，得到 {dim}")
    tokens = payload.decode("utf-8", errors="replace").split()
    vector = [0] * dim
    for token in tokens:
        bucket = int.from_bytes(
            hashlib.sha256(token.encode("utf-8")).digest()[:8], "big"
        ) % dim
        vector[bucket] += 1
    doc = {"vector": vector, "dim": dim, "tokens": len(tokens),
           "method": "hashing-bag-of-words(demo)"}
    return json.dumps(doc, ensure_ascii=False, sort_keys=True).encode("utf-8")


async def _text_extract(payload: bytes, params: dict[str, Any]) -> bytes:
    """正则状态抽取：fields={字段名: 正则} → 首个匹配。"""
    text = payload.decode("utf-8", errors="replace")
    fields: dict[str, str] = dict(params.get("fields", {}))
    extracted: dict[str, str | None] = {}
    for name, pattern in fields.items():
        try:
            matcher = re.compile(pattern)
        except re.error as exc:
            raise VastaError(
                code="derive.bad_params",
                message=f"字段 {name!r} 的正则非法: {exc}",
            ) from exc
        match = matcher.search(text)
        extracted[name] = match.group(0) if match else None
    return json.dumps(extracted, ensure_ascii=False,
                      sort_keys=True).encode("utf-8")


async def _media_window(payload: bytes, params: dict[str, Any]) -> bytes:
    """媒体清单时间窗切片：相交即入窗、边界裁剪、对齐键保留。"""
    try:
        manifest = json.loads(payload.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise VastaError(
            code="derive.bad_params",
            message=f"源不是合法媒体清单 JSON: {exc}",
        ) from exc
    from_s = float(params.get("from_s", 0))
    to_s = float(params.get("to_s", manifest.get("duration_s", 0)))
    _require(from_s < to_s, f"时间窗倒置: from_s={from_s} ≥ to_s={to_s}")
    segments = []
    for segment in manifest.get("segments", []):
        start, end = float(segment["start"]), float(segment["end"])
        if end <= from_s or start >= to_s:
            continue  # 不相交
        clipped = dict(segment)
        clipped["start"] = max(start, from_s)
        clipped["end"] = min(end, to_s)
        segments.append(clipped)  # 对齐键（align）原样保留
    window = {
        "kind": manifest.get("kind", "media"),
        "window": {"from_s": from_s, "to_s": to_s},
        "segments": segments,
        "source_duration_s": manifest.get("duration_s"),
    }
    return json.dumps(window, ensure_ascii=False,
                      sort_keys=True).encode("utf-8")


_DEFAULT_REGISTRY = DeriverRegistry()
for _kind, _deriver in (
    ("text_summary", _text_summary),
    ("text_embedding", _text_embedding),
    ("text_extract", _text_extract),
    ("media_window", _media_window),
):
    _DEFAULT_REGISTRY.register(_kind, _deriver)


def default_registry() -> DeriverRegistry:
    """默认注册表（四件零依赖 deriver）。"""
    return _DEFAULT_REGISTRY


__all__ = ["DerivedRef", "DeriverRegistry", "default_registry",
           "derive_on_demand"]
