"""P5：任务集批量评测（eval）——把 CUA 闭环变成可度量报表。

每任务：run_agent（auto 模式：memory 命中→零视觉；否则 vision）
+ guardrails 闸全程值守；指标：成功率/步数/VLM 决策数/核验通过/
首偏差/闸拦截/熔断/耗时。--compare-vision N 追加 N 个任务的
vision 模式对照（量化记忆收益）。

报告落证据库（source=cua.eval.report）；退出码 = 全任务是否通过。
运行：uv run python -m examples.cua.eval [--limit 6] [--compare-vision 2]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from vasta_storage import SqliteStorage

from .config import CuaConfig
from .guard import build_guard, demo_denials
from .loop import AgentRunResult, run_agent

TASKS_PATH = Path(__file__).parent / "tasks" / "tasks.jsonl"


def load_tasks() -> list[dict]:
    rows = []
    for line in TASKS_PATH.read_text("utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _row(mode: str, tid: str, r: AgentRunResult) -> str:
    return (f"  {'✓' if r.ok else '✗'} [{mode:<6}] {tid:<12}"
            f" 路径={r.mode:<6} 步={r.steps} VLM={r.vlm_calls}"
            f" 核验={r.passed}✓/{r.deviated}✗ 闸拦={r.gate_blocks}"
            f"{' 熔断' if r.escalated else ''}"
            f" 首偏差={r.first_deviation or '无'} {r.elapsed:4.0f}s")


def _summary(mode: str, results: list[tuple[str, AgentRunResult]]) -> list[str]:
    rs = [r for _tid, r in results]
    if not rs:
        return [f"[{mode}] 无样本"]
    n = len(rs)
    ok = sum(r.ok for r in rs)
    return [
        f"[{mode}] 成功率 {ok}/{n} = {ok / n:.0%}"
        f"｜平均步数 {sum(r.steps for r in rs) / n:.1f}"
        f"｜平均 VLM 决策 {sum(r.vlm_calls for r in rs) / n:.1f}"
        f"｜平均耗时 {sum(r.elapsed for r in rs) / n:.0f}s",
        f"       核验通过 Σ{sum(r.passed for r in rs)} 偏差 Σ{sum(r.deviated for r in rs)}"
        f"｜闸拦截 Σ{sum(r.gate_blocks for r in rs)}"
        f"｜熔断 {sum(r.escalated for r in rs)}"
        f"｜memory 命中 {sum(1 for r in rs if r.mode == 'memory')}/{n}",
    ]


async def run_eval(limit: int, compare_vision: int,
                   base_mode: str) -> int:
    cfg = CuaConfig()
    store = SqliteStorage(Path(cfg.store_root) / "store")
    guard, _gconf, _gstate = build_guard(store, cfg)
    tasks = load_tasks()[:limit]
    print(f"[eval] 任务集 {len(tasks)} 个（{[t['id'] for t in tasks]}）"
          f"｜基模式 {base_mode}｜guardrails 闸值守")
    print("[eval] 闸门负例自证：")
    for line in await demo_denials(store, cfg):
        print("   ", line)

    all_results: list[tuple[str, str, AgentRunResult]] = []
    t0 = time.monotonic()
    try:
        for t in tasks:
            print(f"\n[eval] ▶ {t['id']}：{t['task']}（答案 {t['answer']}）")
            r = await run_agent(cfg, store, task=t["task"],
                                answer=t["answer"], mode=base_mode,
                                guard=guard, verbose=True)
            all_results.append((base_mode, t["id"], r))
        for t in tasks[:compare_vision]:
            print(f"\n[eval] ▶（vision 对照）{t['id']}")
            r = await run_agent(cfg, store, task=t["task"],
                                answer=t["answer"], mode="vision",
                                guard=guard, verbose=True)
            all_results.append(("vision", t["id"], r))

        # ── 报表 ──
        print("\n" + "═" * 78)
        print("[eval] 逐任务：")
        for mode, tid, r in all_results:
            print(_row(mode, tid, r))
        print("─" * 78)
        for m in dict.fromkeys(m for m, _t, _r in all_results):
            summary = _summary(
                m, [(tid, r) for mm, tid, r in all_results if mm == m])
            for line in summary:
                print(line)
        # 记忆收益对照（同任务 auto vs vision）
        if compare_vision:
            auto_by_id = {tid: r for m, tid, r in all_results
                          if m == base_mode}
            vis = [(tid, r) for m, tid, r in all_results if m == "vision"]
            for tid, r in vis:
                a = auto_by_id.get(tid)
                if a and a.mode == "memory" and r.mode == "vision":
                    print(f"       记忆收益[{tid}]：{r.elapsed:.0f}s→"
                          f"{a.elapsed:.0f}s｜VLM {r.vlm_calls}→"
                          f"{a.vlm_calls}（vision→memory）")

        ok_all = all(r.ok for _m, _t, r in all_results
                     if _m == base_mode)
        report = {
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "base_mode": base_mode, "total_wall_s": time.monotonic() - t0,
            "rows": [{"mode": m, "task": tid, **{
                k: getattr(r, k) for k in (
                    "ok", "mode", "steps", "vlm_calls", "passed",
                    "deviated", "first_deviation", "gate_blocks",
                    "guard_denies", "escalated", "elapsed")}}
                for m, tid, r in all_results],
        }
        sha = await store.save_artifact(
            json.dumps(report, ensure_ascii=False, sort_keys=True)
            .encode("utf-8"), mime="application/json",
            source="cua.eval.report",
            tags={"cua_kind": "eval_report"},
            tenant_id=cfg.tenant_id, project_id=cfg.project_id)
        print(f"\n[eval] 报告入库 sha256:{sha[:12]}…｜总耗时 "
              f"{time.monotonic() - t0:.0f}s｜"
              f"{'ALL PASS ✓' if ok_all else '存在失败 ✗'}")
        return 0 if ok_all else 1
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--compare-vision", type=int, default=0,
                        help="追加前 N 个任务的 vision 模式对照")
    parser.add_argument("--mode", choices=["auto", "vision", "memory"],
                        default="auto")
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(run_eval(args.limit, args.compare_vision,
                                      args.mode)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
