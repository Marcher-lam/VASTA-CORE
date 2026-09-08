"""证据多维检索（FR-013，Story 2.1）。

- 事件检索：作用域强制 + run/类型（精确或族前缀）/时间窗/载荷等值维度；
- Artifact 检索：经 artifact_refs JOIN（AD-14 可达性）+ source/classification/
  标签/入库时间窗；
- 无死链：事件结果返回前校验 artifact_refs 在作用域内可达且 blob 存在，
  违反抛 search.dead_links（证据完整性问题要响亮，不静默过滤）。
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any

from vasta_protocols.envelope import EventEnvelope
from vasta_protocols.errors import VastaError

from ._scope import validate_scope_pair as _validate_scope_pair

_KEY_RE = re.compile(r"^[A-Za-z0-9_]+$")

#: json_extract 路径键白名单：仅字母数字下划线，防路径注入。
_KEY_OK = "键仅允许字母/数字/下划线（json_extract 路径安全）"


def _safe_key(key: str) -> str:
    if not _KEY_RE.fullmatch(key):
        raise VastaError(code="search.bad_key", message=f"{key!r}: {_KEY_OK}")
    return key


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class EvidenceSearchMixin:
    """挂载于 SqliteStorage；复用其 _conn/_lock/objects_dir。"""

    async def search_events(
        self,
        tenant_id: str,
        project_id: str,
        *,
        run_id: str | None = None,
        event_type: str | None = None,
        ts_from: datetime | None = None,
        ts_to: datetime | None = None,
        payload_equals: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[EventEnvelope]:
        """多维事件检索；作用域成对必填（AD-7），事件仅返回本作用域行。

        event_type 支持族前缀（如 "observation." 匹配该族全部）。
        payload_equals 以 json_extract 对 payload 顶层键做等值匹配。
        """
        _validate_scope_pair(tenant_id, project_id)
        return await asyncio.to_thread(
            self._search_events_sync,
            tenant_id,
            project_id,
            run_id,
            event_type,
            _iso(ts_from),
            _iso(ts_to),
            payload_equals,
            limit,
        )

    def _search_events_sync(
        self,
        tenant_id: str,
        project_id: str,
        run_id: str | None,
        event_type: str | None,
        ts_from: str | None,
        ts_to: str | None,
        payload_equals: dict[str, Any] | None,
        limit: int | None,
    ) -> list[EventEnvelope]:
        query = "SELECT data FROM events WHERE tenant_id=? AND project_id=?"
        params: list[Any] = [tenant_id, project_id]
        if run_id is not None:
            query += " AND run_id=?"
            params.append(run_id)
        if event_type is not None:
            if event_type.endswith("."):
                query += " AND (type=? OR type LIKE ?)"
                params += [event_type[:-1], event_type + "%"]
            else:
                query += " AND type=?"
                params.append(event_type)
        if ts_from is not None:
            query += " AND ts>=?"
            params.append(ts_from)
        if ts_to is not None:
            query += " AND ts<=?"
            params.append(ts_to)
        if payload_equals:
            for key, value in payload_equals.items():
                safe = _safe_key(key)
                query += f" AND json_extract(data, '$.payload.\"{safe}\"')=?"
                params.append(int(value) if isinstance(value, bool) else value)
        query += " ORDER BY ts, run_id, seq"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        events = [EventEnvelope.model_validate_json(row[0]) for row in rows]
        self._assert_no_dead_links(events, tenant_id, project_id)
        return events

    async def search_artifacts(
        self,
        tenant_id: str,
        project_id: str,
        *,
        source: str | None = None,
        classification: str | None = None,
        tags: dict[str, str] | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        """Artifact 检索：经租户引用映射 JOIN，无引用即不可见（AD-14）。"""
        _validate_scope_pair(tenant_id, project_id)
        return await asyncio.to_thread(
            self._search_artifacts_sync,
            tenant_id,
            project_id,
            source,
            classification,
            tags,
            _iso(created_from),
            _iso(created_to),
            limit,
        )

    def _search_artifacts_sync(
        self,
        tenant_id: str,
        project_id: str,
        source: str | None,
        classification: str | None,
        tags: dict[str, str] | None,
        created_from: str | None,
        created_to: str | None,
        limit: int | None,
    ) -> list[dict[str, object]]:
        query = (
            "SELECT a.sha256, a.mime, a.size, a.source, a.classification,"
            " a.retention, a.created_at, a.tags_json, r.referenced_at"
            " FROM artifact_refs r JOIN artifacts a ON a.sha256=r.sha256"
            " WHERE r.tenant_id=? AND r.project_id=?"
        )
        params: list[Any] = [tenant_id, project_id]
        if source is not None:
            query += " AND a.source=?"
            params.append(source)
        if classification is not None:
            query += " AND a.classification=?"
            params.append(classification)
        if created_from is not None:
            query += " AND a.created_at>=?"
            params.append(created_from)
        if created_to is not None:
            query += " AND a.created_at<=?"
            params.append(created_to)
        if tags:
            for key, value in tags.items():
                safe = _safe_key(key)
                query += f" AND json_extract(a.tags_json, '$.\"{safe}\"')=?"
                params.append(value)
        query += " ORDER BY a.created_at, a.sha256"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        keys = (
            "sha256",
            "mime",
            "size",
            "source",
            "classification",
            "retention",
            "created_at",
            "tags_json",
            "referenced_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    # ---- 无死链校验 ----
    def _assert_no_dead_links(
        self, events: list[EventEnvelope], tenant_id: str, project_id: str
    ) -> None:
        refs: set[str] = set()
        for event in events:
            payload_refs = event.payload.get("artifact_refs")
            if isinstance(payload_refs, list):
                refs.update(str(sha) for sha in payload_refs)
        if not refs:
            return
        placeholders = ",".join("?" for _ in refs)
        with self._lock:
            rows = self._conn.execute(
                "SELECT sha256 FROM artifact_refs WHERE tenant_id=? AND project_id=?"
                f" AND sha256 IN ({placeholders})",
                [tenant_id, project_id, *refs],
            ).fetchall()
        reachable = {row[0] for row in rows}
        dead = sorted(
            sha
            for sha in refs
            if sha not in reachable
            or not (self.objects_dir / sha[:2] / sha).exists()
        )
        if dead:
            raise VastaError(
                code="search.dead_links",
                message=(
                    "event results reference unreachable/missing artifacts: "
                    f"{dead[:5]}{'...' if len(dead) > 5 else ''}"
                ),
            )
