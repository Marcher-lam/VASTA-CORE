"""SqliteStorage：事件库 + 内容寻址证据库（FR-010/011，AD-2/3/7/14，Story 1.4）。

- 事件：events 表 PRIMARY KEY (run_id, seq)，冲突抛 DuplicateEventError（AD-2）。
- 证据：sha256 分桶 CAS（objects/<sha[:2]>/<sha>，临时文件 + 原子替换，
  写后重读校验——AD-3"先落盘后引用"）；字节全局单份，元数据经事务写入。
- 作用域（AD-7）与可达性（AD-14）：artifacts 表全局去重，artifact_refs
  租户引用映射分离——带租户取回要求引用存在，字节共享不构成跨租户可达。
- AD-10：sqlite3 同步驱动经 asyncio.to_thread 隔离（adapter 边缘），
  单连接 + 线程锁。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from vasta_protocols.envelope import EventEnvelope
from vasta_protocols.errors import DuplicateEventError, VastaError
from vasta_protocols.protocols import STORAGE_PROTOCOL_VERSION

from ._scope import validate_scope_pair as _validate_scope_pair
from .search import EvidenceSearchMixin

DEFAULT_TENANT = "t-default"
DEFAULT_PROJECT = "p-default"

_SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    parent_event_id TEXT,
    ts TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS artifacts (
    sha256 TEXT PRIMARY KEY,
    mime TEXT,
    size INTEGER NOT NULL,
    source TEXT,
    classification TEXT,
    retention TEXT,
    created_at TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS artifact_refs (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    referenced_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, project_id, sha256)
);
"""


class ArtifactNotFoundError(VastaError):
    def __init__(self, sha256: str, reason: str = "not found") -> None:
        super().__init__(
            code="artifact.not_found",
            message=f"artifact {sha256} {reason}",
        )
        self.sha256 = sha256


