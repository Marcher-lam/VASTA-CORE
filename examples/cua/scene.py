"""场景捕获：截图 → 窗口裁剪 → SoM 标记（probe/loop 共用管线）。

证据语义：全屏原图是原始证据；标记图是派生（供 VLM 感知）。
标记表（mark→AX path/几何）在窗口不动的前提下可跨步复用——
只重渲染标记图，不重枚举（AX 枚举 ~5s，截图 ~0.5s）。
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image

from .ax import (
    AxElement,
    activate_app,
    enumerate_elements,
    frontmost_app,
    screen_info,
    screenshot_png,
)
from .config import CuaConfig
from .marks import build_marks, crop_window, render_marked


@dataclass
class Scene:
    """一步感知的全部产物。"""

    shot: bytes            # 全屏原图（证据）
    scene: bytes           # 窗口裁剪
    marked: bytes          # 编号标记图（VLM 输入）
    marks: list[dict]      # 标记表（mark → path/几何/语义）
    scale: float
    win: AxElement
    elements: list[AxElement]


def capture_scene(app: str, cfg: CuaConfig, *,
                  elements: list[AxElement] | None = None,
                  marks: list[dict] | None = None) -> Scene:
    """捕获当前场景。复用 elements/marks 可省一次枚举（窗口未动时）。"""
    if frontmost_app() != app:
        activate_app(app)
    shot = screenshot_png()
    info = screen_info()
    scale = Image.open(io.BytesIO(shot)).width / info["pt_w"]
    if elements is None:
        elements = enumerate_elements(app, cfg)
    win = next((e for e in elements if e.path == (0,)), None)
    if win is not None and None not in (win.x, win.w):
        scene_png, in_elements = crop_window(shot, elements, win, scale)
        scene_pt = (win.w, win.h)
    else:  # 全屏兜底
        scene_png, in_elements = shot, elements
        scene_pt = (info["pt_w"], info["pt_h"])
    if marks is None:
        marks = build_marks(in_elements, scale, scene_pt,
                            max_marks=cfg.max_marks)
    marked = render_marked(scene_png, marks, scale)
    return Scene(shot=shot, scene=scene_png, marked=marked, marks=marks,
                 scale=scale, win=win, elements=elements)


__all__ = ["Scene", "capture_scene"]
