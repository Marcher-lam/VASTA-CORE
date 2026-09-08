"""AD-5 静态禁令：核心决策路径不得直接调用系统时钟/随机/环境读取。

白名单（唯一许可）：
- vasta_protocols/ids.py —— 时间/ID 供给点；
- vasta_storage/sqlite_store.py —— 存储簿记时间戳（Story 1.4 已文档化的
  非重放路径例外）。
模式为启发式（常见直接调用形态）；绕过形态（如 from-import 别名）不在此
保证范围，由评审与 lint 补充。
"""

from __future__ import annotations

import re
from pathlib import Path

import vasta_cognition
import vasta_contracts
import vasta_eval
import vasta_model_lab
import vasta_policy
import vasta_protocols
import vasta_runtime
import vasta_storage

FORBIDDEN = [
    r"datetime\.now\s*\(",
    r"datetime\.utcnow\s*\(",
    r"date\.today\s*\(",
    r"\btime\.time\s*\(",
    r"\btime\.monotonic\s*\(",
    r"\btime\.perf_counter\s*\(",
    r"\btime\.sleep\s*\(",
    r"\brandom\.random\s*\(",
    r"\brandom\.randint\s*\(",
    r"\brandom\.choice\s*\(",
    r"\brandom\.shuffle\s*\(",
    r"\brandom\.uniform\s*\(",
    r"\brandom\.sample\s*\(",
    r"\brandom\.randrange\s*\(",
    r"\brandom\.getrandbits\s*\(",
    r"os\.environ",
    r"os\.getenv\s*\(",
    r"\bsecrets\.\w+\s*\(",
    r"uuid\.uuid4\s*\(",
]

ALLOWLIST = {
    "packages/vasta-protocols/src/vasta_protocols/ids.py",
    "packages/vasta-storage/src/vasta_storage/sqlite_store.py",
}

PACKAGES = [
    vasta_protocols,
    vasta_runtime,
    vasta_cognition,
    vasta_contracts,
    vasta_policy,
    vasta_model_lab,
    vasta_storage,
    vasta_eval,
]


def test_no_direct_nondeterminism_in_core_paths() -> None:
    violations: list[str] = []
    for package in PACKAGES:
        root = Path(package.__file__).parent
        for py in sorted(root.rglob("*.py")):
            rel = py.relative_to(Path(__file__).resolve().parent.parent)
            rel_posix = str(rel).replace("\\", "/")
            if rel_posix in ALLOWLIST:
                continue
            text = py.read_text(encoding="utf-8")
            for pattern in FORBIDDEN:
                if re.search(pattern, text):
                    violations.append(f"{rel_posix}: /{pattern}/")
    assert not violations, (
        "AD-5 violations — inject via RunContext / protocols.ids instead:\n"
        + "\n".join(violations)
    )


def test_allowlist_files_still_exist() -> None:
    """白名单失效（文件改名/移动）时提醒更新，而不是静默放过。"""
    import vasta_storage

    root = Path(vasta_storage.__file__).parent
    assert (root / "sqlite_store.py").exists()
    assert (Path(vasta_protocols.__file__).parent / "ids.py").exists()
