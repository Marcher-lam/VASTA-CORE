"""Story va-3（吸收方案 §七 序③）：inspect + history 模型侧投影。

VISTA ``inspect``（裁剪放大回看，"without smoothing"）与 ``history``
（分页回看交互记录）语义移植到本仓坐标系：
- 帧按 **CAS ref**（sha256）寻址——确定性重放兼容（强于 VISTA turn 索引）；
- 区域 = 像素坐标 Region；pt 坐标经 ``Region.from_pt(scale)`` 换算
  （scale 逐帧实测，惯例同 scene.py:48）；
- 多 view ≤16、按请求顺序返回（VISTA 上限与顺序保证）；
- 放大用**最近邻**（防插值伪造像素），保持纵横比（CUA 窗口裁剪非
  方形——与 VISTA 1024 方形的差异有据偏离，见 revisit.py 模块注）；
- history 分页：start 含 / end 排 / 越界钳制 / limit 封顶（VISTA 语义）。
"""

from __future__ import annotations

import io

import pytest
from examples.cua.pixels import Region
from examples.cua.revisit import (
    ViewSpec,
    crop_view,
    history_lines,
    inspect_views,
)
from PIL import Image

from vasta_storage import SqliteStorage


def _quadrant_png() -> bytes:
    """8×8 四象限：左上红 / 右上绿 / 左下蓝 / 右下黄（各 4×4）。"""
    img = Image.new("RGB", (8, 8))
    for x in range(8):
        for y in range(8):
            img.putpixel((x, y), (255, 0, 0) if x < 4 and y < 4 else
                         (0, 255, 0) if x >= 4 and y < 4 else
                         (0, 0, 255) if x < 4 else (255, 255, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


RED_PNG = _quadrant_png()


# ---- AC1：crop_view 裁剪 + 最近邻放大（无平滑伪像素） ----

def test_crop_view_quadrant_purity() -> None:
    out = crop_view(RED_PNG, Region(0, 0, 4, 4), view_size=64)
    img = Image.open(io.BytesIO(out))
    assert img.size == (64, 64)
    colors = {img.getpixel((x, y)) for x in range(64) for y in range(64)}
    assert colors == {(255, 0, 0)}  # 纯红——最近邻不混色


def test_crop_view_keeps_aspect_ratio() -> None:
    out = crop_view(RED_PNG, Region(0, 0, 4, 2), view_size=64)
    assert Image.open(io.BytesIO(out)).size == (64, 32)


def test_crop_view_returns_png_bytes() -> None:
    out = crop_view(RED_PNG, Region(4, 4, 4, 4), view_size=32)
    assert out[:8] == b"\x89PNG\r\n\x1a\n"


def test_crop_view_out_of_bounds_fails_closed() -> None:
    # PIL crop 越界是静默黑边填充——必须显式拒绝（fail-closed，VISTA
    # "尺寸不符拒绝渲染" 同精神）
    with pytest.raises(ValueError, match="越界"):
        crop_view(RED_PNG, Region(6, 6, 4, 4), view_size=8)


async def test_inspect_views_ref_without_store_fails_closed() -> None:
    views = [ViewSpec(frame_ref="a" * 64, region=Region(0, 0, 1, 1))]
    with pytest.raises(ValueError, match="store"):
        await inspect_views(None, views, view_size=8)


# ---- AC2：pt → px 换算（对齐 scene.scale 实测惯例） ----

def test_region_from_pt() -> None:
    r = Region.from_pt(10, 20, 5, 5, scale=2.0)
    assert (r.x, r.y, r.width, r.height) == (20, 40, 10, 10)


def test_region_from_pt_half_pixel_rounding() -> None:
    r = Region.from_pt(1.5, 0, 1, 1, scale=2.0)
    assert (r.x, r.y, r.width, r.height) == (3, 0, 2, 2)


# ---- AC3：CAS 寻址多 view（顺序保证 + 上限 + ref 取件） ----

async def test_inspect_views_order_and_bytes_view(tmp_path) -> None:
    views = [ViewSpec(frame_bytes=RED_PNG, region=Region(0, 0, 4, 4),
                      label="top-left"),
             ViewSpec(frame_bytes=RED_PNG, region=Region(4, 4, 4, 4),
                      label="bottom-right")]
    out = await inspect_views(None, views, view_size=16)
    assert [lbl for lbl, _ in out] == ["top-left", "bottom-right"]  # 请求序
    tl = Image.open(io.BytesIO(out[0][1])).convert("RGB")
    assert tl.getpixel((8, 8)) == (255, 0, 0)
    assert Image.open(io.BytesIO(out[1][1])).convert("RGB").getpixel(
        (8, 8)) == (255, 255, 0)


async def test_inspect_views_cas_ref_roundtrip(tmp_path) -> None:
    store = SqliteStorage(tmp_path / "s")
    ref = await store.save_artifact(RED_PNG, mime="image/png")
    out = await inspect_views(
        store, [ViewSpec(frame_ref=ref, region=Region(0, 0, 4, 4))],
        view_size=16)
    assert Image.open(io.BytesIO(out[0][1])).convert("RGB").getpixel(
        (8, 8)) == (255, 0, 0)  # ref → CAS 原件 → 裁剪放大


async def test_inspect_views_missing_ref_fails_closed(tmp_path) -> None:
    store = SqliteStorage(tmp_path / "s")
    with pytest.raises(Exception, match="be0000"):
        await inspect_views(
            store,
            [ViewSpec(frame_ref="be0000" + "0" * 56, region=Region(0, 0, 1, 1))],
            view_size=8)


async def test_inspect_views_cap_sixteen() -> None:
    views = [ViewSpec(frame_bytes=RED_PNG, region=Region(0, 0, 2, 2))
             for _ in range(17)]
    with pytest.raises(ValueError, match="16"):
        await inspect_views(None, views, view_size=8)


def test_viewspec_xor_validation() -> None:
    with pytest.raises(ValueError, match="二选一"):
        ViewSpec(frame_bytes=b"x", frame_ref="abc", region=Region(0, 0, 1, 1))
    with pytest.raises(ValueError, match="二选一"):
        ViewSpec(frame_bytes=None, frame_ref=None, region=Region(0, 0, 1, 1))


# ---- AC4：history 分页投影（start 含 / end 排 / 钳制 / limit） ----

HIST = [{"step": i + 1, "button": str(i + 1), "mark": i + 1,
         "expect": f"display={i + 1}", "display_after": str(i + 1),
         "verified": True} for i in range(5)]


def test_history_lines_window() -> None:
    lines = history_lines(HIST, start=1, end=4)
    assert len(lines) == 3
    assert lines[0].startswith("s2") and lines[2].startswith("s4")


def test_history_lines_clamps_and_limit() -> None:
    assert len(history_lines(HIST, start=-5, end=99)) == 5  # 越界钳制
    assert len(history_lines(HIST, limit=2)) == 2  # 封顶取窗头


def test_history_lines_marks_unverified() -> None:
    hist = [{**HIST[0], "verified": False}, HIST[1]]
    lines = history_lines(hist)
    assert "✗" in lines[0] and "✓" in lines[1]
    assert "expect=display=1" in lines[0]


def test_history_lines_tolerates_partial_records() -> None:
    assert len(history_lines([{"step": 1, "button": "7"}])) == 1
