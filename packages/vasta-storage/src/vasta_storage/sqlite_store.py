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
from pathlib import Path

from vasta_protocols.envelope import EventEnvelope
from vasta_protocols.errors import DuplicateEventError, VastaError
from vasta_protocols.protocols import STORAGE_PROTOCOL_VERSION

from ._bookkeeping import utcnow_iso as _utcnow_iso
from ._scope import validate_scope_pair as _validate_scope_pair
from .lineage import LineageMixin
from .search import EvidenceSearchMixin

DEFAULT_TENANT = "t-default"
DEFAULT_PROJECT = "p-default"

_SCHEMA_VERSION = 4

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
CREATE INDEX IF NOT EXISTS idx_events_scope_ts
    ON events (tenant_id, project_id, ts);
CREATE TABLE IF NOT EXISTS derived_assets (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    derived_sha256 TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    transform TEXT NOT NULL,
    transform_params_json TEXT NOT NULL,
    transformer_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, project_id, derived_sha256, source_sha256, transform)
);
CREATE TABLE IF NOT EXISTS entity_index (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    entity_value TEXT NOT NULL,
    kind TEXT NOT NULL,
    ref TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, project_id, entity_key, entity_value, kind, ref)
);
CREATE INDEX IF NOT EXISTS idx_entity_lookup
    ON entity_index (tenant_id, project_id, entity_key, entity_value);
