"""P2-B：TextEdit 键入（R2）+ 保存（R3 人在环审批，平台原生路径）。

演示要点：
- ``save_doc`` 清单声明 R3 → execute_contracted 默认策略映射
  request_approval → ``action.approval_requested`` 事件 + Run 挂起
  （ApprovalRequestedError）；
- 批准后**同一契约**带 approved=True 重放 → 平台校验「真实挂起请求」
  → ``action.approved`` 事件 → 执行（审批不可自证伪造）；
- type_text 的核验 = AX 直读正文（text_contains 规则）；save_doc 的
  核验 = 落盘文件存在且内容一致（result.ok 由工具诚实给出，schema
  核验器裁决）。

运行：uv run python -m examples.cua.textedit [--require-approval]
（默认走 CUA_AUTO_APPROVE（含 TextEdit）自动批准；--require-approval
在交互终端弹人工确认）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from vasta_contracts import ActionContract, Prediction, audit_six_segment
from vasta_policy import ApprovalRequestedError
from vasta_protocols.ids import new_run_id
from vasta_protocols.protocols import (
    Action,
    CompensationResult,
    DryRunResult,
    Observation,
    ToolManifest,
    ToolResult,
    Verification,
    Verifier,
    VerifierManifest,
)
from vasta_runtime import Budget, RunContext, RunEngine
from vasta_runtime.gateway import ToolGateway
from vasta_storage import SqliteStorage, first_deviation

from .ax import activate_app, ensure_frontmost, key_code
from .config import CuaConfig
from .env import DesktopEnv

DEMO_TEXT = "VastaCore CUA P2 demo —— 契约六段链 42×3=126"
#: 内容核验标记（ASCII）：保存面板可能按富文本格式追加 .rtf 并把
#: 中文转义为 \uNNNN——ASCII 段在 .rtf/.txt 里都字面保留
DEMO_MARKER = "VastaCore CUA P2 demo"
DEMO_STEM = "cua-p2-demo"
_SAVE_ROOTS = (
    Path.home() / "Documents",
    Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs",
    Path.home() / "Library" / "Containers" / "com.apple.TextEdit" /
    "Data" / "Documents",
)


def _paste_text(text: str) -> None:
    """剪贴板粘贴输入（实测坑：中文 IME 会拦截 keystroke 把 ASCII
    打成候选汉字——pbcopy + ⌘V 绕开 IME；用户剪贴板保存/还原）。"""
    import subprocess

    old = subprocess.run(["pbpaste"], capture_output=True).stdout
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        time.sleep(0.15)
        key_code(9, ("cmd",))  # ⌘V
        time.sleep(0.4)
    finally:
        if old:
            subprocess.run(["pbcopy"], input=old, check=False)


class TypeTextTool:
    """向新建 TextEdit 文档输入文本（R2，AX 直读正文核验）。"""

    protocol_version = "0.1.0"

    def __init__(self, *, tenant_id: str, project_id: str) -> None:
        self.manifest = ToolManifest(
            name="type_text", version="1.0",
            risk="R2", read_only=False, idempotent=False,
            side_effects=["在 TextEdit 新建文档中输入文本"],
        )
        self._tenant, self._project = tenant_id, project_id

    async def dry_run(self, action: Action) -> DryRunResult:
        return DryRunResult(allowed=bool(action.args.get("text")))

    async def execute(self, action: Action, idempotency_key=None) -> ToolResult:
        text = str(action.args["text"])
        ensure_frontmost("TextEdit")
        key_code(45, ("cmd",))  # ⌘N 新建文档（默认富文本）
        time.sleep(1.0)
        key_code(40, ("cmd", "shift"))  # ⇧⌘T 转纯文本（.txt/utf-8 核验口径）
        time.sleep(0.5)
        _paste_text(text)
        time.sleep(0.4)
        text_after = _read_textedit_content(text)
        return ToolResult(ok=text_after is not None,
                          detail={"text_after": text_after,
                                  "via": "clipboard-paste"})

    async def read_back(self, action: Action, result: ToolResult) -> Observation:
        return Observation(kind="decision",
                           detail={"text": result.detail.get("text_after")})

    async def compensate(self, execution_detail: dict) -> CompensationResult:
        return CompensationResult(ok=False, detail={"note": "键入不可补偿"})


class SaveDocTool:
    """保存当前文档（R3：落盘文件 = 不可逆写，必须人工批准）。"""

    protocol_version = "0.1.0"

    def __init__(self, *, tenant_id: str, project_id: str) -> None:
        self.manifest = ToolManifest(
            name="save_doc", version="1.0",
            risk="R3", read_only=False, idempotent=True,
            side_effects=["将 TextEdit 未命名文档写入文件系统"],
        )
        self._tenant, self._project = tenant_id, project_id

    async def dry_run(self, action: Action) -> DryRunResult:
        return DryRunResult(allowed=bool(action.args.get("filename")))

    async def execute(self, action: Action, idempotency_key=None) -> ToolResult:
        filename = str(action.args["filename"])
        expect = str(action.args.get("expect_contains", ""))
        ensure_frontmost("TextEdit")
        key_code(1, ("cmd",))  # ⌘S → 存储面板（S 的键码是 1，非 23——实测坑）
        time.sleep(1.2)
        key_code(0, ("cmd",))   # ⌘A 选中默认名（IME 不可信，粘贴替换）
        time.sleep(0.15)
        _paste_text(filename)
        time.sleep(0.3)
        key_code(36)  # Return 确认保存
        time.sleep(1.8)
        path = _find_saved_file()  # 词干匹配（面板可能追加 .rtf 等格式后缀）
        content_ok = (path is not None
                      and expect in path.read_text("utf-8", errors="replace"))
        return ToolResult(
            ok=path is not None and content_ok,
            detail={"path": str(path) if path else None,
                    "content_ok": content_ok},
        )

    async def read_back(self, action: Action, result: ToolResult) -> Observation:
        return Observation(kind="decision", detail=dict(result.detail))

    async def compensate(self, execution_detail: dict) -> CompensationResult:
        return CompensationResult(ok=False, detail={"note": "落盘不自动删除"})


# ── AX 正文直读（TextEdit 正文在滚动区的文本元素 value 上）─────────────

_CONTENT_JS = """
function run(argv) {
  const proc = Application('System Events')
    .applicationProcesses.byName('TextEdit');
  const out = [];
  let count = 0;
  function visit(el, depth) {
    if (depth > 9 || count > 250 || out.length > 6) return;
    let role; try { role = el.role(); } catch (e) { return; }
    count++;
    if (role === 'AXTextArea' || role === 'AXWebArea') {
      try {
        const v = el.value();
        if (v !== undefined && v !== null && String(v).length > 0)
          out.push(String(v));
      } catch (e) {}
    }
    let ch = []; try { ch = el.uiElements(); } catch (e) { return; }
    for (let i = 0; i < Math.min(ch.length, 40); i++) visit(ch[i], depth + 1);
  }
  for (let w = 0; w < proc.windows().length; w++) visit(proc.windows[w], 1);
  return JSON.stringify(out);
}
"""


def _read_textedit_content(expect: str | None = None) -> str | None:
    """全部窗口正文直读；expect 给定时返回包含它的那一篇。"""
    from .ax import _run_osascript  # noqa: PLC2701, PLC0415

    raw = _run_osascript(_CONTENT_JS, timeout_s=30.0)
    vals = json.loads(raw or "[]")
    if expect is None:
        return vals[0] if vals else None
    for v in vals:
        if expect in v:
            return v
    return None


def _find_saved_file() -> Path | None:
    """按词干找落盘文件（保存面板可能追加格式后缀 .rtf/.txt）。"""
    for root in _SAVE_ROOTS:
        if not root.is_dir():
            continue
        for cand in sorted(root.glob(f"{DEMO_STEM}*")):
            if cand.is_file():
                return cand
    return None


def _purge_saved_files() -> None:
    """run 前清旧产物（防保存面板弹「替换确认」卡住 Return）。"""
    for root in _SAVE_ROOTS:
        if not root.is_dir():
            continue
        for cand in root.glob(f"{DEMO_STEM}*"):
            try:
                cand.unlink()
            except OSError:
                pass


class TextContainsVerifier:
    """text_contains=<子串>：AX 正文直读裁决（INV-06）。"""

    protocol_version = "0.1.0"

    def __init__(self) -> None:
        self.manifest = VerifierManifest(name="text_contains", version="1.0",
                                         kind="state")

    async def verify(self, contract_ref: str,
                     evidence: dict[str, Any]) -> Verification:
        result = evidence.get("result")
        detail = result.get("detail", {}) if isinstance(result, dict) else {}
        actual = detail.get("text_after") or ""
        for change in evidence.get("expected_changes") or []:
            if isinstance(change, str) and change.startswith("text_contains="):
                want = change.split("=", 1)[1]
                ok = want in actual
                return Verification(
                    outcome="pass" if ok else "deviation",
                    detail={"want": want, "actual_len": len(actual),
                            "head": actual[:60]})
        return Verification(outcome="inconclusive",
                            detail={"reason": "无 text_contains 规则"})


# ── 运行器 ─────────────────────────────────────────────────────────────

def _type_contract(text: str) -> ActionContract:
    return ActionContract(
        tool="type_text", args={"text": text}, goal="TextEdit 键入演示文本",
        risk="R2",
        preconditions=["TextEdit 前台且存在（新建的）文档"],
        prediction=Prediction(changes=[f"text_contains={text}"],
                              invariants=["其他应用不受影响"]),
        success_criteria=["AX 正文包含全部文本"],
        failure_criteria=["正文缺失或不完整"],
        verify_with=["text_contains"], timeout_ms=20_000,
    )


def _save_contract(filename: str, expect: str) -> ActionContract:
    return ActionContract(
        tool="save_doc", args={"filename": filename, "expect_contains": expect},
        goal="保存演示文档（R3 人在环）", risk="R3",
        preconditions=["演示文本已键入且核验通过"],
        prediction=Prediction(changes=[f"file {filename} 落盘且内容一致"],
                              invariants=["其他文件不受影响"]),
        success_criteria=["文件存在且包含演示文本"],
        failure_criteria=["保存面板异常", "文件缺失或内容不符"],
        verify_with=["schema"], timeout_ms=30_000,
    )


async def run(require_approval: bool) -> int:
    cfg = CuaConfig()
    activate_app("TextEdit")
    time.sleep(1.0)
    _purge_saved_files()
    # 注意：不做键盘式窗口清理——⌘W 在残留脏文档上会触发
    # 「保留此新文稿？」三键对话框（⌘D 无效），吞掉后续全部键入
    # （2026-11 实测坑）。每 run ⌘N 自建新文档，互不干扰。

    store = SqliteStorage(Path(cfg.store_root) / "store")
    gateway = ToolGateway()
    gateway.register(TypeTextTool(tenant_id=cfg.tenant_id,
                                  project_id=cfg.project_id))
    gateway.register(SaveDocTool(tenant_id=cfg.tenant_id,
                                 project_id=cfg.project_id))
    env = DesktopEnv("TextEdit")
    run_id = new_run_id()
    engine = await RunEngine.create(
        env=env, store=store, budget=Budget(max_actions=6),
        run_context=RunContext.create(run_id=run_id, seed=42),
        capture_observations=True, tool_gateway=gateway,
    )

    async def approve_or_deny(exc: ApprovalRequestedError) -> bool:
        auto = "TextEdit" in cfg.auto_approve_apps and not require_approval
        if auto:
            print(f"  [审批] CUA_AUTO_APPROVE 含 TextEdit → 自动批准"
                  f"（{exc.tool} {exc.risk}：{exc.basis}）")
            return True
        try:
            answer = input(f"  [审批] 批准 {exc.tool!r}（{exc.risk}）？"
                           f"{exc.basis} [y/N] ").strip().lower()
        except EOFError:  # 非交互环境（后台任务）——fail-closed 拒绝
            print("  [审批] 非交互环境无输入 → 拒绝（fail-closed）")
            return False
        return answer == "y"

    try:
        await engine.start()
        await engine.reset()
        print(f"[textedit] run_id={run_id}")
        print("[textedit] step1: type_text（R2）…")
        await engine.execute_contracted(
            _type_contract(DEMO_TEXT),
            verifiers={"text_contains": TextContainsVerifier()})
        print("[textedit] step2: save_doc（R3 → 须批准）…")
        save = _save_contract(f"{DEMO_STEM}.txt", DEMO_MARKER)
        saved = False
        try:
            await engine.execute_contracted(save, verifiers={})
            saved = True  # 不该发生：R3 未批准应挂起——走到这即策略被绕过
            print("  ⚠ 未走审批即执行（策略配置异常）")
        except ApprovalRequestedError as exc:
            print(f"  [挂起] {exc}")
            if await approve_or_deny(exc):
                await engine.resume()  # paused → started（重观察 + run.resumed）
                await engine.execute_contracted(save, approved=True,
                                                verifiers={})
                saved = True
            else:
                print("  [拒绝] 人工否决——动作不执行")
        if saved:
            await engine.complete()
            try:  # 已保存文档 ⌘W 直关（无弹窗）；失败不掩没主结果
                key_code(13, ("cmd",))
                time.sleep(0.4)
            except Exception:
                pass
    finally:
        events: list[Any] = list(store.iter_run_events(run_id))
        audit = audit_six_segment(events)
        chain = [f"{e.type.replace('action.', '').replace('verification.', 'v:')}"
                 for e in events
                 if e.type.startswith(("action.", "verification."))]
        print(f"\n[textedit] 动作/核验事件链：{' → '.join(chain)}")
        print(f"[textedit] 六段链 complete={audit.complete}/{audit.total}"
              f" legal={audit.all_success_paths_complete}"
              f"｜首偏差 {first_deviation(events).type if first_deviation(events) else '无'}"
              f"｜run 状态 {engine.state.value}")
        file = _find_saved_file()
        print(f"[textedit] 落盘核验：{file}"
              f"（含 ASCII 标记：{file is not None and DEMO_MARKER in file.read_text('utf-8', errors='replace') if file else False}）")
        store.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-approval", action="store_true",
                        help="强制终端人工审批（默认 CUA_AUTO_APPROVE 自动批）")
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(run(args.require_approval)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
