"""原始证据权限独立（Story 9.4，FR-018，G2）。

- 受限登记（restricted_artifacts 表）→ 原始 blob 取回被拒
  （`evidence.access_denied`——与 `artifact.not_found` 区分）；
- 派生物 / 聚合指标 / 血缘链 / 检索面**不受影响**（元数据面 vs 内容面的
  权限分界——FR-018 语义）；
- 权限判定落审计事件（`artifact.access_denied`——"access" 系统流）；
- 原始 `get_artifact` 不改（后向兼容）——权限检查是叠加层
  （`get_artifact_checked`）。
"""

from __future__ import annotations

from typing import Any

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

_ACCESS_RUN = "access"

_CREATE_RESTRICTED = """
CREATE TABLE IF NOT EXISTS restricted_artifacts (
    sha256 TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    restricted_at TEXT NOT NULL,
    PRIMARY KEY (sha256, tenant_id, project_id)
)
"""


async def restrict_evidence(
    store: Any, sha256: str, *, reason: str,
    tenant_id: str, project_id: str,
) -> None:
    """标记原始证据为受限（幂等——重复 restrict 更新 reason 不炸）。"""
    from ._bookkeeping import utcnow_iso

    with store._lock, store._conn:  # noqa: SLF001 ——同包访问
        store._conn.execute(_CREATE_RESTRICTED)  # noqa: SLF001
        store._conn.execute(  # noqa: SLF001
            "INSERT OR REPLACE INTO restricted_artifacts"
            " (sha256, tenant_id, project_id, reason, restricted_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (sha256, tenant_id, project_id, reason, utcnow_iso()),
        )


async def unrestrict_evidence(
    store: Any, sha256: str, *,
    tenant_id: str, project_id: str,
) -> None:
    with store._lock, store._conn:  # noqa: SLF001
        store._conn.execute(_CREATE_RESTRICTED)  # noqa: SLF001
        store._conn.execute(  # noqa: SLF001
            "DELETE FROM restricted_artifacts"
            " WHERE sha256=? AND tenant_id=? AND project_id=?",
            (sha256, tenant_id, project_id),
        )


def _is_restricted(store: Any, sha: str, tenant: str, project: str) -> str | None:
    """受限则返回 reason，否则 None。"""
    with store._lock:  # noqa: SLF001
        store._conn.execute(_CREATE_RESTRICTED)  # noqa: SLF001
        row = store._conn.execute(  # noqa: SLF001
            "SELECT reason FROM restricted_artifacts"
            " WHERE sha256=? AND tenant_id=? AND project_id=?",
            (sha, tenant, project),
        ).fetchone()
    return row[0] if row else None


async def check_evidence_access(
    store: Any, sha256: str, *,
    tenant_id: str, project_id: str,
) -> str:
    """检查访问权限（不取 blob）：allowed / denied / not_found。"""
    with store._lock:  # noqa: SLF001
        exists = store._conn.execute(  # noqa: SLF001
            "SELECT 1 FROM artifacts WHERE sha256=?", (sha256,)
        ).fetchone()
    if exists is None:
        return "not_found"
    if _is_restricted(store, sha256, tenant_id, project_id) is not None:
        return "denied"
    return "allowed"


async def get_artifact_checked(
    store: Any, sha256: str, *,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> bytes:
    """权限感知的 artifact 取回——受限即拒 + 审计事件。

    原始 get_artifact 不改（后向兼容层）；本函数是权限叠加层。
    作用域缺省即拒（AD-12 fail-closed——漏传作用域不得落到
    默认租户上判权限，否则限制可被无作用域调用绕过）。"""
    if not tenant_id or not project_id:
        raise VastaError(
            code="evidence.scope_required",
            message=(
                "权限检查需要显式 tenant_id/project_id"
                "（无作用域即拒——AD-12 fail-closed）"
            ),
        )
    effective_tenant = tenant_id
    effective_project = project_id

    # 不存在优先于受限（不存在的 sha 谈不上受限）
    with store._lock:  # noqa: SLF001
        exists = store._conn.execute(  # noqa: SLF001
            "SELECT 1 FROM artifacts WHERE sha256=?", (sha256,)
        ).fetchone()
    if exists is None:
        raise VastaError(
            code="artifact.not_found",
            message=f"artifact {sha256[:16]}… 不存在",
        )

    reason = _is_restricted(store, sha256, effective_tenant, effective_project)
    if reason is not None:
        # 权限判定落审计事件（FR-018）
        sequencer = EventSequencer(
            store, _ACCESS_RUN,
            tenant_id=effective_tenant, project_id=effective_project,
        )
        await sequencer.emit("artifact.access_denied", {
            "sha256": sha256,
            "reason": reason,
            "requested_by": f"{effective_tenant}:{effective_project}",
        })
        raise VastaError(
            code="evidence.access_denied",
            message=(
                f"原始证据 {sha256[:16]}… 受限"
                f"（reason={reason!r}）——派生物/血缘/检索不受影响；"
                "unrestrict_evidence 可解除"
            ),
        )

    return await store.get_artifact(
        sha256, tenant_id=tenant_id, project_id=project_id
    )


__all__ = ["check_evidence_access", "get_artifact_checked",
           "restrict_evidence", "unrestrict_evidence"]
