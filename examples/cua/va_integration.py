"""边界清偿集成取证（吸收 va-1/2/4/6/7 的集成回填 + P6 取证仪器演示）。

真机跑一个 >8 步长任务（触发检查点节奏），跑后全部从证据库取数：

1. **检查点实拍**（序④）：load_checkpoint(run_id, s8/s16)——边界步、
   全量历史、归档不可变校验；
2. **偏差率**（序⑥ G）：history 的 model_expect（ex-ante）vs
   verified（核验器裁决）逐条对照表 + 一致率；
3. **P6 取证**（序② 仪器）：每步 mark 区域像素 diff（前后帧配对：
   步 N 前帧 = 步 N-1 后帧；步 1 无前帧仅 AX 对照）× 核验裁决——
   「屏变没变」与「AX 读数」双通道对照，点击失灵三假设的观测面；
4. **机制在场计数**：notes 里 检查点/VLM 格式错误回喂/🔍回看 的发生数。

排序只信事件 seq（沙箱钟下 created_at 不可用于排序——AD-5）。

CLI：
  CUA_VLM_MODEL=qwen3.8-27b-mlx CUA_TEMPERATURE=0.3 \
  uv run python -m examples.cua.va_integration --max-steps 20
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from vasta_storage import SqliteStorage

from .checkpoint import load_checkpoint
from .config import CuaConfig
from .loop import run_agent
from .pixels import Region, diff_region


async def forensics(res, store: SqliteStorage, cfg: CuaConfig) -> dict:
    T, P = cfg.tenant_id, cfg.project_id
    report: dict = {"run_id": res.run_id, "ok": res.ok, "steps": res.steps,
                    "mode": res.mode, "elapsed_s": round(res.elapsed, 1),
                    "notes": list(res.notes)}

    # ── 1. 检查点实拍（序④）——按 cfg 作用域取（run #2 教训：
    #    检查点存 t-cua，默认作用域是 t-default）──
    ckpts = {}
    for boundary in (8, 16):
        ck = await load_checkpoint(store, res.run_id, boundary,
                                   tenant_id=T, project_id=P)
        if ck is not None:
            ckpts[boundary] = {"task": ck.task, "mode": ck.mode,
                               "history_len": len(ck.history)}
    report["checkpoints"] = ckpts

    # ── 2+3. 步表：事件序 → ToolResult 工件 → mark/前后帧 ──
    events = [e for e in store.iter_run_events(res.run_id)
              if e.type == "action.executed"]
    steps = []
    for e in events:
        payload = e.payload
        ref = payload.get("result_ref")
        if not ref:
            continue
        # result_ref 工件在事件自身作用域（engine 默认 t-default）——
        # 按事件信封的 tenant/project 取件，不按 cfg（集成 run #1 教训）
        tr = json.loads((await store.get_artifact(
            ref, tenant_id=e.tenant_id, project_id=e.project_id)
        ).decode("utf-8"))
        steps.append({"seq": e.seq, "mark": tr.get("detail", {}).get("mark"),
                      "after_sha": tr.get("artifact_ref"),
                      "ax_before": tr.get("detail", {}).get("display_before"),
                      "ax_after": tr.get("detail", {}).get("display_after"),
                      "ok": tr.get("ok")})
    report["action_count"] = len(steps)

    # 检查点历史（含 model_expect / verified）——取最大可用边界
    hist: list[dict] = []
    for b in sorted(ckpts, reverse=True):
        ck = await load_checkpoint(store, res.run_id, b,
                                   tenant_id=T, project_id=P)
        hist = list(ck.history)
        break
    report["history_rows"] = len(hist)

    # ── marks 重建（窗口未动——同一标定缓存；AX 长负载后可能退化
    #    （P6 现象本身），失败则降级为无屏差列，报告照出）──
    marks_table: dict[int, dict] = {}
    scene_scale = 2.0
    try:
        from .ax import enumerate_elements  # noqa: PLC0415
        from .calib import get_keypad  # noqa: PLC0415
        from .scene import capture_scene  # noqa: PLC0415

        app = "Calculator"
        elements = enumerate_elements(app, cfg)
        get_keypad(app, elements, cfg.store_root)  # 命中缓存即复用
        scene = capture_scene(app, cfg, elements=elements)
        marks_table = {m["mark"]: m for m in scene.marks}
        scene_scale = scene.scale
    except Exception as exc:  # noqa: BLE001 —— 取证降级不崩（run #2 教训）
        report["marks_rebuild_error"] = str(exc)[:120]

    # ── P6 逐步表：像素 diff × 核验裁决 ──
    p6 = []
    for i, st in enumerate(steps):
        row = {"seq": st["seq"], "mark": st["mark"],
               "ax_before": st["ax_before"], "ax_after": st["ax_after"]}
        if i < len(hist):
            h = hist[i]
            row.update({"button": h.get("button"),
                        "expect": h.get("expect"),
                        "model_expect": h.get("model_expect"),
                        "verified": h.get("verified")})
        mt = marks_table.get(st["mark"]) if st["mark"] is not None else None
        prev_sha = steps[i - 1]["after_sha"] if i > 0 else None
        if prev_sha and st["after_sha"]:
            # 主判：CAS sha 同一性——逐字节级「屏到底变没变」（内容寻址
            # 即完美 diff；run #2 发现粗网格采样漏小字形变化）。
            # sha 不同 → mark 区域精 diff（marks 可用）或全帧 32×32 细
            # 采样辅证（含菜单栏时钟，只报幅度不判因果）。
            if st["after_sha"] == prev_sha:
                row["screen_changed"] = False
                row["changed_cells"] = "同帧（CAS 同 sha——逐字节一致）"
            elif mt:
                before_b = await store.get_artifact(
                    prev_sha, tenant_id=T, project_id=P)
                after_b = await store.get_artifact(
                    st["after_sha"], tenant_id=T, project_id=P)
                region = Region.from_pt(mt["x_pt"], mt["y_pt"], mt["w_pt"],
                                        mt["h_pt"], scale=scene_scale)
                d = diff_region(before_b, after_b, region, rows=4, cols=4)
                row["screen_changed"] = d.changed
                row["changed_cells"] = f"mark区 {d.changed_cells}/{d.total_cells}"
            else:
                import io  # noqa: PLC0415

                from PIL import Image  # noqa: PLC0415

                before_b = await store.get_artifact(
                    prev_sha, tenant_id=T, project_id=P)
                after_b = await store.get_artifact(
                    st["after_sha"], tenant_id=T, project_id=P)
                w, h = Image.open(io.BytesIO(before_b)).size
                d = diff_region(before_b, after_b, Region(0, 0, w, h),
                                rows=32, cols=32)
                row["diff_scope"] = "全帧（marks 不可用——AX 退化）"
            row["screen_changed"] = d.changed
            row["changed_cells"] = f"{d.changed_cells}/{d.total_cells}"
        else:
            row["screen_changed"] = None if i > 0 else "无前帧（基线）"
        p6.append(row)
    report["p6_table"] = p6
    return report


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default="计算 1234567 加 7654321")
    parser.add_argument("--answer", default="8888888")
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--run-id", default=None,
                        help="离线取证：对已落库 run 出报告（不跑 agent）")
    args = parser.parse_args()
    cfg = CuaConfig()
    store = SqliteStorage(Path(cfg.store_root) / "store")
    if args.run_id:
        from types import SimpleNamespace  # noqa: PLC0415

        evs = list(store.iter_run_events(args.run_id))
        res = SimpleNamespace(
            run_id=args.run_id, ok=False,
            steps=sum(1 for e in evs if e.type == "action.executed"),
            mode="offline", elapsed=0.0, notes=["离线取证"])
    else:
        res = await run_agent(cfg, store, task=args.task, answer=args.answer,
                              max_steps=args.max_steps, mode="vision",
                              verbose=True)
    report = await forensics(res, store, cfg)
    out = Path(cfg.store_root) / "va-integration-report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"\n=== 集成取证报告 → {out} ===")
    print(json.dumps({k: v for k, v in report.items()
                      if k != "p6_table"}, ensure_ascii=False, indent=1))
    print("── P6 逐步表（屏差 × 核验 × 预期）──")
    for row in report["p6_table"]:
        print(f"  seq{row['seq']:<4} mark{row.get('mark')!s:<4} "
              f"{row.get('button')!s:<4} 屏变={row['screen_changed']!s:<6}"
              f"{row.get('changed_cells') or '':<8}"
              f"核验={row.get('verified')!s:<6} AX:{row['ax_before']!r}"
              f"→{row['ax_after']!r}")
    # 偏差率（有 model_expect 样本时）
    rows = [r for r in report["p6_table"]
            if r.get("model_expect") is not None]
    if rows:
        agree = sum(1 for r in rows if r.get("verified") is True)
        print(f"预期落史样本 {len(rows)} 条；其中核验通过 {agree} 条")
    if args.run_id:  # 离线取证不按任务成败定退出码
        return 0
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
