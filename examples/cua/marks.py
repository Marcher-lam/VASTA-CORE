"""Set-of-Mark 渲染：原始截图 + AX 元素表 → 编号标记图（带血缘）。

证据语义（对齐平台 AD-3 的「原始—派生」分层）：
- 原始截图是不可变证据（CAS，sha256 寻址）；
- 本模块产出的标记图是**派生**（编号来自 AX 枚举那一刻的快照），
  落 store 时走 save_derived 记血缘（原图 sha → 标记图）；
- VLM 只看标记图；点击反解走 marks 表的 AX path——像素坐标永远
  不是证据链的一环。
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

from .ax import AxElement

#: 标记配色：可交互=绿、文本=灰（问题只问编号，颜色仅助读）。
_INTERACTIVE_FILL = (22, 163, 74, 230)     # #16a34a
_TEXT_FILL = (100, 116, 139, 200)          # #64748b
_OUTLINE = (255, 255, 255, 255)
_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)


def _font(size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size_px)
        except OSError:
            continue
    return ImageFont.load_default()


def build_marks(elements: list[AxElement], scale: float,
                screen_pt: tuple[float, float],
                *, max_marks: int = 80) -> list[dict]:
    """从 AX 元素表筛出编号候选（点→像素换算 + 去重叠 + 截断）。

    返回 marks 记录（mark 编号 → AX path/几何/语义），供渲染与点击反解。
    """
    scr_w, scr_h = screen_pt
    cand: list[AxElement] = []
    seen_frames: set[tuple[int, int, int, int]] = set()
    # 可交互优先（同帧去重时 interactive 赢：排序键先行）
    ranked = sorted(
        elements, key=lambda e: (not e.interactive, -(e.w or 0) * (e.h or 0)),
    )
    for e in ranked:
        if None in (e.x, e.y, e.w, e.h):
            continue
        if not (e.interactive or e.role in ("AXStaticText", "AXImage", "AXGroup")):
            continue
        # 太小/太大无意义（<8pt 是噪音；>屏幕 90% 是窗口壳）
        if e.w < 8 or e.h < 8 or e.w > scr_w * 0.9 or e.h > scr_h * 0.9:
            continue
        frame = (round(e.x), round(e.y), round(e.w), round(e.h))
        if frame in seen_frames:
            continue
        seen_frames.add(frame)
        cand.append(e)
        if len(cand) >= max_marks:
            break
    # 稳定编号：按阅读顺序（上→下、左→右）
    cand.sort(key=lambda e: (e.y or 0, e.x or 0))
    return [
        {
            "mark": i + 1,
            "role": e.role,
            "title": e.title,
            "value": str(e.value) if e.value is not None else None,
            "interactive": e.interactive,
            "x_pt": e.x, "y_pt": e.y, "w_pt": e.w, "h_pt": e.h,
            "path": list(e.path),
        }
        for i, e in enumerate(cand)
    ]


def render_marked(png_bytes: bytes, marks: list[dict],
                  scale: float) -> bytes:
    """在截图上叠加编号框与编号牌，返回 PNG 字节。"""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    line_w = max(1, round(2 * scale))
    # 实测（2026-11）：11pt 偏小易读错相邻牌；外置牌会与上一行按钮
    # 视觉打架——13pt + 框内左上（probe 10/10 的形态）为最优
    font_px = max(14, round(13 * scale))
    font = _font(font_px)
    for m in marks:
        x = m["x_pt"] * scale
        y = m["y_pt"] * scale
        w = m["w_pt"] * scale
        h = m["h_pt"] * scale
        fill = _INTERACTIVE_FILL if m["interactive"] else _TEXT_FILL
        draw.rectangle((x, y, x + w, y + h),
                       outline=_OUTLINE, width=line_w)
        label = str(m["mark"])
        lbox = draw.textbbox((0, 0), label, font=font)
        tw, th = lbox[2] - lbox[0], lbox[3] - lbox[1]
        pad = max(2.0, th * 0.3)
        bw, bh = tw + 2 * pad, th + 2 * pad
        draw.rectangle((x, y, x + bw, y + bh), fill=fill,
                       outline=_OUTLINE, width=max(1, line_w // 2))
        draw.text((x + pad, y + pad), label,
                  fill=(255, 255, 255, 255), font=font)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def find_mark(marks: list[dict], mark: int) -> dict | None:
    """编号 → mark 记录（点击反解入口）。"""
    for m in marks:
        if m["mark"] == mark:
            return m
    return None


def crop_window(png_bytes: bytes, elements: list, win, scale: float,
                ) -> tuple[bytes, list]:
    """裁剪到目标窗口（活动窗感知策略），元素坐标平移到窗内原点。

    win: 窗口 AxElement（x/y/w/h 为点）。中心落在窗外的元素剔除。
    裁剪是确定性派生：crop 区域与原图一并落证据库。
    """
    from dataclasses import replace

    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    x0 = max(0, int(win.x * scale))
    y0 = max(0, int(win.y * scale))
    x1 = min(img.width, int((win.x + win.w) * scale))
    y1 = min(img.height, int((win.y + win.h) * scale))
    cropped = img.crop((x0, y0, x1, y1))
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    inside = []
    for e in elements:
        if None in (e.x, e.y, e.w, e.h):
            continue
        cx, cy = e.x + e.w / 2, e.y + e.h / 2
        if win.x <= cx <= win.x + win.w and win.y <= cy <= win.y + win.h:
            inside.append(replace(e, x=e.x - win.x, y=e.y - win.y))
    return buf.getvalue(), inside


__all__ = ["build_marks", "crop_window", "find_mark", "render_marked"]
