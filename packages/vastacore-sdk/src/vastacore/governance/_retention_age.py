"""工件年龄与分类提取（data_policy 内部辅助——SQLite 元数据面只读）。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def artifact_ages(
    store: Any, *,
    tenant_id: str = "t-default", project_id: str = "p-default",
    now: datetime | None = None,
) -> list[tuple[str, str | None, float]]:
    """本作用域工件的 (sha256, classification, age_days) 清单。

    只读元数据面（artifacts join artifact_refs）；age 按当前时刻与
    created_at 差值（created_at 缺失/不可解析按 0 计——保守不满期）。"""
    from vasta_protocols.ids import now_utc

    if now is None:  # 评审修复 L-3：retention_due 的 as-of 时点透传
        now = now_utc()
    rows: list[tuple[str, str | None, float]] = []
    with store._lock:  # noqa: SLF001 ——同 SDK 域只读直查
        for sha, classification, created_at in store._conn.execute(  # noqa: SLF001
            "SELECT a.sha256, a.classification, a.created_at"
            " FROM artifacts a JOIN artifact_refs r"
            " ON a.sha256 = r.sha256"
            " WHERE r.tenant_id = ? AND r.project_id = ?",
            (tenant_id, project_id),
        ).fetchall():
            try:
                created = datetime.fromisoformat(created_at)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                age = (now - created).total_seconds() / 86400
            except (ValueError, TypeError):
                age = 0.0
            rows.append((sha, classification, max(age, 0.0)))
    return rows
