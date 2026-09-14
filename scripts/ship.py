#!/usr/bin/env python3
"""Story 提交脚本（Story 11.2，Epic 10 复盘 D3，G0）。

一键门禁 + sprint-status 回写 + 提交——声明失实（两连）与回写断链
（两 Epic）的共同根治：工具承载而非记忆。

用法::

    python scripts/ship.py "Story 11.3: 多 Agent 委派契约（G1）——全绿" \\
        --story 11-3-delegation-contract [--paths src/new_file.py ...]

步骤（任一失败即中止，不提交）：
1. pytest 全量（packages+tests 范围）
2. ruff check packages tests
3. lint-imports（import-linter 5 契约）
4. sprint-status 回写（--story 给定时置 done；幂等、原子替换）
5. git add（已跟踪变更 ``-u`` + ``--paths`` 显式新文件——**不做
   ``-A`` 兜底**，Epic 1 复盘 git-hygiene 禁令）+ git commit
   （内联身份 VastaCore <vastacore@localhost>）

提交信息自动附**从当次门禁输出解析**的 pytest 计数尾行——「N 全绿」
不再手写外推（Epic 11 验收审计：11.13 声明 1014 实测 1008）。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS_FILE = ROOT / "docs" / "sprint-status.yaml"


def run(name: str, cmd: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, shell=False)
    output = proc.stdout + proc.stderr
    tail = "\n".join(output.strip().splitlines()[-3:])
    ok = proc.returncode == 0
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if tail:
        print(f"      {tail}")
    return ok, output


def _write_atomic(path: Path, text: str) -> None:
    """原子替换（temp + os.replace——中途崩溃不留撕裂 YAML）。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def update_status(story_key: str | None) -> bool:
    if not story_key:
        return True
    text = STATUS_FILE.read_text(encoding="utf-8")
    # 值允许为空（空值键也是键——评审修复 H-3：\S+ 误报「无键」）
    pattern = re.compile(rf"^(\s+{re.escape(story_key)}):\s*\S*",
                         re.M)
    if not pattern.search(text):
        print(f"[FAIL] sprint-status 无键 {story_key}（先预注册）")
        return False
    # count=1：只改 development_status 区的首个匹配——同键在规划区
    # 再现时不被连带翻转（评审修复 M6.2：epic-11 两处同键全量改写）
    text = pattern.sub(r"\g<1>: done", text, count=1)
    _write_atomic(STATUS_FILE, text)
    print(f"[PASS] sprint-status: {story_key} → done")
    return True


def _pytest_trailer(pytest_output: str, ruff_ok: bool,
                    lint_ok: bool) -> str:
    """从当次 pytest 输出解析计数尾行（声明从输出复制——不手写）。"""
    counts: list[str] = []
    for label, regex in (("passed", r"(\d+) passed"),
                         ("skipped", r"(\d+) skipped"),
                         ("failed", r"(\d+) failed")):
        m = re.search(regex, pytest_output)
        if m:
            counts.append(f"{m.group(1)} {label}")
    summary = ", ".join(counts) if counts else "count unavailable"
    return (f"\n\nGates: pytest {summary}; "
            f"ruff {'clean' if ruff_ok else 'FAILED'}; "
            f"lint-imports {'kept' if lint_ok else 'FAILED'}.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Story 提交一键门禁")
    parser.add_argument("message", help="提交信息（首行）")
    parser.add_argument("--story", default=None,
                        help="sprint-status story 键（置 done）")
    parser.add_argument("--paths", nargs="*", default=[],
                        help="显式新增文件路径（新文件必须显式——"
                             "不做 -A 兜底）")
    args = parser.parse_args()

    steps: list[tuple[str, list[str]]] = [
        ("pytest 全量", [sys.executable, "-m", "pytest", "-q"]),
        ("ruff", [sys.executable, "-m", "ruff", "check",
                  "packages", "tests"]),
        ("lint-imports", ["lint-imports"]),
    ]
    outputs: dict[str, str] = {}
    for name, cmd in steps:
        ok, output = run(name, cmd)
        outputs[name] = output
        if not ok:
            print(f"\n门禁 {name} 红——不提交。修复后重跑。")
            return 1

    if not update_status(args.story):
        return 1

    # 显式路径 add：已跟踪变更（-u 不带 pathspec——它只处理已跟踪
    # 文件，对 untracked pathspec 报错）+ 显式新文件（禁 -A 兜底
    # ——工作区垃圾/评审临时物不入档）
    ok, _ = run("git add tracked", ["git", "add", "-u"])
    if not ok:
        return 1
    if args.paths:
        ok, _ = run("git add new files", ["git", "add", *args.paths])
        if not ok:
            return 1
    message = args.message + _pytest_trailer(
        outputs["pytest 全量"], True, True)
    ok, _ = run("git commit", [
        "git", "-c", "user.name=VastaCore",
        "-c", "user.email=vastacore@localhost",
        "commit", "-m", message])
    if not ok:
        return 1
    print("\n✅ 全门禁绿 + 状态回写 + 已提交。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
