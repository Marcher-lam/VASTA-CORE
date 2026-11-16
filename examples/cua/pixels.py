"""VISTA 吸收序②：read_pixels 视觉取证原语（R0 只读，零 VLM 调用）。

语义移植自 VISTA ``core/tools.py`` / ``core/session.py``：区域均分
rows×cols 网格，采样每格**中心像素**（列偏移 ``(2c+1)*W//(2*C)``，行
同理）；输出「符号调色板 + 每采样行紧凑字符串」；**不对齐、不变换、
不解释**——比较与判读交给调用方（P6 取证用 ``diff_region``）。

坐标约定：PIL 像素坐标（原点左上），region 相对所给图像整体；与
SoM 标记的 pt 坐标映射在模型侧接线（吸收序③）时标定。
确定性：纯函数——同帧字节 + 同参数 → 逐位一致输出（重放兼容）。
上限对齐 VISTA：单次采样 ≤ 4096。
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image

MAX_SAMPLES = 4096  # VISTA 单 view 采样上限
_SYMBOLS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass(frozen=True)
class Region:
    """图像内矩形（像素坐标，原点左上）。"""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.x < 0 or self.y < 0:
            raise ValueError(f"region 原点为负：({self.x}, {self.y})")
        if self.width < 1 or self.height < 1:
            raise ValueError(f"region 尺寸非法：{self.width}×{self.height}")

    @classmethod
    def from_pt(cls, x_pt: float, y_pt: float, w_pt: float, h_pt: float,
                *, scale: float) -> Region:
        """pt 坐标 → 像素 Region（scale 逐帧实测：截图 px 宽 / 屏幕 pt
        宽，惯例同 scene.py 的 Scene.scale——SoM 标记坐标换算入口）。"""
        return cls(x=int(round(x_pt * scale)), y=int(round(y_pt * scale)),
                   width=int(round(w_pt * scale)),
                   height=int(round(h_pt * scale)))


@dataclass(frozen=True)
class PixelReadout:
    """采样读出（行主序）——frozen：可作事件负载（审计链）。"""

    rows: int
    cols: int
    rgb: tuple[tuple[int, int, int], ...]
    row_strings: tuple[str, ...]
    palette: dict[str, str]  # symbol → #rrggbb

    def as_event(self) -> dict[str, object]:
        """审计链负载（JSON 可序列化投影）。"""
        return {"rows": self.rows, "cols": self.cols,
                "rgb": [list(c) for c in self.rgb],
                "row_strings": list(self.row_strings),
                "palette": dict(self.palette)}


@dataclass(frozen=True)
class RegionDiff:
    """两帧同参数采样对比——「屏到底变没变」的独立观测结论。"""

    changed: bool
    changed_cells: int
    total_cells: int


def read_pixels(image_bytes: bytes, region: Region, *, rows: int,
                cols: int) -> PixelReadout:
    """区域中心像素采样（VISTA 语义：只读出、不判读）。"""
    if rows < 1 or cols < 1:
        raise ValueError(f"rows/cols 须 ≥1：{rows}×{cols}")
    if rows * cols > MAX_SAMPLES:
        raise ValueError(
            f"采样数超上限：{rows}×{cols} = {rows * cols} > {MAX_SAMPLES}")
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    if (region.x + region.width > img.width
            or region.y + region.height > img.height):
        raise ValueError(
            f"region 越界：({region.x}, {region.y}, "
            f"{region.width}×{region.height}) 超图像 {img.width}×{img.height}")
    px = img.load()
    samples: list[tuple[int, int, int]] = []
    for r in range(rows):
        y = region.y + (2 * r + 1) * region.height // (2 * rows)
        for c in range(cols):
            x = region.x + (2 * c + 1) * region.width // (2 * cols)
            samples.append(px[x, y])
    hexes = [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in samples]
    palette: dict[str, str] = {}
    by_hex: dict[str, str] = {}
    row_strings: list[str] = []
    for i in range(rows):
        symbols: list[str] = []
        for j in range(cols):
            h = hexes[i * cols + j]
            if h not in by_hex:  # 首见顺序分配——确定性
                symbol = (_SYMBOLS[len(palette)]
                          if len(palette) < len(_SYMBOLS) else h)
                by_hex[h] = symbol
                palette[symbol] = h
            symbols.append(by_hex[h])
        row_strings.append("".join(symbols))
    return PixelReadout(rows=rows, cols=cols, rgb=tuple(samples),
                        row_strings=tuple(row_strings), palette=palette)


def diff_region(before: bytes, after: bytes, region: Region, *, rows: int,
                cols: int) -> RegionDiff:
    """两帧同参数采样逐格对比（P6 取证：区分「点击未生效」与
    「AX 读数偏差」的不依赖 AX 的观测通道）。"""
    a = read_pixels(before, region, rows=rows, cols=cols)
    b = read_pixels(after, region, rows=rows, cols=cols)
    changed = sum(1 for u, v in zip(a.rgb, b.rgb, strict=True) if u != v)
    return RegionDiff(changed=changed > 0, changed_cells=changed,
                      total_cells=rows * cols)
