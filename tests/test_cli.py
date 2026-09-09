"""vasta CLI 守卫（Epic 4-7 code-review 修复）。

评审实锤：inspect/replay 命令原定义在 ``if __name__ == "__main__"``
之后——``python -m vastacore.cli`` 直跑时 Typer 报 No such command。
"""

from __future__ import annotations

import subprocess
import sys

from typer.testing import CliRunner

from vastacore.cli import app

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "vastacore v" in result.output


def test_all_commands_registered() -> None:
    """四命令全部注册（含原先定义在 __main__ 之后的 inspect/replay）。"""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("run", "inspect", "replay", "version"):
        assert name in result.output


def test_module_run_reaches_inspect_and_replay() -> None:
    """模块直跑形态：--help 能列出 inspect/replay（原实测 No such command）。"""
    result = subprocess.run(
        [sys.executable, "-m", "vastacore.cli", "--help"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    assert "inspect" in result.stdout and "replay" in result.stdout


def test_inspect_rejects_path_traversal_run_id(tmp_path) -> None:
    """评审修复：run_id 含路径分隔符拒绝（防 HTML 写出逃逸）。"""
    result = runner.invoke(app, ["inspect", "../evil", "--root", str(tmp_path)])
    assert result.exit_code == 2
    result = runner.invoke(
        app, ["replay", "..\\evil", "--root", str(tmp_path)]
    )
    assert result.exit_code == 2


def test_inspect_unknown_run_exits_nonzero(tmp_path) -> None:
    result = runner.invoke(
        app, ["inspect", "run-none", "--root", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "未找到" in result.output


def test_end_to_end_run_then_inspect_replay(tmp_path) -> None:
    """quickstart → inspect → replay 全链（存储句柄 finally 关闭后可用）。"""
    run_result = runner.invoke(app, ["run", "--root", str(tmp_path), "--seed", "7"])
    assert run_result.exit_code == 0
    assert "run_id=" in run_result.output
    run_id = run_result.output.split("run_id=")[1].split()[0]

    inspect_result = runner.invoke(
        app, ["inspect", run_id, "--root", str(tmp_path)]
    )
    assert inspect_result.exit_code == 0
    assert "timeline run=" in inspect_result.output

    replay_result = runner.invoke(
        app, ["replay", run_id, "--root", str(tmp_path)]
    )
    assert replay_result.exit_code == 0
    assert (tmp_path / f"{run_id}.html").exists()


def test_serve_command_registered_and_requires_token() -> None:
    """Story 8.3：serve 命令注册且 token 必填（无匿名面）。"""
    result = runner.invoke(app, ["--help"])
    assert "serve" in result.output
    # 缺 --token → typer 必填参数错误（exit code 2）
    missing = runner.invoke(app, ["serve"])
    assert missing.exit_code == 2


def test_tool_init_command_generates_green_project(tmp_path) -> None:
    """Story 8.4：vasta tool init → 三件套生成且骨架开箱即绿。"""
    import asyncio

    target = tmp_path / "my_tool"
    result = runner.invoke(app, ["tool", "init", "my_tool", "--dir", str(target)])
    assert result.exit_code == 0, result.output
    assert (target / "tool.py").exists()
    assert (target / "contract_template.py").exists()
    assert (target / "test_protocol.py").exists()
    # 骨架协议全绿（开箱即用）
    import importlib.util
    import sys

    from vastacore.scaffold import run_tool_protocol_checks
    spec = importlib.util.spec_from_file_location("cli_scaffold_my_tool", target / "tool.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    failures = asyncio.run(run_tool_protocol_checks(mod.make_tool()))
    assert failures == [], failures
    # 重复生成拒绝覆盖
    dup = runner.invoke(app, ["tool", "init", "my_tool", "--dir", str(target)])
    assert dup.exit_code != 0
