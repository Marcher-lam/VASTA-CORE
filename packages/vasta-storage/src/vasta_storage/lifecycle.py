"""数据生命周期与删除证明（Story 9.3，FR-017，G2）。

- 热/温/冷分层（LifecyclePolicy 可配置）+ classify_artifacts（dry-run 报告
  ——不移动数据，分级是元数据标记策略）；
- 法律保留（legal_holds 表 + place/release）；
- 删除请求（request_deletion）：依赖检查链——法律保留 / 派生血缘 /
  实体索引引用——任一命中即 blocked 且返回原因清单；全过则删 blob +
  元数据行，随后经 Sequencer 落 ``deletion.proved`` 事件（sha/reason/
  tier/timestamp——**不含内容**）；
- 幂等：已删 sha 再请求返回成功但不重复发事件。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.sequencer import EventSequencer

from ._bookkeeping import utcnow_iso

_LIFECYCLE_RUN = "lifecycle"


@dataclass(frozen=True)
class LifecyclePolicy:
    """热/温/冷分层策略（天数为保留期下限——Stage 4 实际迁移）。"""

    hot_days: int = 7
    warm_days: int = 30

    def tier_of(self, age_days: float) -> str:
        if age_days <= self.hot_days:
            return "hot"
        if age_days <= self.warm_days:
            return "warm"
        return "cold"


class DeletionBlocker(BaseModel):
    """删除阻止原因。"""

    model_config = ConfigDict(extra="forbid")

    code: str  # legal.hold_active | lifecycle.derived_dependency | lifecycle.entity_reference
    detail: str


class DeletionResult(BaseModel):
    """删除请求结果。"""

    model_config = ConfigDict(extra="forbid")

    sha256: str
    status: str  # deleted | blocked | already_deleted
    blockers: list[DeletionBlocker] = Field(default_factory=list)
    proof_event_seq: int | None = None


def classify_artifacts(
    store: Any, policy: LifecyclePolicy, *,
    tenant_id: str, project_id: str,
) -> list[dict[str, Any]]:
    """按工件年龄分层（dry-run——分类报告，不移动数据）。"""
    from vasta_protocols.ids import now_utc
    now = now_utc()
    report: list[dict[str, Any]] = []
    with store._lock:  # noqa: SLF001 ——同包 mixin 访问
        for sha, created_at in store._conn.execute(  # noqa: SLF001
            "SELECT a.sha256, a.created_at FROM artifacts a"
            " JOIN artifact_refs r ON a.sha256 = r.sha256"
            " WHERE r.tenant_id = ? AND r.project_id = ?",
            (tenant_id, project_id),
        ):
            try:
                created = datetime.fromisoformat(created_at)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                created = now
            age_days = (now - created).total_seconds() / 86400
            report.append({
                "sha": sha, "age_days": round(age_days, 1),
                "tier": policy.tier_of(age_days),
            })
    return report


async def place_legal_hold(
    store: Any, sha256: str, *,
    jurisdiction: str, note: str = "",
    tenant_id: str, project_id: str,
) -> None:
    """法律保留登记（删除被阻直至 release）。"""
    with store._lock, store._conn:  # noqa: SLF001
        store._conn.execute(  # noqa: SLF001
            "CREATE TABLE IF NOT EXISTS legal_holds ("
            "  sha256 TEXT NOT NULL, tenant_id TEXT NOT NULL,"
            "  project_id TEXT NOT NULL, jurisdiction TEXT NOT NULL,"
            "  note TEXT, placed_at TEXT NOT NULL, released_at TEXT,"
            "  PRIMARY KEY (sha256, tenant_id, project_id, jurisdiction))"
        )
        store._conn.execute(
            "INSERT OR REPLACE INTO legal_holds"
            " (sha256, tenant_id, project_id, jurisdiction, note,"
            "  placed_at, released_at) VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (sha256, tenant_id, project_id, jurisdiction, note, utcnow_iso()),
        )


async def release_legal_hold(
    store: Any, sha256: str, *,
    tenant_id: str, project_id: str,
) -> None:
    with store._lock, store._conn:  # noqa: SLF001
        store._conn.execute(  # noqa: SLF001
            "UPDATE legal_holds SET released_at = ?"
            " WHERE sha256 = ? AND tenant_id = ? AND project_id = ?"
            " AND released_at IS NULL",
            (utcnow_iso(), sha256, tenant_id, project_id),
        )


def _holds_table(store: Any) -> None:
    store._conn.execute(  # noqa: SLF001
        "CREATE TABLE IF NOT EXISTS legal_holds ("
        "  sha256 TEXT NOT NULL, tenant_id TEXT NOT NULL,"
        "  project_id TEXT NOT NULL, jurisdiction TEXT NOT NULL,"
        "  note TEXT, placed_at TEXT NOT NULL, released_at TEXT,"
        "  PRIMARY KEY (sha256, tenant_id, project_id, jurisdiction))"
    )


def _active_holds(store: Any, sha: str, tenant: str, project: str) -> list[str]:
    """活跃法律保留（**调用方须已持 store._lock**——事务内检查防 TOCTOU）。"""
    _holds_table(store)
    rows = store._conn.execute(  # noqa: SLF001
        "SELECT jurisdiction FROM legal_holds"
        " WHERE sha256=? AND tenant_id=? AND project_id=?"
        " AND released_at IS NULL",
        (sha, tenant, project),
    ).fetchall()
    return [r[0] for r in rows]


def _has_derived(store: Any, sha: str, tenant: str, project: str) -> bool:
    """派生血缘引用（**调用方须已持 store._lock**）。"""
    row = store._conn.execute(  # noqa: SLF001
        "SELECT 1 FROM derived_assets"
        " WHERE tenant_id=? AND project_id=? AND source_sha256=?"
        " LIMIT 1",
        (tenant, project, sha),
    ).fetchone()
    return row is not None


def _has_entity_refs(store: Any, sha: str, tenant: str, project: str) -> bool:
    """实体索引引用（**调用方须已持 store._lock**）。"""
    row = store._conn.execute(  # noqa: SLF001
        "SELECT 1 FROM entity_index"
        " WHERE tenant_id=? AND project_id=? AND ref=? AND kind='artifact'"
        " LIMIT 1",
        (tenant, project, sha),
    ).fetchone()
    return row is not None


async def request_deletion(
    store: Any, sha256: str, *,
    reason: str,
    tenant_id: str = "t-default",
    project_id: str = "p-default",
    policy: LifecyclePolicy | None = None,
) -> DeletionResult:
    """删除请求（依赖检查 → 执行 → 证明事件；幂等）。

    租户边界（评审修复）：依赖检查与删除按**本租户作用域**执行——
    只删本租户的 artifact_scope 映射；全局引用计数归零后才清
    artifacts 行 + blob 字节（跨租户共享字节不被单租户删除破坏）。
    检查与删除在同一锁/事务内（TOCTOU——法律保留不再有并发窗口）。"""
    # 幂等：本作用域已无该 sha 的映射 = 已删（不重复发事件）
    with store._lock:  # noqa: SLF001 ——同包 mixin 访问
        scoped = store._conn.execute(  # noqa: SLF001
            "SELECT 1 FROM artifact_refs WHERE sha256 = ?"
            " AND tenant_id = ? AND project_id = ?",
            (sha256, tenant_id, project_id),
        ).fetchone()
    if scoped is None:
        return DeletionResult(sha256=sha256, status="already_deleted")

    # 依赖检查 + 执行在同一事务（TOCTOU：检查后、删除前落保留不再漏过）
    blob_orphan = False
    with store._lock, store._conn:  # noqa: SLF001
        blockers: list[DeletionBlocker] = []
        for jurisdiction in _active_holds(
                store, sha256, tenant_id, project_id):
            blockers.append(DeletionBlocker(
                code="legal.hold_active",
                detail=f"法律保留 {jurisdiction} 生效中（release 后方可删除）",
            ))
        if _has_derived(store, sha256, tenant_id, project_id):
            blockers.append(DeletionBlocker(
                code="lifecycle.derived_dependency",
                detail="存在派生物血缘引用（先删除派生物或保留源）",
            ))
        if _has_entity_refs(store, sha256, tenant_id, project_id):
            blockers.append(DeletionBlocker(
                code="lifecycle.entity_reference",
                detail="实体索引仍引用该工件（先解除认知/检索依赖）",
            ))
        if blockers:
            return DeletionResult(sha256=sha256, status="blocked",
                                  blockers=blockers)

        # 执行删除（事务内）：先清本租户映射（含 restricted 孤儿行）
        store._conn.execute(  # noqa: SLF001 ——同包（evidence_access 同一定义）
            "CREATE TABLE IF NOT EXISTS restricted_artifacts ("
            "  sha256 TEXT NOT NULL, tenant_id TEXT NOT NULL,"
            "  project_id TEXT NOT NULL, reason TEXT NOT NULL,"
            "  restricted_at TEXT NOT NULL,"
            "  PRIMARY KEY (sha256, tenant_id, project_id))"
        )
        store._conn.execute(  # noqa: SLF001
            "DELETE FROM artifact_refs WHERE sha256 = ?"
            " AND tenant_id = ? AND project_id = ?",
            (sha256, tenant_id, project_id),
        )
        store._conn.execute(  # noqa: SLF001
            "DELETE FROM restricted_artifacts WHERE sha256 = ?"
            " AND tenant_id = ? AND project_id = ?",
            (sha256, tenant_id, project_id),
        )
        remaining = store._conn.execute(  # noqa: SLF001
            "SELECT COUNT(*) FROM artifact_refs WHERE sha256 = ?",
            (sha256,),
        ).fetchone()[0]
        if remaining == 0:
            # 全局引用计数归零——清 artifacts 行（存在性锚）；
            # blob 文件在事务提交后清理（行先删=读路径不再命中；
            # 崩溃残留的孤儿文件由存储运维清理，不影响读取正确性）
            store._conn.execute(  # noqa: SLF001
                "DELETE FROM artifacts WHERE sha256 = ?", (sha256,)
            )
            blob_orphan = True
    if blob_orphan:
        blob = store.objects_dir / sha256[:2] / sha256
        blob.unlink(missing_ok=True)

    # 证明事件（不含内容——FR-017 后果条款）
    tier = ""
    if policy is not None:
        tier = policy.tier_of(float("inf"))
    sequencer = EventSequencer(store, _LIFECYCLE_RUN,
                               tenant_id=tenant_id, project_id=project_id)
    proof = await sequencer.emit("artifact.deletion_proved", {
        "sha256": sha256,
        "reason": reason,
        "tier": tier,
        "requested_by": f"{tenant_id}:{project_id}",
        "content_excluded": True,  # 显式声明不含内容
    })
    return DeletionResult(sha256=sha256, status="deleted",
                          proof_event_seq=proof.seq)


__all__ = ["DeletionBlocker", "DeletionResult", "LifecyclePolicy",
           "classify_artifacts", "place_legal_hold", "release_legal_hold",
           "request_deletion"]
