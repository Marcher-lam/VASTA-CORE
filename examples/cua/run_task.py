"""P1 旗舰：Calculator 任务 42×3 经六段链执行到 126。

与 AgentSession 的差异（零侵入前提下的公开 API 组装）：
- 直接组装 RunEngine + ToolGateway——拿到 execute_contracted 的
  ``verifiers=`` 注入点（AgentSession.act 不透传自定义核验器）；
- 每个原子动作一个契约（click_mark），期望由任务计划确定性给出，
  核验走 AxDisplayVerifier（AX 直读，INV-06）；
- 截图（前/后）在动作链内落 CAS，事件流全程留痕，末尾输出六段链
  审计 + 时间线 + 首偏差定位。

任务：显示屏打 42 → × → 3 → = → 结果须为 126。
运行：uv run python -m examples.cua.run_task
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image

from vasta_contracts import ActionContract, Prediction, audit_six_segment
from vasta_protocols.ids import new_run_id
from vasta_runtime import Budget, RunContext, RunEngine
from vasta_runtime.gateway import ToolGateway
from vasta_storage import SqliteStorage, first_deviation, render_text, timeline

from .ax import enumerate_elements, frontmost_app, screenshot_png
from .calib import _display_element, get_keypad, hard_reset  # noqa: PLC2701
from .config import CuaConfig
from .env import DesktopEnv
from .marks import build_marks, crop_window
from .tools import ClickMarkTool
from .verifiers import AxDisplayVerifier

#: 任务计划：label（标定键）→ 期望 DSL（核验规则）。
TASK_PLAN: list[tuple[str, str]] = [
    ("4", "display=4"),
    ("2", "display=42"),
    ("×", "display_contains=×"),
    ("3", "display_contains=3"),
    ("=", "display=126"),
]


def build_contract(goal: str, mark: int, expect: str) -> ActionContract:
    """click_mark 契约（六必填段齐全；risk 取清单分级 R2）。"""
    return ActionContract(
        tool="click_mark", args={"mark": mark}, goal=goal, risk="R2",
        preconditions=[f"标记 {mark} 存在于当前标记表", "目标应用前台"],
        prediction=Prediction(
            changes=[expect],
            invariants=["窗口布局不变", "非目标应用不受影响"],
        ),
        success_criteria=[f"AX 读屏满足 {expect}"],
        failure_criteria=["点击未生效", "目标应用失焦或消失",
                          "显示屏值与期望不符"],
        verify_with=["ax_display"], timeout_ms=15_000,
    )


async def run() -> int:
    cfg = CuaConfig()
    app = "Calculator"

    print(f"[task] hard_reset {app} + 标定（缓存优先）…")
    hard_reset(app)
    elements = enumerate_elements(app, cfg)
    labels, cached = get_keypad(app, elements, cfg.store_root)
    display = _display_element(elements)
    print(f"  标定 {len(labels)} 钮（{'缓存' if cached else '全量'}）｜"
          f"显示屏 path={tuple(display.path)}")

    # 标记表（几何签名与 probe 同源；窗口在任务期内不动）
    from .ax import screen_info  # noqa: PLC0415

    shot = screenshot_png()
    scale = Image.open(io.BytesIO(shot)).width / screen_info()["pt_w"]
    win = next(e for e in elements if e.path == (0,))
    _, in_elements = crop_window(shot, elements, win, scale)
    marks = build_marks(in_elements, scale, (win.w, win.h),
                        max_marks=cfg.max_marks)
    mark_by_path = {tuple(m["path"]): m["mark"] for m in marks}
    marks_table: dict[int, dict] = {m["mark"]: m for m in marks}
    label_to_mark = {lb: mark_by_path[labels[lb]]
                     for lb, _ in TASK_PLAN
                     if lb in labels and labels[lb] in mark_by_path}
    missing = [lb for lb, _ in TASK_PLAN if lb not in label_to_mark]
    if missing:
        print(f"[task] ✗ 标定按钮未进标记表: {missing}", file=sys.stderr)
        return 2
    print(f"  标记表 {len(marks_table)} 项；计划 {label_to_mark}")

    # ── 组装（公开 API；AgentSession 同构 + verifiers 注入点）──
    store = SqliteStorage(Path(cfg.store_root) / "store")
    gateway = ToolGateway()
    gateway.register(ClickMarkTool(
        app, lambda: marks_table, store, tuple(display.path),
        tenant_id=cfg.tenant_id, project_id=cfg.project_id))
    env = DesktopEnv(app, tuple(display.path))
    run_id = new_run_id()
    context = RunContext.create(run_id=run_id, seed=42)
    engine = await RunEngine.create(
        env=env, store=store, budget=Budget(max_actions=len(TASK_PLAN) + 4),
        run_context=context, capture_observations=True,
        tool_gateway=gateway,
    )

    verifier = AxDisplayVerifier()
    interrupted = False
    try:
        await engine.start()
        await engine.reset()
        print(f"\n[task] run_id={run_id}｜六段链执行 42×3 …")
        for label, expect in TASK_PLAN:
            if frontmost_app() != app:
                from .ax import activate_app  # noqa: PLC0415

                activate_app(app)
            mark = label_to_mark[label]
            contract = build_contract(f"计算器键入 {label!r}", mark, expect)
            t0 = time.monotonic()
            try:
                await engine.execute_contracted(
                    contract, verifiers={"ax_display": verifier})
                outcome = "链返回"
            except Exception as exc:  # 策略拒/超时/预算——诚实报错
                interrupted = True
                outcome = f"中断: {type(exc).__name__}: {str(exc)[:70]}"
            print(f"  {'✗' if interrupted else '·'} {label!r:>4} → {expect:<22}"
                  f" {time.monotonic() - t0:4.1f}s  {outcome}")
            if interrupted:
                break
        if not interrupted:
            await engine.complete()
    finally:
        events: list[Any] = list(store.iter_run_events(run_id))

        # ── 诚实计分：核验结论以事件流为准（链返回≠核验通过）──
        ver_events = [e for e in events if e.type.startswith("verification.")]
        passed = sum(1 for e in ver_events if e.type == "verification.passed")
        deviated = [e for e in events if e.type == "verification.deviated"]
        ok_all = (not interrupted and passed == len(TASK_PLAN)
                  and engine.state.value == "completed")

        # ── 证据面：六段链审计 + 核验事实 + 时间线 + 首偏差 ──
        audit = audit_six_segment(events)
        print("\n[task] 六段链审计："
              f"total={audit.total} complete={audit.complete} "
              f"rejected={audit.rejected} "
              f"legal={audit.all_success_paths_complete}")
        print(f"[task] 核验事实：passed={passed}/{len(TASK_PLAN)}"
              f"{'（存在偏差：' + str(len(deviated)) + ' 次）' if deviated else ''}")
        for e in deviated:
            ver = json.dumps(e.payload.get("verifiers", {}), ensure_ascii=False)[:200]
            print(f"  ⚠ seq={e.seq} {ver}")
        arts = set()
        for e in events:
            refs = e.payload.get("artifact_refs")
            if isinstance(refs, list):
                arts.update(refs)
            for k in ("result_ref", "contract_ref"):
                if e.payload.get(k):
                    arts.add(e.payload[k])
        print(f"[task] 事件 {len(events)} 条｜引用工件 {len(arts)} 个"
              f"｜run 状态 {engine.state.value}")
        hit = first_deviation(events)
        print(f"[task] 首偏差: {hit.type if hit else '无（干净跑）'}")
        print("\n" + render_text(timeline(events))[:1500])
        store.close()
    print(f"\n[task] {'PASS ✓' if ok_all else 'FAIL ✗'}"
          f"（display=126 核验{'通过' if passed == len(TASK_PLAN) else '未全通过'}）")
    return 0 if ok_all else 1


def main() -> None:
    try:
        sys.exit(asyncio.run(run()))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
