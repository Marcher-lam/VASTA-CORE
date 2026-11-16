"""Story va-2（吸收方案 §七 序②）：read_pixels 视觉取证原语（R0 只读）。

VISTA ``core/tools.py``/``session.py`` 语义移植：区域均分 rows×cols、
采样每格**中心像素**（偏移 ``(2c+1)*W//(2*C)``）、输出符号调色板 +
每采样行紧凑字符串；「不对齐、不变换、比较交给调用方」。首个消费者
是 P6 点击失灵调查（目标区域像素 diff——不依赖 AX 的独立观测通道）。
"""

from __future__ import annotations

import io

import pytest
from examples.cua.pixels import PixelReadout, Region, diff_region, read_pixels
from PIL import Image


def _png(pixels: dict[tuple[int, int], tuple[int, int, int]],
         size: tuple[int, int] = (4, 4)) -> bytes:
    """合成确定性 PNG（默认 4×4 黑底 + 指定坐标像素）。"""
    img = Image.new("RGB", size, (0, 0, 0))
    for (x, y), rgb in pixels.items():
        img.putpixel((x, y), rgb)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


GRADIENT = _png({(x, y): (x * 10, y * 10, 0) for x in range(4)
                 for y in range(4)})


# ---- AC1：中心像素采样公式（VISTA 偏移 (2c+1)*W//(2C)） ----

def test_center_sampling_full_region() -> None:
    out = read_pixels(GRADIENT, Region(0, 0, 4, 4), rows=2, cols=2)
    # 中心点：x=y=1,3 → (10,10,0),(30,10,0),(10,30,0),(30,30,0)
    assert out.rgb == ((10, 10, 0), (30, 10, 0), (10, 30, 0), (30, 30, 0))


def test_center_sampling_subregion() -> None:
    img = _png({(4, 4): (255, 0, 0)}, size=(8, 8))
    out = read_pixels(img, Region(2, 2, 4, 4), rows=1, cols=1)
    # 中心：x = 2 + (1*4)//2 = 4 → 唯一红点
    assert out.rgb == ((255, 0, 0),)


# ---- AC2：紧凑读出格式（调色板 + 每行符号串） ----

def test_row_strings_and_palette() -> None:
    img = _png({(1, 1): (255, 0, 0), (3, 1): (0, 255, 0),   # 采样中心
                (1, 3): (255, 0, 0), (3, 3): (0, 255, 0)})
    out = read_pixels(img, Region(0, 0, 4, 4), rows=2, cols=2)
    assert out.row_strings == ("ab", "ab")  # 两行同构
    assert sorted(out.palette) == sorted({"a": "#ff0000", "b": "#00ff00"})


def test_single_color_collapses_palette() -> None:
    solid = _png({}, size=(4, 4))
    out = read_pixels(solid, Region(0, 0, 4, 4), rows=3, cols=3)
    assert len(out.palette) == 1
    assert all(s == next(iter(out.palette)) for s in "".join(out.row_strings))


# ---- AC3：确定性（同帧同参数逐字节一致——重放兼容的前提） ----

def test_deterministic_across_calls() -> None:
    a = read_pixels(GRADIENT, Region(0, 0, 4, 4), rows=4, cols=4)
    b = read_pixels(GRADIENT, Region(0, 0, 4, 4), rows=4, cols=4)
    assert a == b  # frozen dataclass 全字段相等


# ---- AC4：参数校验（越界/超采样——错误信息可行动） ----

def test_region_out_of_bounds_raises() -> None:
    with pytest.raises(ValueError, match="越界"):
        read_pixels(GRADIENT, Region(2, 2, 4, 4), rows=1, cols=1)


def test_sample_cap_enforced() -> None:
    with pytest.raises(ValueError, match="4096"):
        read_pixels(GRADIENT, Region(0, 0, 4, 4), rows=64, cols=65)


def test_nonpositive_grid_rejected() -> None:
    with pytest.raises(ValueError):
        read_pixels(GRADIENT, Region(0, 0, 4, 4), rows=0, cols=1)


# ---- AC5：P6 取证——区域 diff（屏到底变没变的独立通道） ----

def test_diff_detects_change_inside_region() -> None:
    before = _png({(1, 1): (0, 0, 0)}, size=(4, 4))
    after = _png({(1, 1): (255, 255, 255)}, size=(4, 4))
    d = diff_region(before, after, Region(0, 0, 2, 2), rows=2, cols=2)
    assert d.changed and d.changed_cells == 1 and d.total_cells == 4


def test_diff_ignores_change_outside_region() -> None:
    before = _png({}, size=(4, 4))
    after = _png({(3, 3): (255, 0, 0)}, size=(4, 4))  # 区域外
    d = diff_region(before, after, Region(0, 0, 2, 2), rows=2, cols=2)
    assert not d.changed


def test_diff_identical_frames_zero_changes() -> None:
    d = diff_region(GRADIENT, GRADIENT, Region(0, 0, 4, 4), rows=2, cols=2)
    assert not d.changed and d.changed_cells == 0


def test_readout_is_plain_data() -> None:
    # frozen dataclass：可作为事件负载序列化（审计链要求）
    out = read_pixels(GRADIENT, Region(0, 0, 4, 4), rows=2, cols=2)
    assert isinstance(out, PixelReadout)
    assert len(out.rgb) == out.rows * out.cols == 4
