"""Calculator 键盘标定：点击反推 + AX 读屏 → 按钮 label→path 映射。

背景（2026-11 实测）：新版 macOS 计算器按钮 glyph 为矢量绘制，
AXTitle/AXDescription/AXHelp 全空——文字标签不可得。本模块用
**确定性协议**反推：点按钮 → AX 读显示屏值（含 pending 运算符
行）→ 由值反解按钮身份。

实测规律（显示屏 AX 值）：
- 数字钮 → 值=该数字（"7"）；
- 运算符 → pending 带出符号（"0 ÷"、"0 ×"、"−"…）；
- 小数点 → "0."；正负号 → "0"（切 0 的符号仍是 0）；
- AC 与 = → "0"（Phase2 区分：79 后点它，AC→"0"，=→"79"）。

协议全程 Apple event（零视觉参与），标定结果即 probe ground truth
与 P1 任务断言的确定性依据。注意：会真实点击目标 app 内部按钮。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path

from .ax import (  # noqa: PLC2701
    AxError,
    AxElement,
    _run_osascript,
    activate_app,
    ensure_frontmost,
)

_CALIB_JS = r"""
function run(argv) {
  const spec = JSON.parse(argv[0]);
  ObjC.import('Foundation');
  const sleep = function(s) { $.NSThread.sleepForTimeInterval(s); };
  const se = Application('System Events');
  const proc = se.applicationProcesses.byName(spec.app);
  const el = function(path) {
    let e = proc.windows[path[0]];
    for (let i = 1; i < path.length; i++) e = e.uiElements()[path[i]];
    return e;
  };
  const disp = function() {
    try { return String(el(spec.display).value()); } catch (e) { return 'ERR'; }
  };
  const click = function(path) {
    try { el(path).click(); return true; } catch (e) { return false; }
  };
  const esc = function() { try { se.keyCode(53); return true; }
    catch (e) { return false; } };

  const S = spec.settle_s;
  const out = {steps: [], esc_ok: true};
  const perform = function(seq) {  // ['e' | 'c:<path json>', …] → 屏值
    for (const step of seq) {
      if (step === 'e') { if (!esc()) { out.esc_ok = false; return 'NOESC'; } }
      else click(JSON.parse(step.slice(2)));
      sleep(S);
    }
    return disp();
  };

  if (spec.mode === 'check') {
    // 双 Esc 后读初值（须前台；表达式计算器 Esc 清当前项，干净态下即全清）
    esc(); sleep(S); esc(); sleep(S);
    out.initial = disp();
    return JSON.stringify(out);
  }

  if (spec.mode === 'spot') {
    // 缓存活性抽查：双 Esc → 点 7 → 读屏 → Esc 还原
    esc(); sleep(S); esc(); sleep(S);
    click(spec.seven); sleep(S);
    out.spot = disp();
    esc(); sleep(S);
    return JSON.stringify(out);
  }

  // Phase1：Esc → 点 B → 读屏（全部按钮）
  for (const b of (spec.buttons || [])) {
    out.steps.push({path: b,
      phase1: perform(['e', 'c:' + JSON.stringify(b)])});
  }
  // Phase2：仅 unknown 按钮——79 后点 B 区分 AC/=（等号保持 79）
  for (const b of (spec.phase2 || [])) {
    out.steps.push({path: b,
      phase2: perform(['e', 'c:' + JSON.stringify(spec.d7),
                       'c:' + JSON.stringify(spec.d9),
                       'c:' + JSON.stringify(b)])});
  }
  out.final = perform(['e']);
  return JSON.stringify(out);
}
"""

#: 显示屏值里可见的运算符字形（U+2212 − / U+00D7 × / U+00F7 ÷）。
_OP_GLYPHS = ("÷", "×", "−", "+", "%")


def _keypad_candidates(elements: list[AxElement]) -> list[AxElement]:
    """键盘钮过滤：可交互方块中取**众数精确尺寸**（本机 48×48）。

    众数过滤自动剔除侧栏钮（44×52 等）——误点侧栏会改变窗口布局。
    """
    squares = [e for e in elements
               if e.interactive and None not in (e.w, e.h)
               and 30 <= e.w <= 60 and 30 <= e.h <= 60]
    if not squares:
        return []
    modal_size = Counter((e.w, e.h) for e in squares).most_common(1)[0][0]
    return [e for e in squares if (e.w, e.h) == modal_size]


def _display_element(elements: list[AxElement]) -> AxElement | None:
    """显示屏 = 键区正上方的 AXStaticText（几何定位，值无关）。

    值正则不可用：中文数字模式下屏值是「七十九」这类非 ASCII。
    """
    keypad = _keypad_candidates(elements)
    texts = [e for e in elements
             if e.role == "AXStaticText" and None not in (e.x, e.w)]
    if keypad and texts:
        ky0 = min(e.y for e in keypad)
        above = [e for e in texts if e.y + e.h <= ky0 + 1]
        if above:
            # 最顶行 = 表达式/当前数行（打字语义）；求值后的结果行是
            # 另一个更靠下的 static——归一化时若选它会把残留当脏状态
            return min(above, key=lambda e: (e.y, -(e.w or 0) * (e.h or 0)))
    # 兜底：任意带值 static text 中面积最大者
    valued = [e for e in texts if e.value not in (None, "")]
    return max(valued, key=lambda e: (e.w or 0) * (e.h or 0)) if valued else None


#: 中文数字渲染模式的单字数字（点 7 显示「七」——2026-11 实测坑）。
#: 不含「〇」：中文钮点在清零态显示〇，若映射成 0 会冒领数字 0 的身份。
_CN_DIGITS = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
              "六": "6", "七": "7", "八": "8", "九": "9"}


def _classify_phase1(v: str) -> str | None:
    """显示屏值 → 按钮 label；None = unknown（AC/=/正负号类）。"""
    v = v.strip()
    if v in {"0", "", "ERR", "NOESC"}:
        return None
    if v in {"0.", "."}:
        return "."
    if v in {"-0", "−0", "0−", "0-"}:
        return "+/−"
    if len(v) == 1 and v.isdigit():
        return v
    if len(v) == 1 and v in _CN_DIGITS:
        return _CN_DIGITS[v]
    residue = v.replace("0", "").replace(" ", "")  # pending 行剥壳："0 ÷"→"÷"
    if len(residue) == 1 and residue in _OP_GLYPHS:
        return residue
    return None


def hard_reset(app: str = "Calculator", *, settle_s: float = 1.8) -> None:
    """确定性冷启动 + 清零验证：杀 → 删 SavedState → 重开 → Esc 兜底。

    实测（2026-11）：状态恢复源不止 SavedState 一处，冷启动不保证
    回零——故本轮内自证：焦点内双 Esc 后显示语义值须为 "0"，
    最多三轮（pkill 幂等）。仅 demo 沙盒应用使用。
    """
    from .ax import key_code, read_statics_subtree  # noqa: PLC0415

    for _ in range(3):
        subprocess.run(["pkill", "-x", app], capture_output=True)
        time.sleep(0.8)
        if app == "Calculator":
            saved = Path.home() / "Library" / "Saved Application State" / \
                "com.apple.calculator.savedState"
            shutil.rmtree(saved, ignore_errors=True)
            # 侧栏/模式等 UI 状态存于 defaults（非 SavedState）——实测
            # 仅删 SavedState 冷启动后侧栏仍开（键区 13 钮异签名）
            subprocess.run(["defaults", "delete", "com.apple.calculator"],
                           capture_output=True)
        activate_app(app, settle_s=settle_s)
        if not ensure_frontmost(app):
            continue
        if app == "Calculator":
            key_code(53)
            time.sleep(0.25)
            key_code(53)
            time.sleep(0.25)
            try:  # 清零自证（static 子树扫描；本机布局群组路径稳定）
                statics = read_statics_subtree(app, (0, 0, 0, 1, 0))
                clean = all(str(s.get("v", "")).strip() in {"0", ""}
                            for s in statics)
            except Exception:
                clean = True  # 读不到不阻塞（后续 _check_zero 再把关）
            if clean:
                return
    return  # 三轮未自证——交由上层 _check_zero 诚实报错/重试


def _check_zero(app: str, display_path: list[int],
                settle_s: float) -> bool:
    spec = {"app": app, "display": display_path, "mode": "check",
            "settle_s": settle_s}
    out = json.loads(_run_osascript(_CALIB_JS, json.dumps(spec),
                                    timeout_s=30.0))
    return str(out.get("initial")).strip() == "0"


def discover_keypad(app: str, elements: list[AxElement],
                    *, settle_s: float = 0.25) -> dict[str, tuple[int, ...]]:
    """点击反推键盘映射，返回 label→path（"7"/"×"/"="/"AC"/"."…）。

    前置：应用已 hard_reset（或状态干净且前台）——调用方负责。
    """
    display = _display_element(elements)
    keypad = _keypad_candidates(elements)
    if display is None or not keypad:
        raise AxError(f"标定前置失败：display={'有' if display else '无'}，"
                      f"键盘钮={len(keypad)} 个")
    if not _check_zero(app, list(display.path), settle_s):
        ensure_frontmost(app)  # 焦点被抢的常见症状——重激活后再试一次
        if not _check_zero(app, list(display.path), settle_s):
            raise AxError("显示屏非零（状态脏或应用失焦）——请先 hard_reset")

    spec: dict = {"app": app, "display": list(display.path),
                  "buttons": [list(e.path) for e in keypad],
                  "phase2": [], "d7": [], "d9": [], "d2": [],
                  "settle_s": settle_s}

    result = json.loads(_run_osascript(_CALIB_JS, json.dumps(spec),
                                       timeout_s=180.0))
    if not result.get("esc_ok"):
        raise AxError("Esc 键码发送失败（keyCode 不可用）")

    labels: dict[str, tuple[int, ...]] = {}
    unknown: list[tuple[int, ...]] = []
    for step in result["steps"]:
        if "phase1" not in step:
            continue
        path = tuple(step["path"])
        label = _classify_phase1(str(step["phase1"]))
        if label is None:
            unknown.append(path)
        else:
            labels[label] = path
    for d in ("7", "9", "2"):
        if d not in labels:
            raise AxError(f"Phase1 未识别出数字 {d}（得 {sorted(labels)}）")

    if unknown:  # Phase2：79 后点 B——AC→"0"，=→"79"，0→"790"，.→"79."
        spec = {"app": app, "display": spec["display"], "buttons": [],
                "phase2": [list(p) for p in unknown],
                "d7": list(labels["7"]), "d9": list(labels["9"]),
                "d2": list(labels["2"]), "settle_s": settle_s}
        result = json.loads(_run_osascript(_CALIB_JS, json.dumps(spec),
                                           timeout_s=120.0))
        for step in result["steps"]:
            if "phase2" not in step:
                continue
            v = str(step["phase2"]).strip()
            label = {"0": "AC", "79": "=", "790": "0",
                     "79.": ".", "79,": ".",
                     "-79": "+/−", "−79": "+/−"}.get(v)
            if label and label not in labels:
                labels[label] = tuple(step["path"])
    return labels


def type_display_number(app: str, labels: dict[str, tuple[int, ...]],
                        number: str) -> None:
    """把显示屏打成指定数字（esc + 逐位点击）——probe 造读数现场用。"""
    from .ax import click_element, key_code  # noqa: PLC0415

    # 双 Esc 全清（表达式模式下单 Esc 只清当前项，不清挂起表达式）
    key_code(53)
    key_code(53)
    time.sleep(0.2)
    for ch in number:
        click_element(app, labels[ch])
        time.sleep(0.15)


__all__ = ["discover_keypad", "get_keypad", "hard_reset",
           "keypad_signature", "type_display_number"]


# ── 标定缓存（活桌面工程学）────────────────────────────────────────────
#
# 实测（2026-11）：40+ 次点击的标定协议在「机器正被人用」时极易被焦点
# 夺走打断（微信在前台）。键盘几何（按钮数 + 网格位置）不变 ⇒ 标定结果
# 不变——按几何签名缓存，命中即零点击复用；每 run 只剩打数字的 2 次点击。

def keypad_signature(elements: list[AxElement]) -> str:
    """键盘几何签名（按钮数 + 网格形状）。"""
    import hashlib

    kp = _keypad_candidates(elements)
    xs = sorted({round(e.x or 0) for e in kp})
    ys = sorted({round(e.y or 0) for e in kp})
    grid = [[int(any(abs((e.x or 0) - x) < 2 and abs((e.y or 0) - y) < 2
                     for e in kp)) for x in xs] for y in ys]
    payload = json.dumps({"n": len(kp), "cols": len(xs), "rows": len(ys),
                          "grid": grid}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _spot_check(app: str, display_path: list[int],
                labels: dict[str, tuple[int, ...]], settle_s: float) -> bool:
    """缓存活性抽查：Esc → 点 7 → 屏显 "7" → Esc 还原。"""
    if "7" not in labels:
        return False
    spec = {"app": app, "display": display_path, "mode": "spot",
            "seven": list(labels["7"]), "settle_s": settle_s}
    out = json.loads(_run_osascript(_CALIB_JS, json.dumps(spec),
                                    timeout_s=30.0))
    return str(out.get("spot")) == "7"


def get_keypad(app: str, elements: list[AxElement], store_root: Path, *,
               force: bool = False, settle_s: float = 0.25,
               ) -> tuple[dict[str, tuple[int, ...]], bool]:
    """取键盘标定（缓存优先）。返回 (labels, from_cache)。

    缓存命中后做一次廉价活性抽查（点 7 读屏="7"）——签名相同但行为
    变了（系统升级/换皮肤）即失效回退全量标定。
    """
    display = _display_element(elements)
    if display is None:
        raise AxError("标定前置失败：未找到显示屏元素")
    sig = keypad_signature(elements)
    cache = Path(store_root) / f"calib-{app}-{sig}.json"
    if not force and cache.exists():
        try:
            data = json.loads(cache.read_text())
            cached = {k: tuple(v) for k, v in data.get("labels", {}).items()}
        except (json.JSONDecodeError, OSError):
            cached = {}
        if cached and data.get("display") == list(display.path):
            # 焦点被抢会让抽查误判——先守卫，失败再重试一次，仍败才判失效
            if _spot_check(app, list(display.path), cached, settle_s):
                return cached, True
            ensure_frontmost(app)
            if _spot_check(app, list(display.path), cached, settle_s):
                return cached, True
        cache.unlink(missing_ok=True)  # 失效即删
    labels = discover_keypad(app, elements, settle_s=settle_s)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(
        {"display": list(display.path),
         "labels": {k: list(v) for k, v in labels.items()}},
        ensure_ascii=False))
    return labels, False
