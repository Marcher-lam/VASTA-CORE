"""P4：cognition UI-记忆三相演示（Claim 图驱动桌面 CUA）。

① 学习（learn）：全量点击标定 → 42×3 六段链全核验 → 布局+按钮写入
   Claim 图（propose → support → accept，evidence=学习 run）；
② 命中（recall）：新 run 仅凭记忆定位（1 次抽查点击，零标定/零视觉）
   → 任务全核验通过——记忆收益可度量；
③ 改版（break & relearn）：开侧栏改变 UI 树 → record_env_upgrade 锚点
   → 逐主张活检查（revalidated 留痕 + decay）→ 父主张 refute →
   **平台级联失效全部按钮主张** → 冷启动还原 → 全量重标定 → v2 记忆
   （旧 refuted 留痕可审计，新主张并存）。

全部走 vasta-cognition / vastacore.governance 公共 API；认知事件入
"cognition" 系统流（AD-2 投影）。
运行：uv run python -m examples.cua.run_memory
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from vasta_cognition import CognitionService
from vasta_contracts import audit_six_segment
from vasta_protocols.ids import new_run_id
from vasta_protocols.protocols import EnvironmentStatus, Observation
from vasta_runtime import Budget, RunContext, RunEngine
from vasta_runtime.gateway import ToolGateway
from vasta_storage import SqliteStorage

from .ax import click_element, enumerate_elements, read_display
from .calib import (
    _CALIB_JS,
    _display_element,
    _keypad_candidates,
    _run_osascript,
    get_keypad,
    hard_reset,
    keypad_signature,
)
from .config import CuaConfig
from .env import DesktopEnv
from .memory import recall_layout, record_layout
from .run_task import TASK_PLAN, build_contract
from .tools import ClickMarkTool
from .verifiers import AxDisplayVerifier

APP = "Calculator"


# ── 任务执行（六段链；路径来源=标定或记忆）───────────────────────────

async def task_run(cfg: CuaConfig, store: SqliteStorage,
                   labels: dict[str, tuple[int, ...]],
                   display_path: tuple[int, ...], *, tag: str,
                   ) -> tuple[bool, str]:
    """按 labels 执行 42×3；返回 (全核验通过, run_id)。"""
    marks_table = {i + 1: {"path": list(p), "x_pt": 0.0, "y_pt": 0.0,
                           "w_pt": 1.0, "h_pt": 1.0}
                   for i, p in enumerate(labels.values())}
    path_to_mark = {p: i + 1 for i, p in enumerate(labels.values())}
    gateway = ToolGateway()
    gateway.register(ClickMarkTool(
        APP, lambda: marks_table, store, display_path,
        tenant_id=cfg.tenant_id, project_id=cfg.project_id))
    run_id = new_run_id()
    engine = await RunEngine.create(
        # 调用方已重置应用——env 只做 Esc 清零（避免 4s 内双杀重开
        # 导致的 AX 树流态读屏失败）
        env=DesktopEnv(APP, display_path, hard_on_reset=False),
        store=store, budget=Budget(max_actions=len(TASK_PLAN) + 4),
        run_context=RunContext.create(run_id=run_id, seed=42),
        capture_observations=True, tool_gateway=gateway,
    )
    verifier = AxDisplayVerifier()
    await engine.start()
    await engine.reset()
    for label, expect in TASK_PLAN:
        if label not in labels:
            break
        contract = build_contract(f"[{tag}] 键入 {label!r}",
                                  path_to_mark[labels[label]], expect)
        try:
            await engine.execute_contracted(
                contract, verifiers={"ax_display": verifier})
        except Exception as exc:
            print(f"      [{tag}] {label!r} 链异常 {type(exc).__name__}: "
                  f"{str(exc)[:60]}")
            break
    # 计分只认事件流（核验器裁决）——镜像读屏在树渲染流态下不可靠
    passed = sum(1 for e in store.iter_run_events(run_id)
                 if e.type == "verification.passed")
    if passed == len(TASK_PLAN):
        await engine.complete()
    audit = audit_six_segment(list(store.iter_run_events(run_id)))
    print(f"    任务 {passed}/{len(TASK_PLAN)} 核验过｜"
          f"链 complete={audit.complete}/{audit.total}｜"
          f"run={engine.state.value}")
    return passed == len(TASK_PLAN), run_id


# ── 活检查（主张 vs 当前环境的零视觉对质）────────────────────────────

def live_check(path: tuple[int, ...], display_path: tuple[int, ...],
               expect: str) -> bool:
    spec = {"app": APP, "display": list(display_path), "mode": "spot",
            "seven": list(path), "settle_s": 0.25}
    out = json.loads(_run_osascript(_CALIB_JS, json.dumps(spec)))
    return str(out.get("spot", "")).strip() == expect


def toggle_sidebar(cfg: CuaConfig) -> tuple[bool, int, int]:
    """点侧栏钮改变 UI 树（模拟 UI 改版）。返回 (改版成功, 前元素数, 后元素数)。

    自取新鲜枚举——上一次枚举的路径在树变化后（如 = 出结果行）即过期。
    """
    elements = enumerate_elements(APP, cfg)
    keypad = _keypad_candidates(elements)
    modal = (keypad[0].w, keypad[0].h) if keypad else (48, 48)
    ky0 = min((e.y for e in keypad), default=0)
    chrome = [e for e in elements
              if e.interactive and None not in (e.w, e.h)
              and 30 <= e.w <= 60 and 30 <= e.h <= 60
              and (e.w, e.h) != modal and e.y < ky0]
    before = len(elements)
    for btn in chrome[:2]:
        if not click_element(APP, btn.path):
            continue
        time.sleep(1.2)
        for _ in range(2):  # 渲染流态容错：再枚举一次确认
            after = len(enumerate_elements(APP, cfg))
            if after > before + 5:
                return True, before, after
            time.sleep(0.6)
    return False, before, before


async def _accept_all(cog: CognitionService, claim_ids: list[str],
                      evidence: str) -> None:
    for cid in claim_ids:
        await cog.support(cid, [evidence])
        await cog.accept(cid)


def main() -> None:
    try:
        sys.exit(asyncio.run(run()))
    except KeyboardInterrupt:
        sys.exit(130)


async def run() -> int:
    from vastacore.governance.revalidation import record_env_upgrade

    cfg = CuaConfig()
    store = SqliteStorage(Path(cfg.store_root) / "store")
    cog = CognitionService(store, tenant_id=cfg.tenant_id,
                           project_id=cfg.project_id)
    ok = True
    try:
        # ── ① 学习 ──
        print("[①学习] hard_reset + 枚举 + 标定 …")
        hard_reset(APP)
        els = enumerate_elements(APP, cfg)
        sig = keypad_signature(els)
        display = _display_element(els)
        learn_clicks = 0
        if recall_layout(cog, APP, sig) is not None:
            print(f"  已有活跃记忆（sig={sig[:8]}…）→ 跳过标定（复跑演示）")
        else:
            t0 = time.monotonic()
            labels, cached = get_keypad(APP, els, cfg.store_root)
            learn_clicks = 0 if cached else len(labels) * 2  # 粗计：每钮 esc+点
            print(f"  全量标定 {len(labels)} 钮（cached={cached}）｜"
                  f"耗时 {time.monotonic() - t0:.0f}s｜约 {learn_clicks} 次点击")
            ok_task, run_id = await task_run(
                cfg, store, labels, tuple(display.path), tag="学习")
            ok &= ok_task
            if not ok_task:
                print("  ✗ 学习任务未全核验——不写记忆（诚实失败）")
                return 1
            parent, children = await record_layout(
                cog, APP, sig, labels, tuple(display.path), len(els),
                evidence_run=run_id)
            await _accept_all(cog, [parent, *children], f"run:{run_id}")
            print(f"  Claim 图写入：父 1 + 子 {len(children)}"
                  "（propose→support→accept）")

        # ── ② 命中 ──
        print("\n[②命中] 新 run 仅凭记忆定位（零标定）…")
        hard_reset(APP)
        els2 = enumerate_elements(APP, cfg)
        t0 = time.monotonic()
        hit2 = recall_layout(cog, APP, keypad_signature(els2))
        if hit2 is None:
            print("  ✗ 记忆未命中（布局未变，不应发生）")
            return 1
        pid2, labels2, dpath2, _ = hit2
        if not live_check(labels2["7"], dpath2, "7"):
            print("  ✗ 抽查失败——布局已变（应走③）")
            return 1
        print(f"  记忆命中 {len(labels2)} 钮｜抽查 1 次点击 ✓")
        ok2, _ = await task_run(cfg, store, labels2, tuple(dpath2), tag="命中")
        ok &= ok2
        print(f"  本相标定点击 1 次（学习相约 {learn_clicks or '~40'} 次）｜"
              f"耗时 {time.monotonic() - t0:.0f}s")

        # ── ③ 改版：反例 → 级联推翻 → 重标 v2 ──
        print("\n[③改版] 开侧栏改变 UI 树（模拟 UI 改版）…")
        opened, before, after = toggle_sidebar(cfg)
        if not opened:
            print("  ⚠ 未能改变 UI 树——跳过反例相")
            return 0 if ok else 1
        print(f"  UI 树 {before} → {after} 元素｜"
              f"几何签名不变（树已变——正是记忆盲区）")
        hit3 = recall_layout(cog, APP, keypad_signature(
            enumerate_elements(APP, cfg)))
        if hit3 is None:
            print("  ✗ 记忆已失效（不应——尚未推翻）")
            return 1
        pid3, labels3, dpath3, _ = hit3
        await record_env_upgrade(
            store, env_old=f"{APP}:basic", env_new=f"{APP}:sidebar",
            affected_scope={"app": APP},
            tenant_id=cfg.tenant_id, project_id=cfg.project_id)

        # 子主张逐个活检查（数字钮；运算符由父级联裁决）
        refuted_children = 0
        for c in list(cog._claims.values()):  # noqa: SLF001——读面（demo）
            if pid3 not in c.depends_on or c.status in ("refuted", "retired"):
                continue
            m = json.loads(c.statement)
            lb = str(m["label"])
            if lb not in "0123456789":
                continue
            v = live_check(tuple(m["path"]), dpath3, lb)
            await cog.revalidated(c.claim_id, verdict="pass" if v else "fail",
                                  env_version=f"{APP}:sidebar")
            if v:
                continue
            conf = await cog.decay_confidence(
                c.claim_id, factor=0.1, reason="env_upgrade revalidation fail")
            if conf < 0.2:
                await cog.refute(c.claim_id, [
                    f"env_upgrade:{APP}:sidebar", f"live_check:{lb}"])
                refuted_children += 1
        # 父主张：布局有效性代理 = '7' 抽查
        parent_ok = live_check(labels3["7"], dpath3, "7")
        await cog.revalidated(pid3, verdict="pass" if parent_ok else "fail",
                              env_version=f"{APP}:sidebar")
        cascaded: list[str] = []
        if not parent_ok:
            conf = await cog.decay_confidence(
                pid3, factor=0.1, reason="env_upgrade revalidation fail")
            if conf < 0.2:
                cascaded = await cog.refute(pid3, [
                    f"env_upgrade:{APP}:sidebar", "live_check:layout-proxy"])
        print(f"  活检查：子直接推翻 {refuted_children}｜父推翻级联 "
              f"{len(cascaded)}｜Claim 图事件全留痕")

        # 冷启动还原布局 → 重标 → v2 记忆
        hard_reset(APP)
        els4 = enumerate_elements(APP, cfg)
        restored = len(els4) <= before + 2
        print(f"  冷启动还原 UI 树（{len(els4)} 元素，"
              f"{'已还原' if restored else '⚠ 侧栏仍在——按当前布局重标'}）")
        labels4, cached4 = get_keypad(APP, els4, cfg.store_root)
        display4 = _display_element(els4)
        ok4, run_id4 = await task_run(
            cfg, store, labels4, tuple(display4.path), tag="重学")
        ok &= ok4
        if ok4:
            parent4, children4 = await record_layout(
                cog, APP, keypad_signature(els4), labels4,
                tuple(display4.path), len(els4), evidence_run=run_id4)
            await _accept_all(cog, [parent4, *children4], f"run:{run_id4}")
            print(f"  v2 记忆写入：父 1 + 子 {len(children4)}"
                  "（旧 refuted 留痕，新旧并存可审计）")

        cog.refresh()
        total = len(cog._claims)  # noqa: SLF001——读面统计
        active = sum(1 for c in cog._claims.values()  # noqa: SLF001
                     if c.status not in ("refuted", "retired"))
        print(f"\n[memory] Claim 图：共存 {total} 主张"
              f"（活跃 {active}，含历史 refuted）｜"
              f"{'PASS ✓' if ok else 'FAIL ✗'}")
        return 0 if ok else 1
    finally:
        store.close()


if __name__ == "__main__":
    main()