CREATE TABLE IF NOT EXISTS entity_alias (
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    alias_value TEXT NOT NULL,
    canonical_value TEXT NOT NULL,
    PRIMARY KEY (tenant_id, project_id, entity_key, alias_value)
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


def _valid_entity_value(value: object) -> bool:
    """实体索引值校验（评审修复）：仅标量入索引——None/嵌套 dict/list
    曾被 str() 成字面量落库（'None'、「{'id': 7}」），永远检索不到
    预期实体且与真实字面量撞键。"""
    return isinstance(value, (str, int, float, bool))




class SqliteStorage(EvidenceSearchMixin, LineageMixin):
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

    # ---- 实体索引（Story 9.2，FR-013 字母级收口）----

    async def search_by_entity(
        self,
        entity_key: str,
        entity_value: str,
        *,
        tenant_id: str,
        project_id: str,
        include_derived: bool = True,
    ) -> list[dict[str, object]]:
        """按业务实体键检索——命中跨事件/工件/派生物（血缘一跳）。

        别名先解析为 canonical（同键别名表命中即替换）；
        作用域 fail-closed（空/空白对拒）。"""
        from ._scope import validate_scope_pair

        validate_scope_pair(tenant_id, project_id)
        return await asyncio.to_thread(
            self._search_by_entity_sync,
            entity_key, entity_value, tenant_id, project_id, include_derived,
        )

    def _search_by_entity_sync(
        self,
        entity_key: str,
        entity_value: str,
        tenant_id: str,
        project_id: str,
        include_derived: bool,
    ) -> list[dict[str, object]]:
        with self._lock:
            # 别名解析（同键）——命中别名替换为 canonical
            # （评审修复：SELECT 移入锁内——曾与他线程写事务交错）
            alias_row = self._conn.execute(
                "SELECT canonical_value FROM entity_alias"
                " WHERE tenant_id=? AND project_id=? AND entity_key=?"
                " AND alias_value=?",
                (tenant_id, project_id, entity_key, entity_value),
            ).fetchone()
            if alias_row is not None:
                entity_value = alias_row[0]
            hits: list[dict[str, object]] = []
            for key, value, kind, ref in self._conn.execute(
                "SELECT entity_key, entity_value, kind, ref FROM entity_index"
                " WHERE tenant_id=? AND project_id=? AND entity_key=?"
                " AND entity_value=? ORDER BY created_at",
                (tenant_id, project_id, entity_key, entity_value),
            ):
                hits.append({
                    "entity_key": key, "entity_value": value,
                    "kind": kind, "ref": ref,
                })
            if include_derived and hits:
                # 血缘一跳：源工件命中的派生物并入（derived kind）
                shas = [h["ref"] for h in hits if h["kind"] == "artifact"]
                for sha in shas:
                    for row in self._conn.execute(
                        "SELECT derived_sha256 FROM derived_assets"
                        " WHERE tenant_id=? AND project_id=? AND source_sha256=?",
                        (tenant_id, project_id, sha),
                    ):
                        hits.append({
                            "entity_key": entity_key,
                            "entity_value": entity_value,
                            "kind": "derived", "ref": row[0],
                        })
        return hits

    async def register_entity_alias(
        self,
        entity_key: str,
        alias_value: str,
        canonical_value: str,
        *,
        tenant_id: str,
        project_id: str,
    ) -> None:
        """登记实体别名（alias → canonical；检索时自动解析）。"""
        from ._scope import validate_scope_pair

        validate_scope_pair(tenant_id, project_id)
        await asyncio.to_thread(
            self._register_alias_sync,
            entity_key, alias_value, canonical_value, tenant_id, project_id,
        )

    def _register_alias_sync(
        self,
        entity_key: str,
        alias_value: str,
        canonical_value: str,
        tenant_id: str,
        project_id: str,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO entity_alias"
                " (tenant_id, project_id, entity_key, alias_value,"
                "  canonical_value) VALUES (?, ?, ?, ?, ?)",
                (tenant_id, project_id, entity_key,
                 alias_value, canonical_value),
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- 事件（StorageAdapter 端口）----
    async def append_event(self, envelope: EventEnvelope) -> EventEnvelope:
        return await asyncio.to_thread(self._append_event_sync, envelope)

    def _append_event_sync(self, envelope: EventEnvelope) -> EventEnvelope:
        entity_refs = envelope.payload.get("entity_refs")
        if not isinstance(entity_refs, dict):
            entity_refs = None
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
            if entity_refs is not None:
                event_ref = f"{envelope.run_id}:{envelope.seq}"
                for key, value in entity_refs.items():
                    if not _valid_entity_value(value):
                        continue  # 非标量不入索引（同 save_artifact——评审修复）
                    self._conn.execute(
                        "INSERT OR IGNORE INTO entity_index"
                        " (tenant_id, project_id, entity_key, entity_value,"
                        "  kind, ref, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (envelope.tenant_id, envelope.project_id,
                         str(key), str(value), "event", event_ref, _utcnow_iso()),
                    )
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

    def last_event_info(
        self, run_id: str,
    ) -> tuple[int, str | None] | None:
        """该 run 的最大 seq 及其 event_id（点查——Sequencer 同步快路径，
        替代全量重扫；无事件返回 None）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT seq, event_id FROM events WHERE run_id=?"
                " ORDER BY seq DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return (int(row[0]), row[1])

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
        entities: dict[str, str] | None = None,
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
            entities,
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
        entities: dict[str, str] | None,
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
        # tags 属内容级全局元数据（同内容同标签，跨作用域共享键值）——
        # 租户私有标签随 Stage 3 数据治理（FR-017/018）迁移到作用域表。
        from ._scope import validate_tag_key

        for key in tags or {}:
            validate_tag_key(key)
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
                # 去重命中：新键并入、同键冲突保留先到值（first-wins，
                # 不跨作用域覆盖既有标签——评审修复）
                row = self._conn.execute(
                    "SELECT tags_json FROM artifacts WHERE sha256=?", (sha,)
                ).fetchone()
                existing = json.loads(row[0]) if row and row[0] else {}
                additions = {k: v for k, v in tags.items() if k not in existing}
                if additions:
                    merged = {**existing, **additions}
                    self._conn.execute(
                        "UPDATE artifacts SET tags_json=? WHERE sha256=?",
                        (json.dumps(merged, sort_keys=True, separators=(",", ":")), sha),
                    )
            self._conn.execute(
                "INSERT OR IGNORE INTO artifact_refs"
                " (tenant_id, project_id, sha256, referenced_at) VALUES (?, ?, ?, ?)",
                (tenant_id, project_id, sha, _utcnow_iso()),
            )
            for key, value in (entities or {}).items():
                if not _valid_entity_value(value):
                    # 评审修复：非标量（None/嵌套 dict/list）不入索引——
                    # 曾 str() 字面量落库（'None'/「{'id': 7}」——永远检索
                    # 不到预期实体，且与真实字面量撞键）
                    continue
                self._conn.execute(
                    "INSERT OR IGNORE INTO entity_index"
                    " (tenant_id, project_id, entity_key, entity_value,"
                    "  kind, ref, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (tenant_id, project_id, key, str(value),
                     "artifact", sha, _utcnow_iso()),
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
