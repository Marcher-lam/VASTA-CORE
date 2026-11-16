"""VISTA 吸收序③：inspect + history 模型侧投影（R0 只读）。

VISTA ``inspect`` / ``history`` 语义移植，坐标系对齐本仓：
- 帧按 **CAS ref（sha256）** 寻址——强于 VISTA turn 索引，天然确定性
  重放兼容；
- 区域为像素坐标；SoM 标记的 pt 坐标经 ``Region.from_pt(scale)``
  换算（scale 逐帧实测，惯例同 scene.py）；
- 多 view ≤16、按请求顺序返回（VISTA 上限与顺序保证）；
- 放大用**最近邻**（VISTA "without smoothing"——防插值伪造像素），
  但保持纵横比而非 VISTA 的 1024 方形化：CUA 窗口裁剪非方形，方形
  化会几何失真（有据偏离，非漏译）；
- ``history_lines``：start 含 / end 排 / 越界钳制 / limit 封顶
  （VISTA history 语义）——紧凑行投影，供上下文预算受限时替代全量
  JSON 历史（吸收序④ LoopContext 的构件）。
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from PIL import Image

from .pixels import Region

MAX_VIEWS = 16  # VISTA 单次 inspect view 上限


def crop_view(frame_bytes: bytes, region: Region, *,
              view_size: int = 512) -> bytes:
    """裁剪 + 最近邻放大（NEAREST），保持纵横比，返回 PNG 字节。

    region 越界显式拒绝——PIL crop 越界是静默黑边填充，必须 fail-closed。
    """
    img = Image.open(io.BytesIO(frame_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    if (region.x + region.width > img.width
            or region.y + region.height > img.height):
        raise ValueError(
            f"region 越界：({region.x}, {region.y}, "
            f"{region.width}×{region.height}) 超图像 {img.width}×{img.height}")
    crop = img.crop((region.x, region.y,
                     region.x + region.width, region.y + region.height))
    w, h = crop.size
    s = view_size / max(w, h)
    resized = crop.resize((max(1, round(w * s)), max(1, round(h * s))),
                          Image.Resampling.NEAREST)
    buf = io.BytesIO()
    resized.save(buf, format="PNG")
    return buf.getvalue()


@dataclass(frozen=True)
class ViewSpec:
    """一个回看视图：frame_bytes / frame_ref 二选一 + 区域 + 标签。"""

    region: Region
    frame_bytes: bytes | None = None
    frame_ref: str | None = None
    label: str = ""

    def __post_init__(self) -> None:
        if (self.frame_bytes is None) == (self.frame_ref is None):
            raise ValueError("frame_bytes 与 frame_ref 必须二选一")
        if self.frame_ref is not None and len(self.frame_ref) < 8:
            raise ValueError(f"CAS ref 非法：{self.frame_ref!r}")


async def inspect_views(
    store: Any, views: list[ViewSpec], *, view_size: int = 512,
    tenant_id: str | None = None, project_id: str | None = None,
) -> list[tuple[str, bytes]]:
    """多视图回看：CAS ref 取帧 → 裁剪放大 → (label, PNG) 请求序返回。

    store 为 SqliteStorage（frame_bytes 直供的 view 不触 store，可传
    None）。缺失 ref 由存储层 ArtifactNotFoundError fail-closed。
    """
    if len(views) > MAX_VIEWS:
        raise ValueError(f"views 超上限：{len(views)} > {MAX_VIEWS}")
    if store is None and any(v.frame_ref is not None for v in views):
        raise ValueError("frame_ref 视图需要 store（CAS 取件）——store 为 None")
    out: list[tuple[str, bytes]] = []
    for v in views:
        data = v.frame_bytes
        if data is None:
            data = await store.get_artifact(v.frame_ref, tenant_id=tenant_id,
                                            project_id=project_id)
        out.append((v.label, crop_view(data, v.region, view_size=view_size)))
    return out


def history_lines(history: list[dict], *, start: int | None = None,
                  end: int | None = None, limit: int = 64) -> tuple[str, ...]:
    """交互记录 → 紧凑行投影（VISTA history 分页语义）。

    start 含、end 排（缺省到头尾）、越界钳制、limit 封顶取窗头；
    缺字段的记录容错投影（部分记录在错误路径上只写了前几键）。
    """
    s = max(0, start or 0)
    e = len(history) if end is None else min(max(end, s), len(history))
    window = history[s:e][:max(1, limit)]
    lines: list[str] = []
    for h in window:
        parts = [f"s{h.get('step', '?')}", repr(h.get('button', '?')),
                 f"@{h.get('mark', '?')}", f"expect={h.get('expect', '?')}"]
        if "display_after" in h:
            parts.append(f"→{h['display_after']}")
        if "verified" in h:
            parts.append("✓" if h["verified"] else "✗")
        lines.append(" ".join(parts))
    return tuple(lines)
