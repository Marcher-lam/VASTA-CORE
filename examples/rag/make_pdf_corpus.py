"""合成中文图文混排 PDF 语料（方案 B 评测对象）。

三页 A4：每页 = 标题 + 段落（转录自 ARCHITECTURE-SPINE）+ 一张架构图整幅嵌入。
生成的是 born-digital PDF（非扫描件），MinerU 走文本层 + 图像抽取路径。
运行：uv run --all-packages python -m examples.rag.make_pdf_corpus
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from .make_figures import _font

OUT_DIR = Path(__file__).resolve().parent / "corpus"
W, H, MARGIN = 1240, 1754, 84  # A4 @150dpi
LINE_GAP = 10

PAGES = [
    {
        "title": "VastaCore 架构摘要（图文版）",
        "paras": [
            "VastaCore 是面向长程、多模态、工具调用型 Agent 的认知与执行可靠性平台。"
            "架构范式为分层加端口/适配器（hexagonal），事件溯源是唯一的状态写路径。",
            "AD-1 依赖方向：vasta-protocols 是依赖根。依赖只能指向 vasta-protocols 所在层；"
            "核心包只依赖 protocols 与更底层核心包；适配器只实现 protocols 接口，任何包不得 "
            "import 具体适配器；组装只发生在 vastacore-sdk 与 apps 入口。",
        ],
        "figure": "ad1_layers.png",
    },
    {
        "title": "运行拓扑三面（AD-8 划界）",
        "paras": [
            "控制面组件（租户/策略/注册表/发布/配额）只接收元数据、签名摘要与去标识聚合指标，"
            "任何原始 Artifact 载荷与原始证据内容不得进入控制面存储或日志。",
            "运行时数据面承载 Run 循环、Supervisor 与 Tool Gateway；证据认知面由事件库、"
            "CAS 与 Claim 图构成。控制面向运行时数据面下发期望状态与签名资产。",
        ],
        "figure": "three_planes.png",
    },
    {
        "title": "写动作六段链（AD-4 唯一通道）",
        "paras": [
            "状态改变型动作只能经 Contract → Policy →（Approval）→ Tool Gateway → Execute → "
            "Verify 管道执行；模型适配器与业务代码不得直接调用业务工具。",
            "核验（verification）四态为 pass / deviation / inconclusive / system_error；"
            "缺契约段即 fail-closed 拒执行。",
        ],
        "figure": "six_segment.png",
    },
]


def _render_page(page: dict) -> Image.Image:
    img = Image.new("RGB", (W, H), "white")
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    title_f, body_f = _font(36), _font(22)
    y = MARGIN
    d.text((MARGIN, y), page["title"], fill="black", font=title_f)
    y += 70
    max_w = W - 2 * MARGIN
    for para in page["paras"]:
        # 按像素宽度折行（中文无空格，逐字累积）
        lines, buf = [], ""
        for ch in para:
            if title_f.getlength(buf + ch) > max_w:
                lines.append(buf)
                buf = ch
            else:
                buf += ch
        lines.append(buf)
        for line in lines:
            d.text((MARGIN, y), line, fill="black", font=body_f)
            y += body_f.size + LINE_GAP
        y += 16
    fig = Image.open(OUT_DIR / page["figure"])
    scale = max_w / fig.width
    fig = fig.resize((max_w, int(fig.height * scale)))
    if y + fig.height > H - MARGIN:  # 放不下则等比压高
        avail = H - MARGIN - y
        fig = fig.resize((int(fig.width * avail / fig.height), avail))
    img.paste(fig, (MARGIN, y))
    return img


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pages = [_render_page(p) for p in PAGES]
    out = OUT_DIR / "vastacore_arch.pdf"
    pages[0].save(out, save_all=True, append_images=pages[1:], resolution=150.0)
    print("wrote", out)


if __name__ == "__main__":
    main()
