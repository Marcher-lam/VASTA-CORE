"""P2-A/P5：VLM 驱动的 CUA 闭环（三模式 + guardrails 闸）。

模式：
- ``vision``：标记截图 + 意图-定位分离闸（模型答 button+mark，
  标定表对质——不一致不点击、反馈重试）；
- ``memory``：Claim 图命中（P4）——**零视觉**：模型只做任务推理
  （纯文本问答下一步按钮），路径直取主张；抽查 1 次点击守门；
- ``auto``：先 memory（未命中/抽查败 → 回退 vision）。

每步动作先过 guardrails 动作闸（角色/委派/自治/矩阵/预算——
任一层拒即抛，动作不执行），再进六段链；核验偏差走 FR-037；
终局由 runner 用 AX 事实断言（不信模型自评）。

CLI：uv run python -m examples.cua.loop [--mode auto] [--task …] [--answer …]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vasta_contracts import ActionContract, Prediction, audit_six_segment
from vasta_protocols.ids import new_run_id
from vasta_runtime import Budget, RunContext, RunEngine
from vasta_runtime.gateway import ToolGateway
from vasta_runtime.supervisor import SupervisorEscalationError
from vasta_storage import SqliteStorage, first_deviation

from .ax import AxError, activate_app, frontmost_app, read_display
from .calib import _display_element, get_keypad, hard_reset, keypad_signature
from .config import CuaConfig
from .env import DesktopEnv
from .memory import recall_layout
from .scene import capture_scene
from .tools import ClickMarkTool
from .verifiers import AxDisplayVerifier

SYSTEM_PROMPT = (
    "你是 macOS 桌面操作助手。屏幕截图上叠加了带编号的方框标记"
    "（左上角数字牌）。根据问题找到对应元素，只输出一个 JSON 对象，"
    "不要输出任何其他文字。"
)


@dataclass
class AgentRunResult:
    """一次 agent 任务的完整结局（eval 聚合的数据单元）。"""

    task: str
    answer: str
    ok: bool
    run_id: str
    mode: str                     # 实际生效：memory / vision
    steps: int = 0                # 已执行的六段链步数
    vlm_calls: int = 0            # VLM 决策调用（含缓存命中）
    passed: int = 0               # verification.passed
    deviated: int = 0             # verification.deviated
    first_deviation: str | None = None
    gate_blocks: int = 0          # 意图-定位闸拦截（不点击，反馈重试）
    guard_denies: int = 0         # guardrails 拒绝（任务即止）
    escalated: bool = False       # Supervisor 熔断
    elapsed: float = 0.0
    engine_state: str = ""
    notes: list[str] = field(default_factory=list)


def _vision_prompt(task: str, display: str | None, history: list[dict],
                   feedback: str | None) -> str:
    hist = json.dumps(history[-4:], ensure_ascii=False)
    failed = any(not h.get("verified", True) for h in history)
    recovery = ("\n注意：历史中存在 verified=false——你点错了按钮。先按 AC"
                "（清除/归零）清零，再从头正确输入。" if failed else "")
    fb = f"\n系统反馈（上一步未执行）：{feedback}" if feedback else ""
    return (
        f"任务：在计算器应用里完成「{task}」。\n"
        f"当前 AX 显示屏读数：{display!r}\n"
        f"已执行步骤（verified 为独立核验器判定）：{hist}{recovery}{fb}\n\n"
        "决定下一步要点哪个按钮（候选：数字 0-9、运算符 + − × ÷、"
        "等号 =、清除 AC、百分号 %）。只输出 JSON：\n"
        '{"button": "<按钮字符>", "mark": <该按钮在截图中的编号>,'
        ' "answer": "<仅当 button 为 = 时：你计算的最终结果>"}'
    )


def _memory_prompt(task: str, display: str | None,
                   history: list[dict]) -> str:
    hist = json.dumps(history[-4:], ensure_ascii=False)
    failed = any(not h.get("verified", True) for h in history)
    recovery = ("\n注意：历史中存在 verified=false——先按 AC 清零重来。"
                if failed else "")
    return (
        f"任务：在计算器应用里完成「{task}」。\n"
        f"当前 AX 显示屏读数：{display!r}\n"
        f"已执行步骤（verified 为独立核验器判定）：{hist}{recovery}\n"
        "按钮位置已由布局记忆定位（截图仅供你了解界面，无需报编号）。"
        "只输出 JSON：\n"
        '{"button": "<下一步按钮字符>",'
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
    """模型填意图、runner 推导 prediction、AX 核验器裁决。"""
    return ActionContract(
        tool="click_mark", args={"mark": mark}, goal=goal, risk="R2",
        preconditions=[f"标记 {mark} 存在于当前标记表", "目标应用前台"],
        prediction=Prediction(
            changes=[expect],  # derive_expect 已产出完整规则
            invariants=["窗口布局不变", "非目标应用不受影响"],
        ),
        success_criteria=[f"AX 读屏满足 {expect}"],
        failure_criteria=["点击未生效", "目标应用失焦", "显示屏与预期不符"],
        verify_with=["ax_display"], timeout_ms=15_000,
    )


async def run_agent(cfg: CuaConfig, store: SqliteStorage, *, task: str,
                    answer: str, max_steps: int = 10,
                    mode: str = "auto", guard: Callable | None = None,
                    verbose: bool = True,
                    ) -> AgentRunResult:
    """跑一个任务（VLM 决策 + 闸 + 六段链 + AX 终局断言）。"""
    from .vlm import VlmClient  # noqa: PLC0415

    app = "Calculator"
    t_start = time.monotonic()
    res = AgentRunResult(task=task, answer=answer, ok=False, run_id="",
                         mode="vision")
    p = print if verbose else (lambda *_a, **_k: None)

    for attempt in (1, 2, 3):
        hard_reset(app)
        try:
            from .ax import enumerate_elements  # noqa: PLC0415

            elements = enumerate_elements(app, cfg)
            display_el = _display_element(elements)
            if display_el is None:  # 冷启动偶发无窗口/无显示屏
                raise AxError("显示屏元素缺失（窗口未就绪）")
            break
        except AxError as exc:
            if attempt == 3:
                raise
            time.sleep(1.5)  # AX 树就绪缓冲（冷启动后偶发缺显示屏元素）
            p(f"  [agent] 枚举失败重试 ({str(exc)[:50]})")
    display_path = tuple(display_el.path)
    sig = keypad_signature(elements)

    # ── 模式选择：memory 命中（零视觉）→ 否则 vision ──
    labels: dict[str, tuple[int, ...]] = {}
    marks_table: dict[int, dict] = {}
    mark_semantic: dict[int, str] = {}
    scene0 = None
    effective = "vision"
    if mode != "vision":
        hit = recall_layout(_cog(store, cfg), app, sig)
        if hit is not None:
            pid, labels, dpath, _ = hit
            from .calib import _CALIB_JS, _run_osascript  # noqa: PLC0415

            spec = {"app": app, "display": list(dpath), "mode": "spot",
                    "seven": list(labels["7"]), "settle_s": 0.25}
            out = json.loads(_run_osascript(_CALIB_JS, json.dumps(spec)))
            if str(out.get("spot", "")).strip() == "7":
                effective = "memory"
                res.notes.append(f"memory 命中 {len(labels)} 钮（抽查✓）")
            else:
                res.notes.append("memory 抽查失败 → 回退 vision")
                labels = {}
    label_to_mark: dict[str, int] = {}
    if effective == "vision":
        for attempt in (1, 2, 3):
            try:
                labels, cached = get_keypad(app, elements, cfg.store_root)
                break
            except AxError as exc:
                if attempt == 3:
                    raise
                p(f"  [agent] 标定失败重试 ({str(exc)[:50]})")
                hard_reset(app)
                from .ax import enumerate_elements  # noqa: PLC0415

                elements = enumerate_elements(app, cfg)
        scene0 = capture_scene(app, cfg, elements=elements)
        marks_table = {m["mark"]: m for m in scene0.marks}
        mark_of_path = {tuple(m["path"]): m["mark"] for m in scene0.marks}
        mark_semantic = {mark_of_path[path]: lb
                         for lb, path in labels.items() if path in mark_of_path}
    else:
        marks_table = {i + 1: {"path": list(p_), "x_pt": 0.0, "y_pt": 0.0,
                               "w_pt": 1.0, "h_pt": 1.0}
                       for i, p_ in enumerate(labels.values())}
        label_to_mark = {lb: i + 1 for i, lb in enumerate(labels)}
    if scene0 is None:  # 记忆模式也需要场景（截图锚定 + 窗口帧）
        scene0 = capture_scene(app, cfg, elements=elements)
    res.mode = effective
    p(f"  [agent] 模式={effective}｜标记表 {len(marks_table)}")

    # ── 引擎组装（env 软重置——调用方已 hard_reset）──
    gateway = ToolGateway()
    gateway.register(ClickMarkTool(
        app, lambda: marks_table, store, display_path,
        tenant_id=cfg.tenant_id, project_id=cfg.project_id))
    res.run_id = new_run_id()
    engine = await RunEngine.create(
        env=DesktopEnv(app, display_path, hard_on_reset=False),
        store=store, budget=Budget(max_actions=max_steps + 3),
        run_context=RunContext.create(run_id=res.run_id, seed=42),
        capture_observations=True, tool_gateway=gateway,
    )
    vlm = VlmClient(cfg, store)
    verifier = AxDisplayVerifier()
    history: list[dict] = []
    feedback: str | None = None
    done = False
    decisions = 0   # 决策计数（闸拦截不计步——单独封顶防死循环）
    vlm_errors = 0  # VLM 空 content 容错（重试 2 次再放弃）

    await engine.start()
    await engine.reset()
    p(f"\n[agent] run={res.run_id}｜「{task}」期望 {answer!r}｜模式 {effective}")
    while res.steps < max_steps and not done and decisions <= max_steps + 6:
        if frontmost_app() != app:
            activate_app(app)
        display = read_display(app, display_path)
        t0 = time.monotonic()
        res.vlm_calls += 1
        try:
            scene = capture_scene(app, cfg, elements=scene0.elements,
                                  marks=scene0.marks)
            if effective == "memory":
                # 记忆模式附无标记要求的截图（图像锚定推理——纯文本
                # 会让 qwen3.5 thinking 失控，实测 2026-11）
                decision = await vlm.ask_json(
                    SYSTEM_PROMPT,
                    _memory_prompt(task, display, history),
                    images=[(scene.scene, "image/png")], max_tokens=1600)
            else:
                decision = await vlm.ask_json(
                    SYSTEM_PROMPT,
                    _vision_prompt(task, display, history, feedback),
                    images=[(scene.marked, "image/png")], max_tokens=1600)
        except RuntimeError as exc:
            vlm_errors += 1
            res.notes.append(f"VLM 错误：{str(exc)[:60]}")
            p(f"  s{res.steps + 1}: ⚠VLM 错误 {str(exc)[:50]}"
              f"（{vlm_errors}/2）")
            if vlm_errors >= 2:
                break
            continue
        dt = time.monotonic() - t0
        feedback = None

        button = str(decision.get("button", "")).strip()
        answer_claim = str(decision.get("answer", "")).strip()
        decisions += 1
        if button == "C":  # 模型常把 AC 写成 C——同义归一
            button = "AC"
        if button not in labels:
            feedback = f"按钮 {button!r} 不可用"
            res.gate_blocks += 1
            p(f"  s{res.steps + 1}: ✗闸 {feedback}（{dt:.1f}s）")
            continue

        # 意图-定位闸（vision 模式）：标定表对质
        mark: int | None = None
        if effective == "vision":
            try:
                mark = int(decision.get("mark"))
            except (TypeError, ValueError):
                mark = None
            if mark is None or mark_semantic.get(mark) != button:
                res.gate_blocks += 1
                feedback = (f"你声明按钮 {button!r} 但编号 {mark} 实际是 "
                            f"{mark_semantic.get(mark)!r}——重看编号牌")
                p(f"  s{res.steps + 1}: ✗闸 {feedback}（{dt:.1f}s）")
                continue
        else:
            mark = label_to_mark[button]

        # guardrails 动作闸（在一切执行路径之前）
        if guard is not None:
            from vasta_protocols.protocols import Action  # noqa: PLC0415

            try:
                await guard(Action(tool="click_mark", args={"mark": mark}))
            except Exception as exc:
                res.guard_denies += 1
                res.notes.append(f"guard 拒绝：{getattr(exc, 'code', exc)}")
                p(f"  s{res.steps + 1}: ⚠guard 拒绝"
                  f"（{getattr(exc, 'code', type(exc).__name__)}）——任务终止")
                break

        expect = derive_expect(button, display, answer_claim)
        res.steps += 1
        history.append({"step": res.steps, "button": button, "mark": mark,
                        "expect": expect})
        try:
            await engine.execute_contracted(
                build_contract(f"任务「{task}」：按 {button!r}", mark, expect),
                verifiers={"ax_display": verifier})
        except SupervisorEscalationError as exc:
            res.escalated = True
            res.notes.append(f"Supervisor 熔断：{str(exc)[:50]}")
            p(f"  s{res.steps}: ⚠ Supervisor 熔断——{str(exc)[:50]}")
            break
        except Exception as exc:
            res.notes.append(f"链异常 {type(exc).__name__}: {str(exc)[:40]}")
        after = read_display(app, display_path)
        want = expect.split("=", 1)[1] if "=" in expect else expect
        history[-1]["display_after"] = after
        history[-1]["verified"] = bool(after and want
                                       and want in after.replace(" ", ""))
        p(f"  s{res.steps}: {button!r:>3}@{mark:<3} {expect!r:<16}"
          f" → {after!r:<10}"
          f" {'✓' if history[-1]['verified'] else '✗'}（{dt:.1f}s）")
        if history[-1]["verified"] and button == "=":
            done = True

    # ── 终局断言 + 计分（只认事件流）──
    final = read_display(app, display_path)
    final_norm = (final or "").replace(" ", "")
    res.ok = done and final_norm == answer
    if res.ok:
        await engine.complete()
    events: list[Any] = list(store.iter_run_events(res.run_id))
    res.passed = sum(1 for e in events if e.type == "verification.passed")
    res.deviated = sum(1 for e in events if e.type == "verification.deviated")
    hit = first_deviation(events)
    res.first_deviation = hit.type if hit else None
    res.engine_state = engine.state.value
    res.elapsed = time.monotonic() - t_start
    audit = audit_six_segment(events)
    p(f"[agent] 终值 {final_norm!r} vs {answer!r} → "
      f"{'PASS ✓' if res.ok else 'FAIL ✗'}｜核验 {res.passed}✓/{res.deviated}✗"
      f"｜链 {audit.complete}/{audit.total}｜首偏差 "
      f"{res.first_deviation or '无'}｜{res.elapsed:.0f}s")
    for note in res.notes:
        p(f"  · {note}")
    return res


_COG_CACHE: dict[int, Any] = {}


def _cog(store: SqliteStorage, cfg: CuaConfig) -> Any:
    """CognitionService 惰性单例（同 store 句柄，免重复投影重建）。"""
    key = id(store)
    if key not in _COG_CACHE:
        from vasta_cognition import CognitionService  # noqa: PLC0415

        _COG_CACHE[key] = CognitionService(
            store, tenant_id=cfg.tenant_id, project_id=cfg.project_id)
    return _COG_CACHE[key]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default="计算 42 乘 3")
    parser.add_argument("--answer", default="126")
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--mode", choices=["auto", "vision", "memory"],
                        default="auto")
    args = parser.parse_args()
    cfg = CuaConfig()
    store = SqliteStorage(Path(cfg.store_root) / "store")
    try:
        from .guard import build_guard  # noqa: PLC0415

        guard, _, _ = build_guard(store, cfg)
        result = asyncio.run(run_agent(
            cfg, store, task=args.task, answer=args.answer,
            max_steps=args.max_steps, mode=args.mode, guard=guard))
        sys.exit(0 if result.ok else 1)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
