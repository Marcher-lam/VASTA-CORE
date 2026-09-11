"""从零接入 VastaCore：外部团队视角的完整演练（Story 8.1，SM-5 证据）。

一个已有自己的 Agent 循环的团队，只带两样东西来：
1. 一个 EnvironmentAdapter（他们的环境）；
2. 一个 ToolAdapter（他们的写工具）+ 一份契约模板。

跑完即得：六段链自动执行、证据落盘、因果时间线回放、同 seed 复现。

运行：uv run python examples/onboarding/from_zero.py
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from vasta_protocols.protocols import (
    Action,
    DryRunResult,
    EnvironmentAdapter,
    Observation,
    ToolAdapter,
    ToolManifest,
    ToolResult,
)
from vasta_storage import first_deviation, render_text, timeline
from vastacore import AgentSession
from vastacore import ContractTemplate

# ── 1) 你已有的环境：实现五协议 EnvironmentAdapter ───────────────────────

class OrderBoardEnv(EnvironmentAdapter):
    """订单看板：一个订单，标记发货。"""

    protocol_version = "0.1.0"

    def __init__(self) -> None:
        self.orders = {"A102": "pending"}

    async def reset(self, seed=None):
        self.orders["A102"] = "pending"
        return Observation(kind="decision", detail=dict(self.orders),
                           available_actions=["ship_order"])

    async def observe(self):
        return Observation(kind="decision", detail=dict(self.orders))

    async def execute(self, action):
        if action.tool == "ship_order":
            self.orders[action.args["order_id"]] = "shipped"
        return [
            Observation(kind="transition", detail=dict(self.orders)),
            Observation(kind="decision", detail=dict(self.orders)),
        ]

    async def status(self):
        class S:
            running = True
        return S()


# ── 2) 你的写工具：实现 ToolAdapter（清单强制分类，缺声明构造期即拒）──────

class ShipOrderTool(ToolAdapter):
    protocol_version = "0.1.0"
    manifest = ToolManifest(
        name="ship_order", version="1.0",
        risk="R2",            # 真实世界写操作
        read_only=False,
        idempotent=True,      # 同单重复发货幂等
        supports_read_back=True,
    )

    async def execute(self, action, idempotency_key=None):
        # 你的业务逻辑……副作用在这里真实发生
        return ToolResult(ok=True, detail={
            "order_id": action.args["order_id"],
            "status": "shipped",
        })

    async def dry_run(self, action):
        return DryRunResult(allowed=True)

    async def read_back(self, action, result):
        return Observation(kind="decision", detail={"status": result.detail["status"]})

    async def compensate(self, action, result):
        return ToolResult(ok=True, detail={"compensated": True})


# ── 3) 契约模板：这个工具「什么算做对了」（六段链的核验依据）─────────────

SHIP_CONTRACT: ContractTemplate = {
    "goal": "发货已核验订单",
    "preconditions": ["订单存在且已付款"],
    "prediction": {
        "changes": ["A102.status=shipped"],
        "invariants": ["其他订单不变"],
    },
    "success_criteria": ["read-back status=shipped"],
    "failure_criteria": ["重复发货", "状态未变"],
    "verify_with": ["read_back"],
    "timeout_ms": 5000,
    # risk 留空 → 自动取清单分级（AD-4：清单强制，自声明无效）
}


async def main() -> None:
    root = Path(".vasta-onboarding")
    shutil.rmtree(root, ignore_errors=True)

    # 4) 三行接入：环境 + 工具 + 契约模板
    session = await AgentSession.create(
        env=OrderBoardEnv(),
        tools=[ShipOrderTool()],
        contracts={"ship_order": SHIP_CONTRACT},
        root=root,
        seed=42,
    )
    async with session:
        await session.start()
        await session.reset()
        # 5) 你的 Agent 循环：act() 即六段链（核验/恢复/审计全自动）
        observations = await session.act(
            Action(tool="ship_order", args={"order_id": "A102"})
        )
        print(f"动作完成，收到 {len(observations)} 条观察；"
              f"核验结果见事件流")
        await session.complete()
        summary = await session.summary()
        print(f"run={summary.run_id} state={summary.state} "
              f"events={summary.events} artifacts={summary.artifacts}")

        # 6) 回放：因果时间线 + 首偏差定位（UJ-1，句柄关闭前读）
        events = session.events()
        print()
        print(render_text(timeline(events))[:600])
        hit = first_deviation(events)
        print(f"\n首偏差: {hit.type if hit else '无（干净跑）'}")

    print(f"\n证据根目录: {root}/store —— `vasta inspect {summary.run_id} "
          f"--root {root}` 查看完整时间线")


if __name__ == "__main__":
    asyncio.run(main())
