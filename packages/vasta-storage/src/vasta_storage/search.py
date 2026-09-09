"""证据多维检索（FR-013，Story 2.1；Epic 2 评审修复版）。

- 事件检索：作用域强制 + run/类型（精确或族前缀）/时间窗/载荷等值维度；
- Artifact 检索：经 artifact_refs JOIN（AD-14 可达性）+ source/classification/
  标签/入库时间窗；
- 无死链：两类检索返回前校验 artifact_refs 可达且 blob 存在，死链抛
  `search.dead_links`；`verify_hashes=True` 时进一步重算内容哈希
  （AC"哈希校验通过"的显式开关——全量重算每次检索都做不可接受）。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from vasta_protocols.envelope import EventEnvelope
from vasta_protocols.errors import VastaError

from ._scope import validate_scope_pair

_KEY_RE = re.compile(r"^[A-Za-z0-9_]+$")
#: SQLite 主机参数上限远高于此，900 为安全分块粒度。
_CHUNK = 900


def _safe_key(key: str) -> str:
    """json_extract 路径键白名单：仅字母数字下划线，防路径注入。"""
    if not _KEY_RE.fullmatch(key):
        raise VastaError(
            code="search.bad_key",
            message=f"{key!r}: tag/payload 键仅允许字母/数字/下划线",
        )
    return key


def _iso(value: datetime | None, *, field: str) -> str | None:
    """时间窗参数规范化：必须 tz-aware，统一转 UTC 再序列化。"""
    if value is None:
        return None
    if value.tzinfo is None:
        raise VastaError(
            code="search.bad_ts", message=f"{field} 需要 tz-aware datetime（ISO8601 UTC）"
        )
    return value.astimezone(UTC).isoformat()


def _check_limit(limit: int | None) -> None:
    if limit is not None and limit <= 0:
        raise VastaError(code="search.bad_limit", message="limit 必须为正整数")


def _check_payload_values(payload_equals: dict[str, Any]) -> None:
    for key, value in payload_equals.items():
        _safe_key(key)
        if value is None or isinstance(value, (dict, list)):
            raise VastaError(
                code="search.bad_value",
                message=f"{key!r}: payload_equals 仅支持 JSON 标量（str/int/float/bool）",
            )


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
        verify_hashes: bool = False,
    ) -> list[EventEnvelope]:
        """多维事件检索；作用域成对必填（AD-14），事件仅返回本作用域行。

        event_type 支持族前缀（如 "observation." 匹配该族全部；前缀含
        SQL 通配符 %/_ 将被拒绝）。payload_equals 以 json_extract 对
        payload 顶层键做等值匹配（仅 JSON 标量）。verify_hashes=True 时
        对引用证据重算 sha256（默认只做存在性+可达性死链校验）。
        """
        validate_scope_pair(tenant_id, project_id)
        _check_limit(limit)
        if event_type is not None and event_type.endswith("."):
            body = event_type[:-1]
            if "%" in body or "_" in body:
                raise VastaError(
                    code="search.bad_type",
                    message="族前缀不允许 SQL 通配符 % 或 _",
                )
        if payload_equals:
            _check_payload_values(payload_equals)
        return await asyncio.to_thread(
            self._search_events_sync,
            tenant_id,
            project_id,
            run_id,
            event_type,
            _iso(ts_from, field="ts_from"),
            _iso(ts_to, field="ts_to"),
            payload_equals,
            limit,
            verify_hashes,
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
        verify_hashes: bool,
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
        self._assert_no_dead_links(events, tenant_id, project_id, verify_hashes)
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
        verify_hashes: bool = False,
    ) -> list[dict[str, object]]:
        """Artifact 检索：经租户引用映射 JOIN，无引用即不可见（AD-14）。

        返回前做与事件检索同款的死链校验（默认存在性+可达；
        verify_hashes=True 追加重算哈希）。
        """
        validate_scope_pair(tenant_id, project_id)
        _check_limit(limit)
        if tags:
            for key in tags:
                _safe_key(key)
        return await asyncio.to_thread(
            self._search_artifacts_sync,
            tenant_id,
            project_id,
            source,
            classification,
            tags,
            _iso(created_from, field="created_from"),
            _iso(created_to, field="created_to"),
            limit,
            verify_hashes,
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
        verify_hashes: bool,
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
        results = [dict(zip(keys, row, strict=True)) for row in rows]
        # FR-013：Artifact 检索同样无死链（评审修复）
        dead: list[str] = []
        for row in results:
            sha = str(row["sha256"])
            if not self._blob_ok(sha, tenant_id, project_id, verify_hashes):
                dead.append(sha)
        if dead:
            raise VastaError(
                code="search.dead_links",
                message=(
                    "artifact results reference unreachable/missing/corrupted blobs: "
                    f"{dead[:5]}{'...' if len(dead) > 5 else ''}"
                ),
            )
        return results

    # ---- 无死链校验 ----
    def _blob_ok(
        self, sha: str, tenant_id: str, project_id: str, verify_hash: bool
    ) -> bool:
        blob = self.objects_dir / sha[:2] / sha
        if not blob.exists():
            return False
        return not (
            verify_hash
            and hashlib.sha256(blob.read_bytes()).hexdigest() != sha
        )

    def _assert_no_dead_links(
        self,
        events: list[EventEnvelope],
        tenant_id: str,
        project_id: str,
        verify_hashes: bool = False,
    ) -> None:
        refs: set[str] = set()
        for event in events:
            payload_refs = event.payload.get("artifact_refs")
            if isinstance(payload_refs, list):
                refs.update(str(sha) for sha in payload_refs)
        if not refs:
            return
        reachable: set[str] = set()
        ordered = sorted(refs)
        with self._lock:
            for start in range(0, len(ordered), _CHUNK):  # SQLite 参数上限分块
                chunk = ordered[start : start + _CHUNK]
                placeholders = ",".join("?" for _ in chunk)
                rows = self._conn.execute(
                    "SELECT sha256 FROM artifact_refs WHERE tenant_id=? AND project_id=?"
                    f" AND sha256 IN ({placeholders})",
                    [tenant_id, project_id, *chunk],
                ).fetchall()
                reachable.update(row[0] for row in rows)
        dead = sorted(
            sha
            for sha in refs
            if sha not in reachable or not self._blob_ok(
                sha, tenant_id, project_id, verify_hashes
            )
        )
        if dead:
            raise VastaError(
                code="search.dead_links",
                message=(
                    "event results reference unreachable/missing/corrupted artifacts: "
                    f"{dead[:5]}{'...' if len(dead) > 5 else ''}"
                ),
            )
