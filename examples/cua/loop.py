"""P2-A：VLM 驱动的 CUA 闭环（Calculator）。

与 run_task 的差异：任务只给**自然语言目标**，每一步由 VLM 看
「当前标记截图」决定点哪个编号，并**自己声明点击后的显示屏预期**
（prediction 由模型填）——契约构造 → 六段链 → AX 确定性核验
（核验器不信模型自评，只认 AX 直读事实）。核验偏差由平台 FR-037
有界恢复处置；循环每步带全新感知（截图重渲染），模型看得见纠正。

终局判定不由模型说了算：VLM 报 done 后，由 runner 用 AX 读屏
对任务目标做最终断言。

运行：uv run python -m examples.cua.loop --task "计算 42 乘 3" --answer 126
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
from vasta_protocols.ids import new_run_id
from vasta_runtime import Budget, RunContext, RunEngine
from vasta_runtime.gateway import ToolGateway
from vasta_storage import SqliteStorage, first_deviation

from .ax import AxError, activate_app, frontmost_app, read_display
from .calib import _display_element, get_keypad, hard_reset  # noqa: PLC2701
from .config import CuaConfig
from .env import DesktopEnv
from .scene import capture_scene
from .tools import ClickMarkTool
from .verifiers import AxDisplayVerifier

SYSTEM_PROMPT = (
    "你是 macOS 桌面操作助手。屏幕截图上叠加了带编号的方框标记"
    "（左上角数字牌）。根据问题找到对应元素，只输出一个 JSON 对象，"
    "不要输出任何其他文字。"
)


def step_prompt(task: str, display: str | None,
                history: list[dict], feedback: str | None) -> str:
    hist = json.dumps(history[-4:], ensure_ascii=False)
    failed = any(not h.get("verified", True) for h in history)
    recovery = ("\n注意：历史中存在 verified=false 的步骤——你点错了按钮。"
                "先按 AC（清除/归零按钮）清零，再从头正确输入。"
                if failed else "")
    fb = f"\n系统反馈（上一步未执行）：{feedback}" if feedback else ""
    return (
        f"任务：在计算器应用里完成「{task}」。\n"
        f"当前 AX 显示屏读数：{display!r}\n"
        f"已执行步骤（verified 为独立核验器判定，非你的自评）：{hist}"
        f"{recovery}{fb}\n\n"
        "决定下一步要点哪个按钮（候选：数字 0-9、运算符 + − × ÷、"
        "等号 =、清除 AC、百分号 %）。只输出 JSON：\n"
        '{"button": "<按钮字符>", "mark": <该按钮在截图中的编号>,'
        ' "answer": "<仅当 button 为 = 时：你计算的最终结果>"}'
    )


def derive_expect(button: str, display: str | None,
                  answer: str | None) -> str:
    """意图 → 确定性期望（prediction 不让模型自由填写）。"""
    d = (display or "").replace(" ", "")
    if button == "AC":
        return "0"
    if button in {"+", "−", "×", "÷", "%"}:
        return f"display_contains={button}"
    if button == "=":
        return f"display={(answer or '').strip()}"
    if button.isdigit() and d.lstrip("-").isdigit():
        base = "" if d in {"0", ""} else d
        return f"display={base}{button}"  # 数字拼接（表达式行）
    return f"display_contains={button}"


def build_contract(goal: str, mark: int, expect: str) -> ActionContract:
    """模型填 prediction（expect），AX 核验器裁决（不信自评）。"""
    return ActionContract(
        tool="click_mark", args={"mark": mark}, goal=goal, risk="R2",
        preconditions=[f"标记 {mark} 存在于当前标记表", "目标应用前台"],
        prediction=Prediction(
            changes=[expect],  # derive_expect 已产出完整规则（display=…/contains=…）
            invariants=["窗口布局不变", "非目标应用不受影响"],
        ),
        success_criteria=[f"AX 读屏包含 {expect!r}"],
        failure_criteria=["点击未生效", "目标应用失焦", "显示屏与预期不符"],
        verify_with=["ax_display"], timeout_ms=15_000,
    )


async def run_loop(task: str, answer: str, max_steps: int) -> int:
    cfg = CuaConfig()
    app = "Calculator"

    print(f"[loop] hard_reset + 标定（缓存优先）…")
    from .ax import enumerate_elements  # noqa: PLC0415

    elements = None
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
            print(f"  标定失败（{str(exc)[:60]}）——重试 ({attempt + 1}/3)")
    display_el = _display_element(elements)
    display_path = tuple(display_el.path)
    print(f"  标定 {len(labels)} 钮（{'缓存' if cached else '全量'}）")

    # 首帧场景（标记表跨步复用；窗口任务期内不动）
    scene0 = capture_scene(app, cfg, elements=elements)
    marks_table = {m["mark"]: m for m in scene0.marks}
    print(f"  标记表 {len(marks_table)} 项｜scale={scene0.scale}")

    store = SqliteStorage(Path(cfg.store_root) / "store")
    gateway = ToolGateway()
    gateway.register(ClickMarkTool(
        app, lambda: marks_table, store, display_path,
        tenant_id=cfg.tenant_id, project_id=cfg.project_id))
    env = DesktopEnv(app, display_path)
    run_id = new_run_id()
    context = RunContext.create(run_id=run_id, seed=42)
    engine = await RunEngine.create(
        env=env, store=store, budget=Budget(max_actions=max_steps + 3),
        run_context=context, capture_observations=True,
        tool_gateway=gateway,
    )
    vlm = _vlm(cfg, store)
    verifier = AxDisplayVerifier()
    history: list[dict] = []
    # mark → 语义（标定表反查；意图一致性闸的事实来源）
    mark_of_path = {tuple(m["path"]): m["mark"] for m in scene0.marks}
    mark_semantic = {mark_of_path[path]: lb
                     for lb, path in labels.items() if path in mark_of_path}

    try:
        await engine.start()
        await engine.reset()
        print(f"\n[loop] run_id={run_id}｜任务「{task}」期望终值 {answer!r}")
        done_claimed: dict | None = None
        feedback: str | None = None
        step = 0
        while step < max_steps:
            step += 1
            if frontmost_app() != app:
                activate_app(app)
            scene = capture_scene(app, cfg, elements=scene0.elements,
                                  marks=scene0.marks)
            display = read_display(app, display_path)
            t0 = time.monotonic()
            try:
                decision = await vlm.ask_json(
                    SYSTEM_PROMPT,
                    step_prompt(task, display, history, feedback),
                    images=[(scene.marked, "image/png")], max_tokens=1600)
            except RuntimeError as exc:
                print(f"  step {step}: VLM 错误 {str(exc)[:70]}")
                break
            dt = time.monotonic() - t0
            feedback = None

            button = str(decision.get("button", "")).strip()
            try:
                mark = int(decision.get("mark"))
            except (TypeError, ValueError):
                mark = None
            answer_claim = str(decision.get("answer", "")).strip()

            # ── 意图-定位一致性闸（标定事实裁决，不点击即反馈）──
            if button not in labels:
                feedback = f"按钮 {button!r} 不在已标定键位中"
                print(f"  step {step}: ✗闸 {feedback}（{dt:.1f}s）")
                step -= 1  # 未消耗动作，不计步
                continue
            if mark is None or mark_semantic.get(mark) != button:
                actual = mark_semantic.get(mark)
                feedback = (f"你声明按钮 {button!r} 但编号 {mark} 实际是 "
                            f"{actual!r}——重新看编号牌")
                print(f"  step {step}: ✗闸 {feedback}（{dt:.1f}s）")
                step -= 1
                continue

            expect = derive_expect(button, display, answer_claim)
            history.append({"step": step, "button": button, "mark": mark,
                            "expect": expect})
            from vasta_runtime.supervisor import (  # noqa: PLC0415
                SupervisorEscalationError,
            )

            escalated = False
            try:
                await engine.execute_contracted(
                    build_contract(f"任务「{task}」：按 {button!r}",
                                   mark, expect),
                    verifiers={"ax_display": verifier})
            except SupervisorEscalationError as exc:
                escalated = True
                print(f"  step {step}: ⚠ Supervisor 熔断——{str(exc)[:60]}")
            except Exception as exc:
                print(f"  step {step}: EXC {type(exc).__name__}: "
                      f"{str(exc)[:50]}")
            after = read_display(app, display_path)
            # verified 用确定性镜像（与核验器同规则），不信链返回值
            history[-1]["display_after"] = after
            want = expect.split("=", 1)[1] if "=" in expect else expect
            history[-1]["verified"] = bool(
                after and want and want in after.replace(" ", ""))
            print(f"  step {step}: {button!r:>3}@mark{mark:<3}"
                  f" expect={expect!r:<14} → display={after!r:<10} "
                  f"{'✓' if history[-1]['verified'] else '✗核验失败'}"
                  f"（VLM {dt:.1f}s）")
            if escalated:
                break
            if history[-1]["verified"] and button == "=":
                done_claimed = {"done": True, "answer": answer_claim}
                break

        # ── 终局断言：runner 用 AX 事实裁决，不信模型自评 ──
        final = read_display(app, display_path)
        final_norm = (final or "").replace(" ", "")
        passed = (final_norm == answer
                  or (done_claimed is not None
                      and str(done_claimed.get("answer", "")).strip()
                      .replace(" ", "") == answer == final_norm))
        print(f"\n[loop] 终值断言：AX display={final!r} vs 任务答案 "
              f"{answer!r} → {'PASS ✓' if passed else 'FAIL ✗'}")
        if passed:
            await engine.complete()
    finally:
        events: list[Any] = list(store.iter_run_events(run_id))
        audit = audit_six_segment(events)
        ver_pass = sum(1 for e in events
                       if e.type == "verification.passed")
        ver_dev = sum(1 for e in events
                      if e.type == "verification.deviated")
        print(f"[loop] 六段链 complete={audit.complete}/{audit.total}"
              f"｜核验 passed={ver_pass} deviated={ver_dev}"
              f"｜事件 {len(events)} 条")
        hit = first_deviation(events)
        print(f"[loop] 首偏差: {hit.type if hit else '无（干净跑）'}"
              f"｜run 状态 {engine.state.value}")
        store.close()
    return 0 if passed else 1


def _vlm(cfg, store):
    from .vlm import VlmClient  # noqa: PLC0415

    return VlmClient(cfg, store)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default="计算 42 乘 3")
    parser.add_argument("--answer", default="126")
    parser.add_argument("--max-steps", type=int, default=10)
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(run_loop(args.task, args.answer,
                                      args.max_steps)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
