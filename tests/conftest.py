"""测试套件全局配置。

item-33（Epic 12 复盘）：flake 遥测钩子——失败用例的结构化记录
（名称/阶段/耗时/机器上下文）落 ``.flake/telemetry.jsonl``，用于
定位「两 Epic 连续的不可复现偶发失败」（疑似 Desktop/OneDrive/
Defender 对源文件读取的瞬时干扰）。零失败零文件；对测试行为零侵入。
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time

# 同目录测试夹具模块可导入（如 tests/_sidecar_usermod.py——Story 8.15
# 子进程形态以 ``--module tests._sidecar_usermod:build`` 复用它）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def pytest_runtest_logreport(report) -> None:  # noqa: ANN001
    if report.when == "call" and report.failed:
        _record(report)
    elif report.when == "setup" and report.outcome == "error":
        _record(report, phase="setup-error")


def _record(report, phase: str = "call") -> None:
    try:
        path = os.path.join(".flake")
        os.makedirs(path, exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "nodeid": report.nodeid,
            "phase": phase,
            "duration_ms": round(getattr(report, "duration", 0.0) * 1000),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "longrepr": str(report.longrepr)[:2000],
        }
        with open(os.path.join(path, "telemetry.jsonl"), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 遥测自身永不阻断测试
