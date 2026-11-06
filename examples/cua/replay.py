"""P3：确定性回放（AD-5 桌面版）——录制 run 的字节级复现。

语义（对齐平台 AD-5）：
- 回放模式下适配器必须是**确定性替身**（RunContext.replay_mode=True +
  adapter.deterministic=True 过守卫；真实桌面适配器一律拒绝）；
- 不碰屏幕：ReplayEnv 按录制序供给观察帧，ReplayClickTool 按录制序
  返回原 ToolResult（字节相同 ⇒ CAS sha 相同 ⇒ result_ref 相同）；
- 契约从录制的 contract 工件**原样重建**（不重新构造）；
- 核验器照常运行于回放证据（确定性函数 → 同结论）；
- 终判：两条 run 的归一化事件流（抹 run_id/ts/event_id/parent）逐字节
  对比——这是 quickstart「同 seed 跨根目录字节级复现」的桌面版。

运行：uv run python -m examples.cua.replay --run-id <录制的 run_id>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from vasta_contracts import ActionContract, audit_six_segment
from vasta_protocols.ids import new_run_id
from vasta_protocols.protocols import (
    Action,
    CompensationResult,
    DryRunResult,
    EnvironmentStatus,
    Observation,
    ToolManifest,
    ToolResult,
)
from vasta_runtime import Budget, RunContext, RunEngine
from vasta_runtime.gateway import ToolGateway
from vasta_storage import SqliteStorage, first_deviation

from .config import CuaConfig
from .verifiers import AxDisplayVerifier


class ReplayEnv:
    """确定性替身环境：按录制序供给 reset/decision 观察帧。"""

    deterministic = True
    protocol_version = "0.1.0"

    def __init__(self, reset_detail: dict) -> None:
        self._reset_detail = reset_detail

    async def reset(self, seed: int | None = None) -> Observation:
        return Observation(kind="reset", detail=dict(self._reset_detail))

    async def observe(self) -> Observation:
        return Observation(kind="decision", detail=dict(self._reset_detail),
                           available_actions=["click_mark"])

    async def execute(self, action: Action) -> list[Observation]:
        raise RuntimeError("回放模式不允许环境直执行（AD-4）")

    async def status(self) -> EnvironmentStatus:
        return EnvironmentStatus(running=True, detail={"replay": True})


class ReplayClickTool:
    """确定性替身工具：按录制序返回原 ToolResult（同字节 ⇒ 同 sha）。"""

    deterministic = True
    protocol_version = "0.1.0"

    def __init__(self, results: list[dict]) -> None:
        self.manifest = ToolManifest(
            name="click_mark", version="1.0",
            risk="R2", read_only=False, idempotent=False,
            compensable=False, supports_dry_run=True, supports_read_back=True,
            side_effects=["（回放）无副作用——返回录制的 ToolResult"],
        )
        self._results = list(results)

    async def dry_run(self, action: Action) -> DryRunResult:
        return DryRunResult(allowed=True)

    async def execute(self, action: Action, idempotency_key=None) -> ToolResult:
        return ToolResult.model_validate(self._results.pop(0))

    async def read_back(self, action: Action, result: ToolResult) -> Observation:
        return Observation(kind="decision",
                           detail={"display": result.detail.get("display_after"),
                                   "mark": result.detail.get("mark")})

    async def compensate(self, execution_detail: dict) -> CompensationResult:
        return CompensationResult(ok=False, detail={"note": "回放无补偿"})


def _normalize(events: list[Any]) -> str:
    """归一化事件流（同 AgentSession.normalized_stream 口径）。"""
    rows = [{"seq": e.seq, "type": e.type, "payload": e.payload} for e in events]
    return json.dumps(rows, ensure_ascii=False, sort_keys=True)


async def replay(run_id: str) -> int:
    cfg = CuaConfig()
    store = SqliteStorage(Path(cfg.store_root) / "store")
    try:
        events = list(store.iter_run_events(run_id))
        if not events:
            print(f"[replay] 录制 run {run_id} 不存在", file=sys.stderr)
            return 2

        # ── 从录制流抽取回放素材 ──
        contracts: list[ActionContract] = []
        results: list[dict] = []
        reset_detail: dict | None = None
        budget_max_actions = 9   # run_task 默认；run.created 快照覆写
        seed = 42
        reset_seen = 0
        for e in events:
            if e.type == "run.created":
                snap = e.payload.get("budget", {})
                if isinstance(snap.get("max_actions"), int):
                    budget_max_actions = snap["max_actions"]
                if isinstance(e.payload.get("seed"), int):
                    seed = e.payload["seed"]
            elif e.type == "observation.reset":
                # 第 1 条是引擎 marker（seed），第 2 条才是 env 帧——
                # detail 只在采集工件里（事件 payload 不带）
                reset_seen += 1
                if reset_seen == 2:
                    refs = e.payload.get("artifact_refs") or []
                    if refs:
                        cap = json.loads(await store.get_artifact(refs[0]))
                        reset_detail = cap.get("detail") or {}
            elif e.type == "action.contracted":
                raw = await store.get_artifact(e.payload["contract_ref"])
                contracts.append(ActionContract.model_validate(
                    json.loads(raw)))
            elif e.type == "action.executed":
                raw = await store.get_artifact(e.payload["result_ref"])
                results.append(json.loads(raw))
        if not contracts or len(contracts) != len(results) or reset_detail is None:
            print(f"[replay] 素材不全：contracts={len(contracts)} "
                  f"results={len(results)} reset={'有' if reset_detail else '无'}",
                  file=sys.stderr)
            return 2
        print(f"[replay] 录制 run：{len(events)} 事件｜{len(contracts)} 契约"
              f"｜budget.max_actions={budget_max_actions}｜seed={seed}")

        # ── 替身组装（replay_mode：AD-5 守卫只放行 deterministic）──
        gateway = ToolGateway()
        gateway.register(ReplayClickTool(results))
        context = RunContext.create(run_id=new_run_id(), seed=seed,
                                    replay_mode=True)
        engine = await RunEngine.create(
            env=ReplayEnv(reset_detail), store=store,
            budget=Budget(max_actions=budget_max_actions),
            run_context=context, capture_observations=True,
            tool_gateway=gateway,
        )
        verifier = AxDisplayVerifier()
        await engine.start()
        await engine.reset()
        for contract in contracts:
            await engine.execute_contracted(
                contract, verifiers={"ax_display": verifier})
        await engine.complete()
        replay_events = list(store.iter_run_events(context.run_id))

        # ── 终判：归一化事件流逐字节对比 ──
        a, b = _normalize(events), _normalize(replay_events)
        print(f"\n[replay] 录制 {len(events)} 条 vs 回放 {len(replay_events)} 条"
              f"｜run 状态 {engine.state.value}")
        if a == b:
            print(f"[replay] **PASS ✓ 归一化事件流逐字节一致**"
                  f"（{len(a)} 字符）——AD-5 桌面版复现成立")
            return 0

        # 首个差异定位（诚实诊断）
        ra, rb = json.loads(a), json.loads(b)
        for i, (x, y) in enumerate(zip(ra, rb)):
            if x != y:
                print(f"[replay] ✗ 首差异 @ seq={x.get('seq')}：")
                print(f"  录制: {json.dumps(x, ensure_ascii=False)[:200]}")
                print(f"  回放: {json.dumps(y, ensure_ascii=False)[:200]}")
                break
        else:
            shorter = "回放" if len(rb) < len(ra) else "录制"
            tail = (rb if shorter == "回放" else ra)[-1]
            print(f"[replay] ✗ 前缀一致但长度不同（{len(ra)} vs {len(rb)}），"
                  f"{shorter}较短，末条: {json.dumps(tail, ensure_ascii=False)[:160]}")
        audit = audit_six_segment(replay_events)
        hit = first_deviation(replay_events)
        print(f"[replay] 回放侧审计 complete={audit.complete}/{audit.total}"
              f"｜首偏差 {hit.type if hit else '无'}")
        return 1
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="录制的 run_id")
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(replay(args.run_id)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
