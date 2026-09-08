"""ID 与时间工具。

约定（架构脊柱 Consistency Conventions）：
- 实体 ID 用 UUIDv7/ULID 字符串（经 uuid6 库；Python 3.14+ 可换 stdlib）；
- 时间 ISO8601 UTC。
"""

from __future__ import annotations

from datetime import UTC, datetime

from uuid6 import uuid7


def now_utc() -> datetime:
    """当前 UTC 时间（带 tzinfo）。AD-5：决策路径禁止直接读系统时钟，
    该函数仅供 RunContext 装配与测试使用。"""
    return datetime.now(UTC)


def new_event_id() -> str:
    return str(uuid7())


def new_run_id() -> str:
    return str(uuid7())
