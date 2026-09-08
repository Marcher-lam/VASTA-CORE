"""派生资产生命周期：血缘登记与回链校验（FR-012，Story 2.3）。

- save_derived：派生载荷照走全局 CAS（save_artifact），血缘行登记
  源 sha / 变换名 / 变换参数 / 变换器版本 / 作用域；
- lineage / verify_lineage：一键回链——源与派生体均可取回且哈希通过
  才算 verified；源缺失 → source_missing（"来源不可再验证"，不静默），
  源损坏 → source_corrupted。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError

from ._scope import validate_scope_pair


class DerivationRecord(BaseModel):
    """一条血缘记录（派生物 ← 源，经变换）。"""

    model_config = ConfigDict(extra="forbid")

    derived_sha256: str
    source_sha256: str
    transform: str
    params: dict[str, Any] = Field(default_factory=dict)
    transformer_version: str
    created_at: str


class RecordVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record: DerivationRecord
    status: str  # verified | source_missing | source_corrupted | derived_missing


class LineageVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    derived_sha256: str
    derived_retrievable: bool
    records: list[RecordVerification]

    @property
    def all_verified(self) -> bool:
        return self.derived_retrievable and bool(self.records) and all(
            r.status == "verified" for r in self.records
        )


class LineageMixin:
    """挂载于 SqliteStorage。"""

    async def save_derived(
        self,
        payload: bytes,
        *,
        source_sha256: str,
        transform: str,
        params: dict[str, Any] | None = None,
        transformer_version: str,
        mime: str | None = None,
        tenant_id: str = "t-default",
        project_id: str = "p-default",
    ) -> str:
        """登记派生物：载荷入 CAS（哈希校验），血缘行 OR IGNORE 幂等。"""
        derived_sha = await self.save_artifact(
            payload,
            mime=mime,
            source=f"derived.{transform}",
            tenant_id=tenant_id,
            project_id=project_id,
        )
        await asyncio.to_thread(
            self._save_derived_row_sync,
            derived_sha,
            source_sha256,
            transform,
            params or {},
            transformer_version,
            tenant_id,
            project_id,
        )
        return derived_sha

    def _save_derived_row_sync(
        self,
        derived_sha: str,
        source_sha: str,
        transform: str,
        params: dict[str, Any],
        transformer_version: str,
        tenant_id: str,
        project_id: str,
    ) -> None:
        from ._bookkeeping import utcnow_iso

        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO derived_assets"
                " (derived_sha256, source_sha256, transform, transform_params_json,"
                "  transformer_version, created_at, tenant_id, project_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    derived_sha,
                    source_sha,
                    transform,
                    json.dumps(params, sort_keys=True, separators=(",", ":"), default=repr),
                    transformer_version,
                    utcnow_iso(),
                    tenant_id,
                    project_id,
                ),
            )

    async def lineage(
        self,
        derived_sha256: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> list[DerivationRecord]:
        """血缘列表（多源支持）；不含校验——校验走 verify_lineage。"""
        validate_scope_pair(tenant_id, project_id)
        return await asyncio.to_thread(
            self._lineage_sync, derived_sha256, tenant_id, project_id
        )

    def _lineage_sync(
        self, derived_sha256: str, tenant_id: str | None, project_id: str | None
    ) -> list[DerivationRecord]:
        query = (
            "SELECT derived_sha256, source_sha256, transform, transform_params_json,"
            " transformer_version, created_at FROM derived_assets WHERE derived_sha256=?"
        )
        params: list[Any] = [derived_sha256]
        if tenant_id is not None and project_id is not None:
            query += " AND tenant_id=? AND project_id=?"
            params += [tenant_id, project_id]
        query += " ORDER BY created_at, source_sha256"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [
            DerivationRecord(
                derived_sha256=row[0],
                source_sha256=row[1],
                transform=row[2],
                params=json.loads(row[3]),
                transformer_version=row[4],
                created_at=row[5],
            )
            for row in rows
        ]

    async def verify_lineage(
        self,
        derived_sha256: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> LineageVerification:
        """一键回链校验：源与派生体取回 + 哈希校验；缺失/损坏显式标记。"""
        validate_scope_pair(tenant_id, project_id)
        records = await self.lineage(
            derived_sha256, tenant_id=tenant_id, project_id=project_id
        )
        if not records:
            raise VastaError(
                code="lineage.not_found",
                message=f"no derivation records for {derived_sha256[:16]}… in scope",
            )
        derived_retrievable = True
        try:
            await self.get_artifact(
                derived_sha256, tenant_id=tenant_id, project_id=project_id
            )
        except VastaError:
            derived_retrievable = False

        verifications: list[RecordVerification] = []
        for record in records:
            status = "verified"
            try:
                await self.get_artifact(
                    record.source_sha256, tenant_id=tenant_id, project_id=project_id
                )
            except VastaError as exc:
                status = (
                    "source_corrupted" if exc.code == "artifact.corrupted" else "source_missing"
                )
            verifications.append(RecordVerification(record=record, status=status))
        return LineageVerification(
            derived_sha256=derived_sha256,
            derived_retrievable=derived_retrievable,
            records=verifications,
        )


__all__ = [
    "DerivationRecord",
    "LineageMixin",
    "LineageVerification",
    "RecordVerification",
]
