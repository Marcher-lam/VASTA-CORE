"""生成合成架构图语料（3 张 PNG，PIL 手绘，内容忠实转录自 ARCHITECTURE-SPINE）。

诚实标注：这些图是原型为补齐「纯图像模态」语料而合成的（docs/ 本身无图），
内容来自 docs/architecture/.../ARCHITECTURE-SPINE.md 的 AD-1 / AD-8 / AD-4。
运行：uv run python -m examples.rag.make_figures
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "corpus"

_FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise RuntimeError("找不到中文字体（PingFang/Hiragino/STHeiti）")


class Canvas:
    def __init__(self, w: int, h: int, title: str) -> None:
        self.img = Image.new("RGB", (w, h), "white")
        self.d = ImageDraw.Draw(self.img)
        self.title_font = _font(30)
        self.font = _font(20)
        self.small = _font(16)
        self.d.text((w // 2, 34), title, fill="black",
                    font=self.title_font, anchor="mm")

    def box(self, xy: tuple[int, int, int, int], label: str, fill: str = "#EEF2FF",
            outline: str = "#3730A3", font: ImageFont.FreeTypeFont | None = None,
            dashed: bool = False) -> None:
        x0, y0, x1, y1 = xy
        if dashed:
            step, gap = 10, 7
            x = x0
            while x < x1:
                self.d.line([(x, y0), (min(x + step, x1), y0)], fill=outline, width=2)
                self.d.line([(x, y1), (min(x + step, x1), y1)], fill=outline, width=2)
                x += step + gap
            y = y0
            while y < y1:
                self.d.line([(x0, y), (x0, min(y + step, y1))], fill=outline, width=2)
                self.d.line([(x1, y), (x1, min(y + step, y1))], fill=outline, width=2)
                y += step + gap
        else:
            self.d.rounded_rectangle(xy, radius=10, fill=fill, outline=outline, width=2)
        self.d.text(((x0 + x1) // 2, (y0 + y1) // 2), label,
                    fill="black", font=font or self.font, anchor="mm",
                    align="center")

    def arrow(self, a: tuple[int, int], b: tuple[int, int], label: str = "",
              dashed: bool = False, label_offset: tuple[int, int] = (0, -12)
              ) -> None:
        if dashed:
            step, gap = 12, 8
            import math
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy)
            ux, uy = dx / length, dy / length
            t = 0.0
            while t < length - 14:
                seg_end = min(t + step, length - 14)
                self.d.line([(a[0] + ux * t, a[1] + uy * t),
                             (a[0] + ux * seg_end, a[1] + uy * seg_end)],
                            fill="#57534E", width=2)
                t = seg_end + gap
        else:
            self.d.line([a, b], fill="#292524", width=3)
        # 箭头头部
        import math
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        for rot in (2.6, -2.6):
            x2 = b[0] + 14 * math.cos(ang + rot)
            y2 = b[1] + 14 * math.sin(ang + rot)
            self.d.line([b, (x2, y2)], fill="#292524" if not dashed else "#57534E",
                        width=3)
        if label:
            mx = (a[0] + b[0]) // 2 + label_offset[0]
            my = (a[1] + b[1]) // 2 + label_offset[1]
            self.d.text((mx, my), label, fill="#7C2D12", font=self.small,
                        anchor="mm", align="center")

    def note(self, xy: tuple[int, int], text: str) -> None:
        self.d.text(xy, text, fill="#57534E", font=self.small, anchor="mm")

    def save(self, name: str) -> Path:
        OUT.mkdir(parents=True, exist_ok=True)
        p = OUT / name
        self.img.save(p)
        return p


def figure_ad1() -> None:
    c = Canvas(1120, 780, "AD-1 依赖方向：protocols 是依赖根")
    c.box((300, 80, 820, 140), "apps（CLI + Replay）｜solutions（垂直包）")
    c.box((340, 180, 780, 240), "vastacore-sdk（组装根——唯一允许引用适配器）",
          fill="#FEF3C7", outline="#B45309")
    core = ["runtime", "contracts", "policy", "cognition", "storage",
            "model-lab", "eval"]
    w, gap, x0, y = 128, 14, 92, 330
    for i, name in enumerate(core):
        c.box((x0 + i * (w + gap), y, x0 + i * (w + gap) + w, y + 52), name,
              fill="#ECFDF5", outline="#047857", font=c.small)
    c.box((850, 270, 1090, 440), "vasta-adapters\n（实现端口，\n不被任何包\nimport）",
          fill="#FFF", outline="#9CA3AF", dashed=True, font=c.small)
    c.box((340, 560, 780, 630), "vasta-protocols\n（端口 + schema，依赖根，零本仓库依赖）",
          fill="#FEE2E2", outline="#B91C1C")
    # 核心层整体一条箭头指向 protocols（逐包画线会太乱）
    c.arrow((560, 382), (560, 560))
    c.arrow((560, 140), (560, 180))
    c.arrow((560, 240), (560, 330))
    c.arrow((970, 440), (780, 595), "实现", dashed=True, label_offset=(18, -14))
    c.note((560, 700), "规则：依赖只指向 vasta-protocols；组装仅在 vastacore-sdk 与 apps")
    c.note((560, 730), "import-linter 强制：核心包禁止 import 适配器")
    return c.save("ad1_layers.png")


def figure_planes() -> None:
    c = Canvas(1200, 640, "运行拓扑三面（AD-8 划界）")
    c.box((80, 90, 460, 210), "控制面 services/control-plane\n（租户 · 策略 · 注册表 · 发布）",
          fill="#EEF2FF", outline="#3730A3")
    c.box((740, 90, 1120, 210), "运行时数据面 runtime-api\n（Run / Supervisor / Tool Gateway）",
          fill="#ECFDF5", outline="#047857")
    c.box((410, 400, 790, 520), "证据认知面 storage+cognition\n（事件库 + CAS + Claim 图）",
          fill="#FEF3C7", outline="#B45309")
    c.arrow((460, 150), (740, 150), "期望状态 / 签名资产")
    c.arrow((930, 210), (700, 400), "运行事件 / 证据写入", label_offset=(56, 0))
    c.arrow((270, 210), (480, 400), "只读摘要与聚合指标\n（无原始载荷）", dashed=True,
            label_offset=(-40, -2))
    c.note((600, 590), "AD-8：控制面不碰原始载荷——只收元数据、签名摘要与去标识指标")
    return c.save("three_planes.png")


def figure_chain() -> None:
    c = Canvas(1280, 340, "写动作六段链（AD-4 唯一通道）")
    steps = ["① before\n观察", "② 契约\n落 CAS", "③ policy\n_cleared",
             "④ action\n_executed", "⑤ after\n观察", "⑥ verifi\ncation"]
    w, gap, x0, y = 158, 26, 62, 120
    for i, s in enumerate(steps):
        c.box((x0 + i * (w + gap), y, x0 + i * (w + gap) + w, y + 76), s,
              fill="#EEF2FF" if i % 2 == 0 else "#ECFDF5",
              outline="#3730A3" if i % 2 == 0 else "#047857", font=c.small)
        if i < len(steps) - 1:
            ax = x0 + i * (w + gap) + w
            c.arrow((ax, y + 38), (ax + gap, y + 38))
    c.note((640, 250), "每段都追加事件留痕；缺契约段即 fail-closed 拒执行（action.policy_denied）")
    c.note((640, 280), "核验四态：pass / deviation / inconclusive / system_error")
    return c.save("six_segment.png")


if __name__ == "__main__":
    for fn in (figure_ad1, figure_planes, figure_chain):
        p = fn()
        print("wrote", p)
