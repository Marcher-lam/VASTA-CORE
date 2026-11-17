"""P6：≥10 种子 GUI 评测——W-1 标准施加到 CUA 路径（vm-gui 计划 §一目标 3）。

种子语义（§八 Phase 4 前置发现的对策，缺一即伪种子）：
- 独立 store（``CUA_STORE_ROOT/seed-i``）→ fresh 标定 + fresh 响应缓存；
- VLM 请求注入 ``temperature>0`` 与 ``seed``（vlm.py 默认 temperature=0
  贪心——不开启则 10 个种子是同一次解码的重放，CI 无意义）；
- 每种子一轮 ``examples.cua.eval``（任务集 6 条）→ 成功率 → 集合过
  ``seed_confidence_interval``（9.11 契约，与 real_eval 同一数学）→
  ``evaluation.real_seed_ci`` 留痕（W-1 三要素之第三：CI 并入报告结构
  ——本 runner 的 summary.json 即报告工件，事件为 trace）。

崩溃种子诚实口径：子进程崩 = 该种子成功率 0.0 并记入 crashed（agent
健壮性本身是被测属性；不用缺号样本算 CI）。

运行（VM 内 Terminal；宿主机 relay 已起时）：
  CUA_BASE_URL=http://192.168.64.1:1235/v1 \
  uv run python -m examples.cua.seeds [--seeds 10] [--temperature 0.7]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from vasta_protocols.sequencer import EventSequencer
from vasta_storage import SqliteStorage
from vastacore.agents.real_eval import W1_MIN_SEEDS
from vastacore.governance.revalidation import seed_confidence_interval

from .config import REPO_ROOT, CuaConfig

#: eval 输出的 [auto] 汇总行（取最后一处）
_RATE_RE = re.compile(r"\[auto\]\s*成功率\s*(\d+)/(\d+)")

#: 单种子上限：实测（2026-11-13 二跑）单任务 170-700s（temperature>0
#: 下 thinking 失控样态最贵）+ 标定 ~90s——6 任务正常需 20-35 分钟，
#: 2400s 封顶既装得下健康种子又能抓真挂死；超时也必须留下部分输出
#: （首跑教训：subprocess.run 超时异常会把 stdout 一起吞掉）
_SEED_TIMEOUT_S = 3600  # 40→60min：infra 卡顿判慢不判死（run4 教训）


def _run_seed(seed: int, temperature: float, base: Path) -> dict[str, Any]:
    """跑一个种子：子进程隔离（独立 env + 独立 store），任何失败=0 分记录。

    超时/崩溃都落 partial 日志（首跑教训：subprocess.run 超时异常会把
    stdout 一起吞掉）；子进程独立进程组，杀全组（osascript 孙进程不残留）。
    """
    env = {**os.environ,
           "CUA_SEED": str(seed),
           "CUA_TEMPERATURE": str(temperature),
           "CUA_STORE_ROOT": str(base / f"seed-{seed}")}
    log = base / f"seed-{seed}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    rc: int | None = None
    out = err = ""
    try:
        proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-u", "-m", "examples.cua.eval"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=env, start_new_session=True)
        try:
            out, err = proc.communicate(timeout=_SEED_TIMEOUT_S)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            out, err = proc.communicate()  # SIGKILL 后回收残余输出并收尸
            rc = proc.returncode
    except Exception as exc:  # noqa: BLE001 ——单种子任何故障不炸批次
        err = f"runner 异常：{type(exc).__name__}: {exc}"
    log.write_text(f"rc={rc}\n{out}\n=== stderr ===\n{err}", encoding="utf-8")
    matches = list(_RATE_RE.finditer(out or ""))
    hit = matches[-1] if matches else None  # 最后一处 [auto] 汇总行
    rate = int(hit.group(1)) / int(hit.group(2)) if hit else 0.0
    # crashed 只认"没跑出汇总行"（eval 的 rc=1 仅表示有任务未通过，
    # 属被测结果不是故障——四跑实测曾把两者混报）
    return {"seed": seed, "rate": rate,
            "crashed": hit is None,
            "rc": rc, "elapsed_s": round(time.time() - t0, 1)}


async def main() -> int:
    ap = argparse.ArgumentParser(description="≥10 种子 GUI 评测（W-1 口径）")
    ap.add_argument("--seeds", type=int, default=W1_MIN_SEEDS,
                    help=f"种子数（≥{W1_MIN_SEEDS} 强制）")
    ap.add_argument("--temperature", type=float, default=0.3,
                    help="VLM 采样温度（0=贪心，多种子评测须 >0；二跑"
                         "实测 0.7 令 thinking 失控频发，0.3 平衡独立"
                         "采样与空烧预算）")
    ap.add_argument("--level", type=float, default=0.95,
                    choices=[0.90, 0.95, 0.99])
    args = ap.parse_args()
    if args.seeds < W1_MIN_SEEDS:
        raise SystemExit(f"≥{W1_MIN_SEEDS} 种子强制（W-1 口径），"
                         f"得到 {args.seeds}")
    if args.temperature <= 0:
        raise SystemExit("temperature 须 >0（贪心解码下种子无独立性）")
    cfg = CuaConfig()
    base = REPO_ROOT / ".vasta-seeds"
    base.mkdir(parents=True, exist_ok=True)
    print(f"[seeds] {args.seeds} 种子 × temperature={args.temperature}"
          f"｜model={cfg.vlm_model}｜store={base}", flush=True)
    rows: list[dict[str, Any]] = []
    for i in range(args.seeds):
        row = _run_seed(i, args.temperature, base)
        rows.append(row)
        print(f"[seeds] seed={row['seed']} rate={row['rate']:.2f}"
              f"{'（崩溃 rc=' + str(row['rc']) + '）' if row['crashed'] else ''}"
              f"｜{row['elapsed_s']}s｜累计 {i + 1}/{args.seeds}", flush=True)
    rates = [r["rate"] for r in rows]
    ci = seed_confidence_interval(rates, level=args.level)
    crashed = [r["seed"] for r in rows if r["crashed"]]
    summary = {"model": cfg.vlm_model, "temperature": args.temperature,
               "seeds": [r["seed"] for r in rows], "rates": rates,
               "crashed": crashed, "ci": ci, "rows": rows,
               "seed_semantics": "独立 store + VLM seed/temperature 注入"
                                 "（vlm.py 贪心解码对策）；崩溃=0 分入样"}
    (base / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    store = SqliteStorage(base / "summary")
    sequencer = EventSequencer(store, "evaluation",
                               tenant_id=cfg.tenant_id,
                               project_id=cfg.project_id)
    await sequencer.emit("evaluation.real_seed_ci", {
        "adapter": f"cua-vm:{cfg.vlm_model}",
        "seeds": summary["seeds"], "ci": ci,
        "temperature": args.temperature, "crashed": crashed})
    print(f"[seeds] 成功率集 {[f'{r:.2f}' for r in rates]}", flush=True)
    print(f"[seeds] CI@{args.level:.0%}: [{ci['low']:.3f}, {ci['high']:.3f}]"
          f"（n={ci['n']} mean={ci['mean']:.3f}）", flush=True)
    print(f"[seeds] 报告 {base / 'summary.json'}"
          f"｜留痕 store {base / 'summary'}", flush=True)
    return 1 if crashed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
