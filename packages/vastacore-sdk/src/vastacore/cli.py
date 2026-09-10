"""vasta CLI：quickstart、回放检查与人工控制四操作。

控制命令为进程内演示形态（跨进程控制面属 Stage 3）——对引擎 API 的
直接封装，可用 `vasta control-demo` 完整走一遍四操作留痕事件。

评审修复（Epic 4-7 code-review）：
- inspect/replay 命令原定义在 ``if __name__ == "__main__"`` 之后——
  模块直跑（``python -m vastacore.cli``）时不可达（实测 No such
  command），移到入口调用之前；
- 存储句柄统一 finally 关闭；
- run_id 过路径分隔符校验（防 ``../`` 逃逸写 HTML）。
"""

from __future__ import annotations

import asyncio

import typer

from ._version import __version__
from .quickstart import quickstart as run_quickstart

app = typer.Typer(help="VastaCore CLI", no_args_is_help=True)
control = typer.Typer(help="人工控制（FR-052）", no_args_is_help=True)
app.add_typer(control, name="control")


def _validate_run_id(run_id: str) -> str:
    """run_id 只允许安全字符（评审修复：防路径逃逸写入 HTML 路径）。"""
    if not run_id or any(ch in run_id for ch in "/\\:"):
        typer.echo(f"非法 run_id {run_id!r}（不允许路径分隔符）", err=True)
        raise typer.Exit(code=2)
    return run_id


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


@app.command()
def serve(root: str = typer.Option(".vasta", help="存储根目录"),
          token: str = typer.Option(..., help="Bearer 令牌（必填，无匿名面）"),
          host: str = typer.Option("127.0.0.1", help="监听地址"),
          port: int = typer.Option(8700, help="监听端口")) -> None:
    """HTTP 接入服务（Story 8.3）：run 生命周期 + 证据查询，令牌鉴权。"""
    from .ops.service import serve as run_serve

    typer.echo(f"VastaCore service → http://{host}:{port}（root={root}）")
    run_serve(root=root, token=token, host=host, port=port)


tool = typer.Typer(help="工具开发（init 脚手架）")
app.add_typer(tool, name="tool")


@tool.command("init")
def tool_init(name: str = typer.Argument(..., help="工具名（snake_case 标识符）"),
              directory: str = typer.Option(None, "--dir",
                                            help="目标目录（默认 ./<name>）")) -> None:
    """生成工具项目三件套（Story 8.4）：骨架 + 契约模板 + 协议测试。"""
    from .scaffold import generate_tool_project

    target = directory or name
    result = generate_tool_project(name, target)
    typer.echo(f"已生成 {result.tool_name} 工具项目 → {result.root}")
    typer.echo(f"  {result.tool_path.name}          # ToolAdapter 骨架（从绿改起）")
    typer.echo(f"  {result.template_path.name}  # 契约模板（填业务语义）")
    typer.echo(f"  {result.test_path.name}      # 协议测试（pytest test_protocol.py -q）")
    typer.echo("全绿后即可注册网关上架（FR-081/FR-032）。")


@app.command()
def inspect(root: str = typer.Option(".vasta", help="存储根目录"),
            run_id: str = typer.Argument(..., help="Run ID")) -> None:
    """回放检查：时间线 + 首偏差定位（UJ-1）。"""
    from vasta_storage import SqliteStorage, first_deviation, render_text, timeline

    _validate_run_id(run_id)
    store = SqliteStorage(f"{root}/store")
    try:
        events = list(store.iter_run_events(run_id))
        if not events:
            typer.echo(f"未找到 Run {run_id!r}", err=True)
            raise typer.Exit(code=1)
        typer.echo(render_text(timeline(events)))
        hit = first_deviation(events)
        if hit:
            typer.echo(f"\n首个偏差: seq={hit.seq} {hit.type} [{hit.category}]")
            typer.echo(f"  契约: {hit.contract_ref or '无'}")
            typer.echo(f"  计划: {hit.plan_ref or '无'}")
            typer.echo(f"  前后观察: before={hit.before_seq} after={hit.after_seq}")
        else:
            typer.echo("\n无偏差信号")
    finally:
        store.close()


@app.command()
def replay(root: str = typer.Option(".vasta", help="存储根目录"),
           run_id: str = typer.Argument(..., help="Run ID"),
           out: str = typer.Option(
               None, help="输出 HTML 路径（默认 {root}/{run_id}.html)")
) -> None:
    """生成自包含 HTML Replay（单文件无外部依赖）。"""
    from vasta_storage import SqliteStorage, first_deviation, render_html, timeline

    run_id = _validate_run_id(run_id)
    store = SqliteStorage(f"{root}/store")
    try:
        events = list(store.iter_run_events(run_id))
        if not events:
            typer.echo(f"未找到 Run {run_id!r}", err=True)
            raise typer.Exit(code=1)
        tl = timeline(events)
        hit = first_deviation(events)
        html = render_html(tl, hit, version=__version__)
    finally:
        store.close()
    path = out or f"{root}/{run_id}.html"
    with open(path, "wb") as f:
        f.write(html)
    typer.echo(f"HTML Replay 已生成: {path} ({len(html)} bytes)")


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
