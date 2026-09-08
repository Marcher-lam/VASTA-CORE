"""存储簿记时间戳（非重放决策路径，AD-5 文档化例外）。"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()
