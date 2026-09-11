#!/usr/bin/env python3
"""Story 提交脚本（Story 11.2，Epic 10 复盘 D3，G0）。

一键门禁 + sprint-status 回写 + 提交——声明失实（两连）与回写断链
（两 Epic）的共同根治：工具承载而非记忆。

用法::

    python scripts/ship.py "Story 11.3: 多 Agent 委派契约（G1）——全绿" \\
        --story 11-3-delegation-contract

步骤（任一失败即中止，不提交）：
1. pytest 全量（packages+tests 范围）
2. ruff check packages tests
3. lint-imports（import-linter 5 契约）
4. sprint-status 回写（--story 给定时置 done；幂等）
5. git add -A + git commit（内联身份 VastaCore <vastacore@localhost>）

打印每步结论——提交信息里的门禁声明从当次输出复制，不再凭记忆。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS_FILE = ROOT / "docs" / "sprint-status.yaml"


def run(name: str, cmd: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, shell=False)
    tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-3:])
    ok = proc.returncode == 0
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if tail:
        print(f"      {tail}")
    return ok, tail


def update_status(story_key: str | None) -> bool:
    if not story_key:
        return True
    text = STATUS_FILE.read_text(encoding="utf-8")
    pattern = re.compile(rf"^(\s+{re.escape(story_key)}):\s*\S+", re.M)
    if not pattern.search(text):
        print(f"[FAIL] sprint-status 无键 {story_key}（先预注册）")
        return False
    text = pattern.sub(rf"\g<1>: done", text)
    STATUS_FILE.write_text(text, encoding="utf-8")
    print(f"[PASS] sprint-status: {story_key} → done")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Story 提交一键门禁")
    parser.add_argument("message", help="提交信息（首行）")
    parser.add_argument("--story", default=None,
                        help="sprint-status story 键（置 done）")
    args = parser.parse_args()

    steps: list[tuple[str, list[str]]] = [
        ("pytest 全量", [sys.executable, "-m", "pytest", "-q"]),
        ("ruff", [sys.executable, "-m", "ruff", "check",
                  "packages", "tests"]),
        ("lint-imports", [sys.executable, "-m", "importlinter",
                          "--config", str(ROOT / "pyproject.toml")]),
    ]
    for name, cmd in steps:
        ok, _ = run(name, cmd)
        if not ok:
            print(f"\n门禁 {name} 红——不提交。修复后重跑。")
            return 1

    if not update_status(args.story):
        return 1

    run("git add", ["git", "add", "-A"])
    ok, _ = run("git commit", [
        "git", "-c", "user.name=VastaCore",
        "-c", "user.email=vastacore@localhost",
        "commit", "-m", args.message])
    if not ok:
        return 1
    print("\n✅ 全门禁绿 + 状态回写 + 已提交。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
