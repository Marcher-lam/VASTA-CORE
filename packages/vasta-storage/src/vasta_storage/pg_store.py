"""PostgresEventStore（Story 9.1，Team 档——FR-070 存储侧）。

- asyncpg **可选 extra**（pyproject [project.optional-dependencies].pg）：
  延迟导入——无驱动时构造期明确报错（不静默降级）；
- 核心 StorageAdapter 契约：事件 (run_id,seq) 唯一、artifact bytea +
  ON CONFLICT 去重、取回哈希校验、作用域映射（AD-9/14：字节全局去重、
  租户可达性分离）；
- 检索/血缘/图像 mixins 为 SQLite 耦合——不在本 Story（后续 Stage 3 Story）；
- 组合形态：``PostgresEventStore(dsn, blob_store=S3BlobStore(...))``——
  事件入 PG、工件入 S3（团队档）；默认工件仍入 PG bytea（小团队单库）。

集成测试 DSN 门控：``VASTA_PG_DSN`` 环境变量（无则 skip——Windows
resource 模块先例）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from vasta_protocols.envelope import EventEnvelope
from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import STORAGE_PROTOCOL_VERSION

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    run_id      TEXT NOT NULL,
    seq         BIGINT NOT NULL,
    type        TEXT NOT NULL,
    parent_event_id TEXT,
    ts          TIMESTAMPTZ NOT NULL,
    tenant_id   TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    event_id    TEXT NOT NULL UNIQUE,
    payload     JSONB NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_events_tenant ON events (tenant_id, project_id, run_id);

CREATE TABLE IF NOT EXISTS artifacts (
    sha256       TEXT PRIMARY KEY,
    payload      BYTEA NOT NULL,
    mime         TEXT,
    source       TEXT,
    classification TEXT,
    retention    TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS artifact_scope (
    sha256    TEXT NOT NULL REFERENCES artifacts (sha256),
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    PRIMARY KEY (sha256, tenant_id, project_id)
);
CREATE TABLE IF NOT EXISTS entity_index (
    tenant_id   TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    entity_key  TEXT NOT NULL,
    entity_value TEXT NOT NULL,
    kind        TEXT NOT NULL,
    ref         TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, project_id, entity_key, entity_value, kind, ref)
);
CREATE INDEX IF NOT EXISTS idx_entity_lookup
    ON entity_index (tenant_id, project_id, entity_key, entity_value);
CREATE TABLE IF NOT EXISTS entity_alias (
    tenant_id  TEXT NOT NULL,
    project_id TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    alias_value TEXT NOT NULL,
    canonical_value TEXT NOT NULL,
    PRIMARY KEY (tenant_id, project_id, entity_key, alias_value)
);
"""


def _ts(value: Any) -> datetime:
    """asyncpg datetime → 带 UTC 的 datetime（信封要求 tzinfo）。"""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return value


