"""VastaCore quickstart 示例（Story 1.7）。

运行：uv run python examples/quickstart.py
版本：vastacore-sdk 0.1.0（与 docs/quickstart.md 同步，由测试守卫）
"""

from __future__ import annotations

import asyncio

import vastacore


async def main() -> None:
    summary = await vastacore.quickstart(".vasta", seed=42, run_id="run-quickstart")
    print(f"VastaCore quickstart (vastacore v{vastacore.__version__})")
    print(f"  run_id       : {summary.run_id}")
    print(f"  final_state  : {summary.final_state}")
    print(f"  steps        : {summary.steps}")
    print(f"  events       : {summary.events}")
    print(f"  artifacts    : {summary.artifacts}")
    print(f"  goal_reached : {summary.goal_reached}")
    print(f"  store        : {summary.store_root}")


if __name__ == "__main__":
    asyncio.run(main())