class ArtifactCorruptedError(VastaError):
    def __init__(self, sha256: str) -> None:
        super().__init__(
            code="artifact.corrupted",
            message=f"artifact {sha256} content hash mismatch on read-back",
        )
        self.sha256 = sha256


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class SqliteStorage(EvidenceSearchMixin):
    """Evidence Store 本地档实现（StorageAdapter 端口 + 元数据/作用域扩展）。"""

    protocol_version = STORAGE_PROTOCOL_VERSION

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.objects_dir = self.root / "objects"
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.root / "store.db", check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        with self._lock, self._conn:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if version > _SCHEMA_VERSION:  # AD-9：过新 schema 拒读，不得静默误读
                raise VastaError(
                    code="store.schema_too_new",
                    message=(
                        f"store schema user_version={version} > {_SCHEMA_VERSION};"
                        " migrate first"
                    ),
                )
            self._conn.executescript(_SCHEMA)
            # v1→v2 迁移（AD-9 首次演练）：旧库补 tags_json 列。
            columns = {
                row[1] for row in self._conn.execute("PRAGMA table_info(artifacts)")
            }
            if "tags_json" not in columns:
                self._conn.execute(
                    "ALTER TABLE artifacts ADD COLUMN tags_json"
                    " TEXT NOT NULL DEFAULT '{}'"
                )
            self._conn.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- 事件（StorageAdapter 端口）----
    async def append_event(self, envelope: EventEnvelope) -> EventEnvelope:
        return await asyncio.to_thread(self._append_event_sync, envelope)

    def _append_event_sync(self, envelope: EventEnvelope) -> EventEnvelope:
        with self._lock, self._conn:
            try:
                self._conn.execute(
                    "INSERT INTO events (run_id, seq, type, parent_event_id, ts,"
                    " tenant_id, project_id, event_id, schema_version, data)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        envelope.run_id,
                        envelope.seq,
                        envelope.type,
                        envelope.parent_event_id,
                        envelope.ts.isoformat(),
                        envelope.tenant_id,
                        envelope.project_id,
                        envelope.event_id,
                        envelope.schema_version,
                        envelope.model_dump_json(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if "event_id" in str(exc):
                    raise VastaError(
                        code="event.duplicate_id",
                        message=f"event_id {envelope.event_id} already stored",
                    ) from exc
                raise DuplicateEventError(envelope.run_id, envelope.seq) from exc
        return envelope

    async def get_event(
        self, run_id: str, seq: int, *, tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> EventEnvelope:
        return await asyncio.to_thread(
            self._get_event_sync, run_id, seq, tenant_id, project_id
        )

    def _get_event_sync(
        self, run_id: str, seq: int, tenant_id: str | None, project_id: str | None
    ) -> EventEnvelope:
        _validate_scope_pair(tenant_id, project_id)
        query = "SELECT data FROM events WHERE run_id=? AND seq=?"
        params: list[object] = [run_id, seq]
        if tenant_id is not None:
            query += " AND tenant_id=? AND project_id=?"
            params += [tenant_id, project_id]
        with self._lock:
            row = self._conn.execute(query, params).fetchone()
        if row is None:
            raise VastaError(
                code="event.not_found", message=f"run {run_id} has no event at seq {seq}"
            )
        return EventEnvelope.model_validate_json(row[0])

    def iter_run_events(
        self, run_id: str, *, tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> Iterator[EventEnvelope]:
        """同步迭代（CLI/测试用）；异步路径请用 aiter_run_events（AD-10）。

        给定作用域时按 (tenant_id, project_id) 过滤（AD-7）。
        """
        _validate_scope_pair(tenant_id, project_id)
        query = "SELECT data FROM events WHERE run_id=?"
        params: list[object] = [run_id]
        if tenant_id is not None:
            query += " AND tenant_id=? AND project_id=?"
            params += [tenant_id, project_id]
        query += " ORDER BY seq"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        for row in rows:
            yield EventEnvelope.model_validate_json(row[0])

    async def aiter_run_events(
        self, run_id: str, *, tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> list[EventEnvelope]:
        """异步版事件迭代（fetchall 经 to_thread，不在事件循环做阻塞 IO）。"""
        return await asyncio.to_thread(
            lambda: list(self.iter_run_events(run_id, tenant_id=tenant_id,
                                              project_id=project_id))
        )

    # ---- Artifact（StorageAdapter 端口 + 元数据/作用域扩展）----
    async def save_artifact(
        self,
        payload: bytes,
        *,
        mime: str | None = None,
        source: str | None = None,
        classification: str | None = None,
        retention: str | None = None,
        tags: dict[str, str] | None = None,
        tenant_id: str = DEFAULT_TENANT,
        project_id: str = DEFAULT_PROJECT,
    ) -> str:
        return await asyncio.to_thread(
            self._save_artifact_sync,
            payload,
            mime,
            source,
            classification,
            retention,
            tags,
            tenant_id,
            project_id,
        )

    def _save_artifact_sync(
        self,
        payload: bytes,
        mime: str | None,
        source: str | None,
        classification: str | None,
        retention: str | None,
        tags: dict[str, str] | None,
        tenant_id: str,
        project_id: str,
    ) -> str:
        sha = hashlib.sha256(payload).hexdigest()
        blob_path = self.objects_dir / sha[:2] / sha
        # AD-3：先落盘、写后重读校验，成功后才允许元数据/引用（无部分状态）。
        if not blob_path.exists():
            blob_path.parent.mkdir(parents=True, exist_ok=True)
            # 唯一临时名：并发写同内容时不共享 .tmp 路径（评审修复）
            tmp = blob_path.with_name(f"{sha}.{threading.get_ident()}.tmp")
            tmp.write_bytes(payload)
            if hashlib.sha256(tmp.read_bytes()).hexdigest() != sha:
                tmp.unlink(missing_ok=True)
                raise ArtifactCorruptedError(sha)
            tmp.replace(blob_path)
        elif hashlib.sha256(blob_path.read_bytes()).hexdigest() != sha:
            # 已存在的字节被篡改：不得静默复用（评审修复）
            raise ArtifactCorruptedError(sha)
        new_tags = json.dumps(tags or {}, sort_keys=True, separators=(",", ":"))
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO artifacts"
                " (sha256, mime, size, source, classification, retention,"
                "  created_at, tags_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (sha, mime, len(payload), source, classification, retention,
                 _utcnow_iso(), new_tags),
            )
            if tags:
                # 去重命中：标签并集合并（Story 2.1）
                row = self._conn.execute(
                    "SELECT tags_json FROM artifacts WHERE sha256=?", (sha,)
                ).fetchone()
                existing = json.loads(row[0]) if row and row[0] else {}
                merged = {**existing, **tags}
                if merged != existing:
                    self._conn.execute(
                        "UPDATE artifacts SET tags_json=? WHERE sha256=?",
                        (json.dumps(merged, sort_keys=True, separators=(",", ":")), sha),
                    )
            self._conn.execute(
                "INSERT OR IGNORE INTO artifact_refs"
                " (tenant_id, project_id, sha256, referenced_at) VALUES (?, ?, ?, ?)",
                (tenant_id, project_id, sha, _utcnow_iso()),
            )
        return sha

    async def get_artifact(
        self,
        sha256: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> bytes:
        return await asyncio.to_thread(
            self._get_artifact_sync, sha256, tenant_id, project_id
        )

    def _get_artifact_sync(
        self, sha256: str, tenant_id: str | None, project_id: str | None
    ) -> bytes:
        _validate_scope_pair(tenant_id, project_id)
        if tenant_id is not None and project_id is not None:
            with self._lock:
                ref = self._conn.execute(
                    "SELECT 1 FROM artifact_refs WHERE tenant_id=? AND project_id=?"
                    " AND sha256=?",
                    (tenant_id, project_id, sha256),
                ).fetchone()
            if ref is None:
                raise ArtifactNotFoundError(sha256, reason="not reachable in scope")
        blob_path = self.objects_dir / sha256[:2] / sha256
        if not blob_path.exists():
            raise ArtifactNotFoundError(sha256)
        content = blob_path.read_bytes()
        if hashlib.sha256(content).hexdigest() != sha256:
            raise ArtifactCorruptedError(sha256)
        return content

    # ---- 元数据查询（作用域过滤，AD-7/14）----
    async def artifact_info(
        self, sha256: str, *, tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, object] | None:
        """元数据读取：给定作用域时必须持有该租户引用（AD-14 可达性）；
        无作用域调用仅供存储内部/审计用途。"""
        return await asyncio.to_thread(
            self._artifact_info_sync, sha256, tenant_id, project_id
        )

    def _artifact_info_sync(
        self, sha256: str, tenant_id: str | None, project_id: str | None
    ) -> dict[str, object] | None:
        _validate_scope_pair(tenant_id, project_id)
        if tenant_id is not None and project_id is not None:
            with self._lock:
                ref = self._conn.execute(
                    "SELECT 1 FROM artifact_refs WHERE tenant_id=? AND project_id=?"
                    " AND sha256=?",
                    (tenant_id, project_id, sha256),
                ).fetchone()
            if ref is None:
                raise ArtifactNotFoundError(sha256, reason="not reachable in scope")
        with self._lock:
            row = self._conn.execute(
                "SELECT sha256, mime, size, source, classification, retention,"
                " created_at FROM artifacts WHERE sha256=?",
                (sha256,),
            ).fetchone()
        if row is None:
            return None
        keys = (
            "sha256",
            "mime",
            "size",
            "source",
            "classification",
            "retention",
            "created_at",
        )
        return dict(zip(keys, row, strict=True))

    async def list_artifacts(
        self, tenant_id: str, project_id: str, *, classification: str | None = None
    ) -> list[dict[str, object]]:
        return await asyncio.to_thread(
            self._list_artifacts_sync, tenant_id, project_id, classification
        )

    def _list_artifacts_sync(
        self, tenant_id: str, project_id: str, classification: str | None
    ) -> list[dict[str, object]]:
        query = (
            "SELECT a.sha256, a.mime, a.size, a.source, a.classification, a.retention,"
            " a.created_at, r.referenced_at FROM artifact_refs r"
            " JOIN artifacts a ON a.sha256 = r.sha256"
            " WHERE r.tenant_id=? AND r.project_id=?"
        )
        params: list[object] = [tenant_id, project_id]
        if classification is not None:
            query += " AND a.classification=?"
            params.append(classification)
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
            "referenced_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]


__all__ = [
    "DEFAULT_PROJECT",
    "DEFAULT_TENANT",
    "ArtifactCorruptedError",
    "ArtifactNotFoundError",
    "SqliteStorage",
]