class PostgresEventStore:
    """PG 事件库（+可选外部 blob 后端）。protocol_version 满足端口。"""

    protocol_version = STORAGE_PROTOCOL_VERSION

    def __init__(
        self,
        dsn: str,
        *,
        blob_store: Any | None = None,
        schema_setup: bool = True,
    ) -> None:
        from importlib.util import find_spec

        try:
            if find_spec('asyncpg') is None:
                raise ImportError('asyncpg not installed')
        except ImportError as exc:  # pragma: no cover——驱动门控
            raise VastaError(
                code="pg.driver_missing",
                message="PostgresEventStore 需要 pg 可选 extra"
                        "（uv sync --extra pg 安装 asyncpg）",
            ) from exc
        self._dsn = dsn
        self._pool: Any | None = None
        # 评审修复：并发首用双 pool 泄漏——锁保护首建
        self._pool_lock: Any = None  # 延迟创建（asyncio.Lock 需循环）
        self._blob_store = blob_store  # None → 工件入 PG bytea
        self._schema_setup = schema_setup

    def _get_pool_lock(self) -> Any:
        import asyncio

        if self._pool_lock is None:
            self._pool_lock = asyncio.Lock()
        return self._pool_lock

    async def _ensure_pool(self) -> Any:
        import asyncpg

        if self._pool is None:
            async with self._get_pool_lock():
                if self._pool is None:  # 双检——并发首用只建一个
                    self._pool = await asyncpg.create_pool(self._dsn,
                                                           min_size=1)
                    if self._schema_setup:
                        async with self._pool.acquire() as conn:
                            await conn.execute(_SCHEMA)
        return self._pool

    async def _dedicated_conn(self) -> Any:
        """专用连接（不进共享 pool）——同步临时循环路径用。

        评审修复：sync iter 曾把共享 pool 绑到临时事件循环（loop 关闭
        后异步路径复用同一 pool 跨循环报废）——临时上下文一律专用连接，
        用后即关。"""
        import asyncpg

        conn = await asyncpg.connect(self._dsn)
        if self._schema_setup:
            await conn.execute(_SCHEMA)
        return conn

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # ---- 事件（AD-2：唯一写路径 + (run_id,seq) 唯一）----
    async def append_event(self, envelope: EventEnvelope) -> EventEnvelope:
        from vasta_protocols.errors import DuplicateEventError

        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO events
                        (run_id, seq, type, parent_event_id, ts,
                         tenant_id, project_id, event_id, payload)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                    """,
                    envelope.run_id, envelope.seq, envelope.type,
                    envelope.parent_event_id, envelope.ts,
                    envelope.tenant_id, envelope.project_id,
                    envelope.event_id,
                    json.dumps(envelope.payload, ensure_ascii=False),
                )
            except Exception as exc:
                # 评审修复：按约束名分流（曾按英文串 "duplicate key"
                # 分类——event_id 冲突被误报为 seq 冲突，非英文 locale
                # 直接漏裸异常）
                constraint = getattr(exc, "constraint_name", "") or ""
                if constraint in ("events_pkey", "events_event_id_key") \
                        or "duplicate key" in str(exc).lower():
                    if constraint == "events_event_id_key":
                        raise VastaError(
                            code="event.duplicate_id",
                            message=(f"event_id {envelope.event_id} "
                                     "already stored"),
                        ) from exc
                    raise DuplicateEventError(
                        envelope.run_id, envelope.seq) from exc
                raise
        return envelope

    async def get_event(self, run_id: str, seq: int) -> EventEnvelope:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM events WHERE run_id=$1 AND seq=$2", run_id, seq
            )
        if row is None:
            raise VastaError(
                code="storage.unknown_event",
                message=f"event {run_id}:{seq} 不存在",
            )
        return self._row_to_envelope(row)

    def _row_to_envelope(self, row: Any) -> EventEnvelope:
        return EventEnvelope.model_validate({
            "run_id": row["run_id"], "seq": row["seq"], "type": row["type"],
            "parent_event_id": row["parent_event_id"],
            "ts": _ts(row["ts"]),
            "tenant_id": row["tenant_id"], "project_id": row["project_id"],
            "event_id": row["event_id"],
            "payload": json.loads(row["payload"]),
        })

    def iter_run_events(
        self, run_id: str,
        *, tenant_id: str | None = None, project_id: str | None = None,
    ):
        """同步迭代（快照预取）——仅无事件循环上下文可用；
        事件循环内（asyncio 代码/pytest-asyncio）请用 aiter_run_events。

        评审修复：临时循环走专用连接（用后即关），不再创建/触碰共享
        pool——同步读一次不再把共享 pool 绑到已关闭的循环上。"""
        import asyncio as _aio

        try:
            _aio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise VastaError(
                code="pg.sync_iter_in_loop",
                message="事件循环内请用 aiter_run_events（同步迭代器仅供"
                        "无循环上下文）",
            )
        fetched = _aio.new_event_loop().run_until_complete(
            self._iter_dedicated(run_id, tenant_id, project_id))
        _aio.set_event_loop(None)
        return iter(fetched)

    async def _iter_dedicated(
        self, run_id: str,
        tenant_id: str | None, project_id: str | None,
    ) -> list[EventEnvelope]:
        conn = await self._dedicated_conn()
        try:
            query = "SELECT * FROM events WHERE run_id=$1"
            params: list[Any] = [run_id]
            if tenant_id is not None and project_id is not None:
                query += " AND tenant_id=$2 AND project_id=$3"
                params += [tenant_id, project_id]
            query += " ORDER BY seq"
            rows = await conn.fetch(query, *params)
            return [self._row_to_envelope(row) for row in rows]
        finally:
            await conn.close()

    async def last_event_info(
        self, run_id: str,
    ) -> tuple[int, str | None] | None:
        """该 run 最大 seq 及其 event_id（点查——Sequencer 同步快路径）。
        无事件返回 None。"""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT seq, event_id FROM events WHERE run_id=$1"
                " ORDER BY seq DESC LIMIT 1",
                run_id,
            )
        if row is None:
            return None
        return (int(row["seq"]), row["event_id"])

    async def aiter_run_events(
        self, run_id: str,
        tenant_id: str | None = None, project_id: str | None = None,
    ) -> list[EventEnvelope]:
        """异步迭代（事件循环内使用的正确入口）。"""
        return await self._iter_async(run_id, tenant_id, project_id)

    async def _iter_async(
        self, run_id: str,
        tenant_id: str | None, project_id: str | None,
    ) -> list[EventEnvelope]:
        pool = await self._ensure_pool()
        query = "SELECT * FROM events WHERE run_id=$1"
        params: list[Any] = [run_id]
        if tenant_id is not None and project_id is not None:
            query += " AND tenant_id=$2 AND project_id=$3"
            params += [tenant_id, project_id]
        query += " ORDER BY seq"
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [self._row_to_envelope(row) for row in rows]

    # ---- 工件（AD-3/AD-14：哈希全局去重 + 作用域映射分离）----
    async def save_artifact(
        self,
        payload: bytes,
        *,
        mime: str | None = None,
        source: str | None = None,
        classification: str | None = None,
        retention: str | None = None,
        entities: dict[str, str] | None = None,
        tenant_id: str = "t-default",
        project_id: str = "p-default",
    ) -> str:
        sha = hashlib.sha256(payload).hexdigest()
        bytea_in_pg = self._blob_store is None
        if not bytea_in_pg:
            # 组合形态：字节入外部 blob（AD-14 全局去重——head 命中同址）
            await self._blob_store.save_artifact(
                payload, mime=mime, source=source,
                classification=classification, retention=retention,
                tenant_id=tenant_id, project_id=project_id,
            )
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            # 评审修复：组合形态也落 PG 元数据（曾直接 return——
            # artifact_scope/entity_index 全丢，租户可达性与实体检索
            # 双失效）。artifacts 行在组合形态为占位（payload 空串——
            # 读路径走 blob，不消费该列；行仅为 FK 锚）。
            await conn.execute(
                """
                INSERT INTO artifacts (sha256, payload, mime, source,
                                       classification, retention)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (sha256) DO NOTHING
                """,
                sha, payload if bytea_in_pg else b"",
                mime, source, classification, retention,
            )
            await conn.execute(
                """
                INSERT INTO artifact_scope (sha256, tenant_id, project_id)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                """,
                sha, tenant_id, project_id,
            )
            for key, value in (entities or {}).items():
                if value is None or not isinstance(value, (str, int, float,
                                                           bool)):
                    continue  # 评审修复：非标量不入索引（None/嵌套不落库）
                await conn.execute(
                    """
                    INSERT INTO entity_index
                        (tenant_id, project_id, entity_key, entity_value,
                         kind, ref)
                    VALUES ($1, $2, $3, $4, 'artifact', $5)
                    ON CONFLICT DO NOTHING
                    """,
                    tenant_id, project_id, key, str(value), sha,
                )
        return sha

    async def get_artifact(
        self, sha256: str,
        *, tenant_id: str | None = None, project_id: str | None = None,
    ) -> bytes:
        if self._blob_store is not None:
            return await self._blob_store.get_artifact(
                sha256, tenant_id=tenant_id, project_id=project_id
            )
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            # 评审修复：给定作用域时校验租户可达性（AD-14——曾任何
            # 租户知道 sha 即可取字节）；不传作用域=管理面显式全量读
            if tenant_id is not None and project_id is not None:
                scoped = await conn.fetchval(
                    "SELECT 1 FROM artifact_scope"
                    " WHERE sha256=$1 AND tenant_id=$2 AND project_id=$3",
                    sha256, tenant_id, project_id,
                )
                if scoped is None:
                    raise VastaError(
                        code="artifact.not_found",
                        message=(f"artifact {sha256[:16]}… 在 "
                                 f"{tenant_id}:{project_id} 不可达"
                                 "（AD-14 作用域）"),
                    )
            row = await conn.fetchrow(
                "SELECT payload FROM artifacts WHERE sha256=$1", sha256
            )
        if row is None:
            raise VastaError(
                code="artifact.not_found",
                message=f"artifact {sha256[:16]}… 不存在",
            )
        payload = bytes(row["payload"])
        if hashlib.sha256(payload).hexdigest() != sha256:
            raise VastaError(
                code="artifact.corrupted",
                message=f"artifact {sha256[:16]}… 哈希校验失败",
            )
        return payload


__all__ = ["PostgresEventStore"]
