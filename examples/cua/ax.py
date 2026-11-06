"""macOS Accessibility 桥：纯 osascript/JXA 枚举控件、读值、注入输入。

零外部依赖（不装 cliclick / pyobjc）：
- 枚举：JXA 递归 uiElements()，每属性独立 try/catch（无 title/value
  是常态不是异常）；菜单族（MenuBar/MenuBarItem/Menu）跳过——
  菜单打开时再按需枚举；
- 点击：优先 System Events 元素级 click（walk 索引路径），坐标兜底
  走 JXA ObjC 桥的 CGEvent（只需辅助功能权限）；
- 证据语义：本模块只读 UI 状态，不产生副作用；click/keystroke 是
  仅有的写面，全部由 tools.py 经契约链调用。

坐标口径：AX position/size 单位是**点**（point）；截图是像素，
marks.py 用 screen_info() 的 scale 换算。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field

from .config import CuaConfig

#: 视为「可交互」的 AX 角色（编号标记与点击白名单的默认集）。
INTERACTIVE_ROLES = frozenset({
    "AXButton", "AXCheckBox", "AXRadioButton", "AXPopUpButton",
    "AXMenuButton", "AXSlider", "AXTextField", "AXSecureTextField",
    "AXComboBox", "AXTab", "AXLink",
})

#: 可读值角色（显示屏、标签——核验的确定性证据来源）。
TEXT_ROLES = frozenset({"AXStaticText"})


class AxError(RuntimeError):
    """AX 桥失败（多为权限缺失：系统设置 → 隐私与安全性 → 辅助功能）。"""


@dataclass
class AxElement:
    role: str | None = None
    subrole: str | None = None
    title: str | None = None
    value: str | int | float | None = None
    desc: str | None = None
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    path: tuple[int, ...] = field(default_factory=tuple)

    @property
    def interactive(self) -> bool:
        return self.role in INTERACTIVE_ROLES

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2, self.y + self.h / 2)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["path"] = list(self.path)
        return d


def _run_osascript(script: str, *args: str, language: str = "JavaScript",
                   timeout_s: float = 30.0) -> str:
    """osascript 子进程（脚本体单 argv 传入，无 shell 引用问题）。"""
    proc = subprocess.run(
        ["osascript", "-l", language, "-e", script, *[str(a) for a in args]],
        capture_output=True, text=True, timeout=timeout_s,
    )
    if proc.returncode != 0:
        raise AxError(f"osascript 失败: {proc.stderr.strip()[:400]}")
    return proc.stdout.strip()


# ── 枚举（JXA：递归 uiElements，限额防爆量）─────────────────────────────

_ENUM_JS = """
function run(argv) {
  const appName = argv[0];
  const MAX_EL = parseInt(argv[1]) || 400;
  const MAX_DEPTH = parseInt(argv[2]) || 7;
  const MAX_CHILDREN = parseInt(argv[3]) || 60;
  const se = Application('System Events');
  const proc = se.applicationProcesses.byName(appName);
  const SKIP = {'AXMenuBar': 1, 'AXMenuBarItem': 1, 'AXMenu': 1};
  const out = [];
  let count = 0;

  function visit(el, path, depth) {
    if (count >= MAX_EL || depth > MAX_DEPTH) return;
    const o = { path: path.slice() };
    try { o.role = el.role(); } catch (e) {}
    if (SKIP[o.role]) return;
    try { o.title = el.title(); } catch (e) {}
    try {
      const v = el.value();
      if (v !== undefined && v !== null)
        o.value = (typeof v === 'object') ? String(v) : v;
    } catch (e) {}
    try {
      const p = el.position();
      if (p && p.length === 2) { o.x = p[0]; o.y = p[1]; }
    } catch (e) {}
    try {
      const s = el.size();
      if (s && s.length === 2) { o.w = s[0]; o.h = s[1]; }
    } catch (e) {}
    out.push(o);
    count++;
    let children = [];
    try { children = el.uiElements(); } catch (e) { return; }
    // 逐属性是 Apple event 往返：子节点限流防爆量（Finder/浏览器类
    // 重树截断前 60 个——标记密度本身由 max_marks 封顶）
    const n = Math.min(children.length, MAX_CHILDREN);
    for (let i = 0; i < n && count < MAX_EL; i++)
      visit(children[i], path.concat(i), depth + 1);
  }

  const wins = proc.windows();
  for (let w = 0; w < wins.length && count < MAX_EL; w++)
    visit(wins[w], [w], 1);
  return JSON.stringify(out);
}
"""


def enumerate_elements(app: str, cfg: CuaConfig) -> list[AxElement]:
    """枚举 app 全部窗口的 UI 元素（扁平 + 索引路径）。"""
    raw = _run_osascript(
        _ENUM_JS, app, str(cfg.ax_max_elements), str(cfg.ax_max_depth),
        str(getattr(cfg, "ax_max_children", 60)), timeout_s=90.0,
    )
    rows = json.loads(raw or "[]")
    els: list[AxElement] = []
    for r in rows:
        els.append(AxElement(
            role=r.get("role"), subrole=r.get("subrole"), title=r.get("title"),
            value=r.get("value"), desc=r.get("desc"),
            x=r.get("x"), y=r.get("y"), w=r.get("w"), h=r.get("h"),
            path=tuple(r.get("path") or ()),
        ))
    return els


# ── 读值（核验的确定性证据：不经模型的屏幕事实）─────────────────────────

_READ_JS = """
function run(argv) {
  const proc = Application('System Events')
    .applicationProcesses.byName(argv[0]);
  const path = argv[1].split(',').map(Number);
  let el = proc.windows[path[0]];
  for (let i = 1; i < path.length; i++) el = el.uiElements()[path[i]];
  const o = {};
  try { o.role = el.role(); } catch (e) {}
  try { const v = el.value(); if (v !== undefined && v !== null)
    o.value = (typeof v === 'object') ? String(v) : v; } catch (e) {}
  try { o.title = el.title(); } catch (e) {}
  return JSON.stringify(o);
}
"""


def read_element(app: str, path: tuple[int, ...]) -> dict:
    """按路径读元素当前值（AX 直读——read_back 核验器的证据源）。"""
    raw = _run_osascript(_READ_JS, app, ",".join(map(str, path)))
    return json.loads(raw or "{}")


_STATICS_JS = """
function run(argv) {
  const proc = Application('System Events')
    .applicationProcesses.byName(argv[0]);
  const rootPath = argv[1].split(',').map(Number);
  const MAX_DEPTH = parseInt(argv[2]) || 4;
  let el = proc.windows[rootPath[0]];
  for (let i = 1; i < rootPath.length; i++) el = el.uiElements()[rootPath[i]];
  const out = [];
  let count = 0;
  function visit(e, path, depth) {
    if (depth > MAX_DEPTH || count > 80) return;
    let role; try { role = e.role(); } catch (err) { return; }
    count++;
    if (role === 'AXStaticText') {
      let v = null;
      try { const x = e.value();
        if (x !== undefined && x !== null) v = String(x); } catch (err) {}
      if (v !== null) {
        let y = null;
        try { y = e.position()[1]; } catch (err) {}
        out.push({p: path.join(','), y: y, v: v});
      }
      return;  // static 无子树
    }
    let ch = [];
    try { ch = e.uiElements(); } catch (err) { return; }
    for (let i = 0; i < Math.min(ch.length, 40); i++)
      visit(ch[i], path.concat(i), depth + 1);
  }
  visit(el, rootPath.slice(), 0);
  return JSON.stringify(out);
}
"""


def read_statics_subtree(app: str, root_path: tuple[int, ...],
                         max_depth: int = 4) -> list[dict]:
    """子树内全部带值 AXStaticText（[{p,y,v}]——显示屏行发现）。"""
    raw = _run_osascript(
        _STATICS_JS, app, ",".join(map(str, root_path)), str(max_depth))
    return json.loads(raw or "[]")


def read_display(app: str, display_path: tuple[int, ...]) -> str | None:
    """显示屏语义值：display 祖父子树内 static text 取**最大 y**。

    实测（2026-11）：表达式行与结果行**各包一层容器**（非同父直接
    子级）；求值前只有一行，按 = 后新增结果行（y 更大）。取 max-y
    即「当前有效显示」。
    全函数：树在渲染流态（瞬时缺节点）时返回 None，不抛——
    调用方按「读不到=未知」处理。
    """
    root = display_path[:-2] if len(display_path) >= 3 else (0,)
    try:
        statics = read_statics_subtree(app, root)
        if statics:
            return max(statics, key=lambda s: (s.get("y") or 0))["v"]
    except Exception:
        pass
    try:
        raw = read_element(app, display_path).get("value")
        return None if raw is None else str(raw)
    except Exception:
        return None


# ── 输入注入（写面：仅 tools.py 契约链可达）────────────────────────────

_CLICK_EL_JS = """
function run(argv) {
  const proc = Application('System Events')
    .applicationProcesses.byName(argv[0]);
  const path = argv[1].split(',').map(Number);
  let el = proc.windows[path[0]];
  for (let i = 1; i < path.length; i++) el = el.uiElements()[path[i]];
  try { el.actions.byName('press').perform(); return 'press'; }
  catch (e) { try { el.click(); return 'click'; } catch (e2) {
    return 'FAIL:' + e2.message; } }
}
"""

_CLICK_AT_JS = """
function run(argv) {
  ObjC.import('CoreGraphics');
  const pt = $.CGPointMake(parseFloat(argv[0]), parseFloat(argv[1]));
  const post = function(type) {
    $.CGEventPost($.kCGHIDEventTap,
      $.CGEventCreateMouseEvent(null, type, pt, $.kCGMouseButtonLeft));
  };
  post($.kCGEventMouseMoved);
  post($.kCGEventLeftMouseDown);
  post($.kCGEventLeftMouseUp);
  return 'ok';
}
"""

_KEYSTROKE_AS = (
    "on run(argv)\n"
    "  tell application \"System Events\" to keystroke item 1 of argv\n"
    "end run"
)

_KEYCODE_AS = (
    "on run(argv)\n"
    "  tell application \"System Events\" to key code (item 1 of argv as number)"
    "%(using)s\n"
    "end run"
)

_MOD_LABELS = {"cmd": "command down", "command": "command down",
               "ctrl": "control down", "control": "control down",
               "alt": "option down", "option": "option down",
               "shift": "shift down", "fn": "fn down"}


def click_element(app: str, path: tuple[int, ...]) -> bool:
    """元素级点击（System Events press/click——AX 路径定点）。"""
    return not _run_osascript(
        _CLICK_EL_JS, app, ",".join(map(str, path)),
    ).startswith("FAIL")


def click_at(x_pt: float, y_pt: float) -> bool:
    """坐标点击兜底（CGEvent：move→down→up，单位=点）。"""
    return _run_osascript(_CLICK_AT_JS, f"{x_pt:.1f}", f"{y_pt:.1f}") == "ok"


def keystroke(text: str) -> None:
    """向聚焦控件键入文本（须先 click 元素聚焦）。"""
    _run_osascript(_KEYSTROKE_AS, text, language="AppleScript")


def key_code(code: int, modifiers: tuple[str, ...] = ()) -> None:
    """键码 + 可选修饰键（36=return, 53=esc…）。"""
    mods = ", ".join(_MOD_LABELS[m] for m in modifiers if m in _MOD_LABELS)
    _run_osascript(
        _KEYCODE_AS % {"using": f" using {{{mods}}}" if mods else ""},
        str(code), language="AppleScript",
    )


# ── 环境（前台应用 / 激活 / 屏幕）───────────────────────────────────────

def frontmost_app() -> str:
    raw = _run_osascript(
        "tell application \"System Events\" to get name of first "
        "application process whose frontmost is true",
        language="AppleScript",
    )
    return raw


def ensure_frontmost(app: str, *, tries: int = 4) -> bool:
    """焦点守卫（活桌面工程学）：失焦即重激活，最多 tries 次。"""
    import time

    for _ in range(tries):
        if frontmost_app() == app:
            return True
        activate_app(app)
    return frontmost_app() == app


def activate_app(name: str, *, settle_s: float = 0.8) -> None:
    """激活应用（LaunchServices open -a：切 Space + 抢焦点）。

    实测（2026-11）：System Events `activate` 在本机抢不到前台焦点
    （后台窗口的 Esc 键码不落地）；open -a 稳定有效。
    """
    import time

    subprocess.run(["open", "-a", name], capture_output=True, timeout=15)
    time.sleep(settle_s)


_SCREEN_JS = """
function run() {
  ObjC.import('CoreGraphics');
  const id = $.CGMainDisplayID();
  const b = $.CGDisplayBounds(id);
  return JSON.stringify({
    pt_w: b.size.width, pt_h: b.size.height,
    px_w: $.CGDisplayPixelsWide(id), px_h: $.CGDisplayPixelsHigh(id),
  });
}
"""


def screen_info() -> dict[str, float]:
    """主屏信息 + pt→px 缩放（Retina=2）。"""
    raw = json.loads(_run_osascript(_SCREEN_JS))
    info = {k: float(v) for k, v in raw.items()}  # JXA 数值可能回字符串
    info["scale"] = info["px_w"] / info["pt_w"] if info["pt_w"] else 1.0
    return info


def screenshot_png() -> bytes:
    """全屏截图（screencapture -x：需「屏幕录制」权限）。"""
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = Path(f.name)
    try:
        proc = subprocess.run(
            ["screencapture", "-x", "-t", "png", str(tmp)],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
            raise AxError(
                f"screencapture 失败（{proc.stderr.strip() or '无输出'}）——"
                "多为缺「屏幕录制」权限：系统设置 → 隐私与安全性 → "
                "屏幕录制 → 勾选终端宿主后重启宿主",
            )
        return tmp.read_bytes()
    finally:
        tmp.unlink(missing_ok=True)


__all__ = [
    "AxElement", "AxError", "INTERACTIVE_ROLES", "TEXT_ROLES",
    "activate_app", "click_at", "click_element", "ensure_frontmost",
    "enumerate_elements", "frontmost_app", "key_code", "keystroke",
    "read_display", "read_element", "read_statics_subtree", "screen_info",
    "screenshot_png",
]
