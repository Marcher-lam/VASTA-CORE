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
    status: str  # verified | source_missing | source_corrupted | derived_missing | derived_corrupted


class LineageVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    derived_sha256: str
    derived_status: str  # ok | derived_missing | derived_corrupted
    records: list[RecordVerification]

    @property
    def derived_retrievable(self) -> bool:
        return self.derived_status == "ok"

    @property
    def all_verified(self) -> bool:
        return self.derived_status == "ok" and bool(self.records) and all(
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
        """登记派生物：载荷入 CAS（哈希校验），血缘行幂等登记。

        - 源必须在本作用域可达（fail-fast，不登记悬空血缘）；
        - 同 (derived, source, transform) 重复登记幂等，但 params/version
          不同则拒绝（lineage.conflict）——不静默吞差异；
        - params 必须可 JSON 序列化（不静默 repr 化，保证参数可原样回读）。
        """
        try:
            json.dumps(params or {}, sort_keys=True)
        except TypeError as exc:
            raise VastaError(
                code="lineage.bad_params",
                message=f"params 含不可 JSON 序列化的值: {exc}",
            ) from exc
        try:
            await self.get_artifact(
                source_sha256, tenant_id=tenant_id, project_id=project_id
            )
        except VastaError as exc:
            raise VastaError(
                code="lineage.source_unreachable",
                message=(
                    f"source {source_sha256[:16]}... not reachable in scope"
                    f" ({exc.code}); refusing to register dangling lineage"
                ),
            ) from exc
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

        params_json = json.dumps(params, sort_keys=True, separators=(",", ":"))
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT transform_params_json, transformer_version FROM"
                " derived_assets WHERE tenant_id=? AND project_id=?"
                " AND derived_sha256=? AND source_sha256=? AND transform=?",
                (tenant_id, project_id, derived_sha, source_sha, transform),
            ).fetchone()
            if existing is not None and (
                existing[0] != params_json or existing[1] != transformer_version
            ):
                raise VastaError(
                    code="lineage.conflict",
                    message=(
                        f"derivation ({derived_sha[:12]}..., {source_sha[:12]}...,"
                        f" {transform}) already registered with different"
                        " params/version; refusing silent overwrite"
                    ),
                )
            self._conn.execute(
                "INSERT OR IGNORE INTO derived_assets"
                " (derived_sha256, source_sha256, transform, transform_params_json,"
                "  transformer_version, created_at, tenant_id, project_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    derived_sha,
                    source_sha,
                    transform,
                    params_json,
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
        derived_status = "ok"
        try:
            await self.get_artifact(
                derived_sha256, tenant_id=tenant_id, project_id=project_id
            )
        except VastaError as exc:
            if exc.code == "artifact.corrupted":
                derived_status = "derived_corrupted"
            elif exc.code == "artifact.not_found":
                derived_status = "derived_missing"
            else:
                raise  # 未知存储错误不得压平成"来源不可再验证"

        verifications: list[RecordVerification] = []
        for record in records:
            if derived_status != "ok":
                # Task 4：verified = 派生与源均可取回且哈希通过——
                # 派生侧坏则逐记录状态并入派生状态（不虚标 verified）
                status = derived_status
            else:
                status = "verified"
                try:
                    await self.get_artifact(
                        record.source_sha256, tenant_id=tenant_id, project_id=project_id
                    )
                except VastaError as exc:
                    if exc.code == "artifact.corrupted":
                        status = "source_corrupted"
                    elif exc.code == "artifact.not_found":
                        status = "source_missing"
                    else:
                        raise
            verifications.append(RecordVerification(record=record, status=status))
        return LineageVerification(
            derived_sha256=derived_sha256,
            derived_status=derived_status,
            records=verifications,
        )


__all__ = [
    "DerivationRecord",
    "LineageMixin",
    "LineageVerification",
    "RecordVerification",
]
