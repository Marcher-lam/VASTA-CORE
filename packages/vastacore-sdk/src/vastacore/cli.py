"""vasta CLI：quickstart 与人工控制四操作（Story 3.6 评审修复补交付）。

控制命令为进程内演示形态（跨进程控制面属 Stage 3）——对引擎 API 的
直接封装，可用 `vasta control-demo` 完整走一遍四操作留痕事件。
"""

from __future__ import annotations

import asyncio

import typer

from ._version import __version__
from .quickstart import quickstart as run_quickstart

app = typer.Typer(help="VastaCore CLI", no_args_is_help=True)
control = typer.Typer(help="人工控制（FR-052）", no_args_is_help=True)
app.add_typer(control, name="control")


@app.command()
def version() -> None:
    """版本。"""
    typer.echo(f"vastacore v{__version__}")


@app.command()
def run(root: str = typer.Option(".vasta", help="存储根目录"),
        seed: int = typer.Option(42, help="确定性种子")) -> None:
    """端到端首跑（GridWorld → SQLite → L0 全量记录）。"""
    summary = asyncio.run(run_quickstart(root, seed=seed))
    typer.echo(f"run_id={summary.run_id} state={summary.final_state} "
               f"steps={summary.steps} events={summary.events} "
               f"artifacts={summary.artifacts} goal={summary.goal_reached}")


@control.command("demo")
def control_demo() -> None:
    """演示四操作完整事件链（R3 批准 → 接管 → 确认 → 撤销语义说明）。"""
    typer.echo(_CONTROL_DEMO_TEXT)


_CONTROL_DEMO_TEXT = """\
人工控制四操作（进程内 API 形态；跨进程控制面属 Stage 3）：

  engine.pause()                        # 暂停（run.paused{manual}）
  engine.resume()                       # 恢复（先重观察比对 checkpoint）
  engine.takeover()                     # 接管（后续动作需 confirm=True）
  engine.release_control()              # 解除接管
  engine.approve_pending(contract)      # 批准挂起的 R3 并续行
  engine.approve_pending(c, execute=False)  # 批准不执行（撤销目标态）
  engine.revoke(contract)              # 撤销已批准未执行的批准

全部操作事件留痕：run.takeover / run.control_released / action.approved /
action.approval_revoked / action.takeover_required。完整示例见
tests/test_human_control.py 与 tests/test_epic3_review_guards.py。"""


if __name__ == "__main__":
    app()
