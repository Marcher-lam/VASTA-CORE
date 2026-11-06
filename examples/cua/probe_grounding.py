"""P0 门禁：纯视觉 + SoM 编号的 grounding 命中率 probe。

问题：qwen3.5-9b-mlx 能否在「编号标记截图」上正确选号？
通过线（≥80%）：P1 最小闭环开工；不过：换模型 / 降级「VLM 报区域
+ AX 就近吸附」再复测。

Ground truth 不经模型：本机计算器按钮 AX 无文字标签（矢量 glyph），
按钮身份由 calib.py 的确定性点击反推标定；显示屏真值由 AX 直读。

流程：激活计算器 → 点击标定键盘 → 显示屏打 42 → 截图（原始证据）
→ 编号标记（派生）→ 语义问题逐条问 VLM（只看标记图）→ 对分。

点击面说明：probe 仅点击目标沙盒应用（计算器）内部按钮用于标定，
不触碰其他任何应用；无键盘输入（Esc 清零除外）。
运行：uv run python -m examples.cua.probe_grounding [--gate 0.8]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

from .ax import (
    AxError,
    activate_app,
    enumerate_elements,
    frontmost_app,
    screen_info,
    screenshot_png,
)
from .calib import get_keypad, hard_reset, type_display_number
from .config import CuaConfig
from .marks import build_marks, crop_window, render_marked
from .vlm import VlmClient

#: 语义问题 → 标定 label（GT 来自点击反推，与模型零接触）。
#: 注：本机 macOS 27 计算器为整数表达式版——无小数点钮（有中文数字
#: 功能钮），故第 10 题取 %。
QUERY_LABELS: dict[str, str] = {
    "数字 7 的按钮": "7",
    "数字 8 的按钮": "8",
    "数字 9 的按钮": "9",
    "执行乘法（×）运算的按钮": "×",
    "执行除法（÷）运算的按钮": "÷",
    "执行加法（+）运算的按钮": "+",
    "执行减法（−）运算的按钮": "−",
    "等号（=）按钮": "=",
    "清除/归零（AC）按钮": "AC",
    "百分号（%）按钮": "%",
}

SYSTEM_PROMPT = (
    "你是 macOS 桌面操作助手。屏幕截图上叠加了带编号的方框标记"
    "（左上角数字牌）。根据问题找到对应元素，只输出一个 JSON 对象，"
    "不要输出任何其他文字。"
)


async def run_probe(gate: float, no_cache: bool) -> int:
    cfg = CuaConfig()
    app = "Calculator"
    store = None
    if not no_cache:
        from vasta_storage import SqliteStorage
        store = SqliteStorage(cfg.store_root / "store")

    try:
        print(f"[probe] hard_reset {app}（冷启动）+ AX 枚举 + 标定（缓存优先）…")
        elements: list = []
        labels: dict = {}
        cached = False
        for attempt in (1, 2, 3):
            hard_reset(app)
            elements = enumerate_elements(app, cfg)
            try:
                labels, cached = get_keypad(app, elements, cfg.store_root)
                break
            except AxError as exc:
                if attempt == 3:
                    raise
                print(f"  标定失败（{str(exc)[:60]}）——hard_reset 重试 "
                      f"({attempt + 1}/3)")
        print(f"  标定按钮 {len(labels)} 个（{'缓存命中' if cached else '全量点击'}）: "
              f"{sorted(labels)}")
        if frontmost_app() != app:
            activate_app(app)
        type_display_number(app, labels, "42")  # 显示屏=42（读数题真值）
        time.sleep(0.3)

        print("[probe] 截图 + 窗口裁剪 + 编号标记 …")
        if frontmost_app() != app:  # 焦点被抢则重新激活（Esc/截图都依赖前台）
            activate_app(app)
        info = screen_info()
        shot = screenshot_png()  # 缺屏幕录制权限在此抛 AxError（含指引）
        # scale 以实际截图为准（CGDisplayPixelsWide 本机返回点而非像素）
        import io

        from PIL import Image

        img_w = Image.open(io.BytesIO(shot)).width
        scale = img_w / info["pt_w"]
        win = next((e for e in elements if e.path == (0,)), None)
        if win is not None and None not in (win.x, win.w):
            scene, in_elements = crop_window(shot, elements, win, scale)
            scene_pt = (win.w, win.h)
        else:  # 无窗口框架 → 全屏兜底
            scene, in_elements = shot, elements
            scene_pt = (info["pt_w"], info["pt_h"])
        marks = build_marks(in_elements, scale, scene_pt,
                            max_marks=cfg.max_marks)
        marked = render_marked(scene, marks, scale)
        interactive = sum(1 for m in marks if m["interactive"])
        print(f"  屏幕 {info['pt_w']:.0f}×{info['pt_h']:.0f}pt "
              f"@{scale:.1f}x（实测）｜场景 {len(marks)} 个标记"
              f"（可交互 {interactive}）｜AX 元素 {len(elements)} 个")

        # GT：标定 path ↔ mark path 精确匹配
        by_path = {tuple(m["path"]): m for m in marks}
        targets: dict[str, dict] = {}
        for question, label in QUERY_LABELS.items():
            m = by_path.get(labels[label]) if label in labels else None
            if m is not None:
                targets[question] = m
        if len(targets) < len(QUERY_LABELS):
            missing = [q for q in QUERY_LABELS if q not in targets]
            print(f"  ⚠ 标定按钮未进 marks: {missing}")

        # 证据落库：原始全屏截图 / 场景（窗口裁剪）/ 标记图 / 标记表 / 标定表
        if store is not None:
            sha_shot = await store.save_artifact(
                shot, mime="image/png", source="cua.probe.screenshot",
                tags={"cua_probe": app},
                tenant_id=cfg.tenant_id, project_id=cfg.project_id)
            sha_marked = await store.save_artifact(
                marked, mime="image/png", source="cua.probe.marked",
                tags={"cua_probe": app},
                tenant_id=cfg.tenant_id, project_id=cfg.project_id)
            await store.save_artifact(
                json.dumps(marks, ensure_ascii=False).encode("utf-8"),
                mime="application/json", source="cua.probe.marks",
                tags={"cua_probe": app},
                tenant_id=cfg.tenant_id, project_id=cfg.project_id)
            await store.save_artifact(
                json.dumps({k: list(v) for k, v in labels.items()},
                           ensure_ascii=False).encode("utf-8"),
                mime="application/json", source="cua.probe.calib",
                tags={"cua_probe": app},
                tenant_id=cfg.tenant_id, project_id=cfg.project_id)
            print(f"  证据：原图 sha256:{sha_shot[:12]}… "
                  f"标记图 sha256:{sha_marked[:12]}…")

        # ── 逐题问 VLM（只看标记图）──
        vlm = VlmClient(cfg, store)
        rows: list[tuple[str, str, str, bool, float]] = []
        questions = [(q, m, "mark") for q, m in targets.items()]
        questions.append(("显示屏读数", None, "display"))
        for question, truth, mode in questions:
            if mode == "mark":
                ask = f"问题：{question}？只输出 JSON：{{\"mark\": <编号>}}"
            else:
                ask = ("问题：计算器显示屏当前显示的数值是多少？只输出 JSON："
                       '{"display": "<数值字符串>"}')
            t0 = time.monotonic()
            try:
                answer = await vlm.ask_json(
                    SYSTEM_PROMPT, ask, images=[(marked, "image/png")],
                    max_tokens=1200)
            except RuntimeError as exc:
                rows.append((question, "?", f"ERR:{str(exc)[:60]}", False,
                             time.monotonic() - t0))
                continue
            dt = time.monotonic() - t0
            if mode == "mark":
                got_raw = answer.get("mark")
                try:  # 模型时而回字符串 "27" 时而回整数（实测坑）
                    got = int(got_raw)
                except (TypeError, ValueError):
                    got = None
                want = truth["mark"]
                rows.append((question, f"mark {want}", f"mark {got_raw}",
                             got == want, dt))
            else:
                got = str(answer.get("display", "")).strip()
                rows.append(("显示屏读数", '"42"', f"{got!r}",
                             got == "42", dt))

        # ── 计分 ──
        hit = sum(1 for r in rows if r[3])
        rate = hit / len(rows) if rows else 0.0
        print("\n" + "─" * 56)
        for q, want, got, ok, dt in rows:
            print(f"  {'✓' if ok else '✗'} {q:<20} 期望 {want:<9} "
                  f"得到 {got:<9} {dt:5.1f}s")
        print("─" * 56)
        api = vlm.api_calls
        print(f"命中 {hit}/{len(rows)} = {rate:.0%}（门禁 {gate:.0%}）"
              f"｜API {api} 次"
              f"{'（其余缓存命中）' if api < len(rows) else ''}")
        verdict = rate >= gate
        print(f"[probe] {'PASS ✓' if verdict else 'FAIL ✗'}"
              + ("" if verdict else " → 换模型或降级区域吸附后复测"))
        return 0 if verdict else 1
    finally:
        if store is not None:
            store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", type=float, default=0.8)
    parser.add_argument("--no-cache", action="store_true",
                        help="不落库不缓存（快诊断）")
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(run_probe(args.gate, args.no_cache)))
    except AxError as exc:
        print(f"[probe] 权限/环境错误：{exc}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
