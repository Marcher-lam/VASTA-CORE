"""版本回溯收口：as-of 查询（Story 8.7，FR-061，G4）。

- 记忆侧：`claim_as_of` 重放 claim.* 事件至指定 seq/ts 重建当时 Claim——
  真时间旅行（Claim 经事件演化，AD-2 事件为唯一事实源）；
- 派生物侧：`derived_recall` 回链收口——CAS 内容寻址天然不可变，"回到当时"
  即取回本体 + 血缘 + 源哈希校验（复用既有 verify_lineage 三态）；
- 两者均只读零副作用（守卫测试锚定）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_cognition import Claim
from vasta_protocols.errors import VastaError


class DerivedRecall(BaseModel):
    """派生物回链结果（verify_lineage 三态透传 + 本体取回）。"""

    model_config = ConfigDict(extra="forbid")

    derived_sha256: str
    source_sha256: str
    transform: str
    status: str = Field(description="verified | source_* | derived_*（三态族）")
    payload: bytes | None = Field(default=None, description="当时内容原样取回")


def _claim_events_up_to(
    store: Any, claim_id: str, *, as_of_seq: int | None, as_of_ts: datetime | None
) -> list[Any]:
    events = store.iter_run_events("cognition")
    selected = []
    seen_claim = False
    for event in events:
        if as_of_seq is not None and event.seq > as_of_seq:
            continue
        if as_of_ts is not None and event.ts > as_of_ts:
            continue
        if str(event.payload.get("claim_id", "")) != claim_id:
            continue
        if not event.type.startswith("claim."):
            continue
        selected.append(event)
        seen_claim = True
    if not seen_claim:
        point = f"seq={as_of_seq}" if as_of_seq is not None else f"ts={as_of_ts}"
        raise VastaError(
            code="claim.not_found_at",
            message=f"主张 {claim_id!r} 在 {point} 时点不存在（不取最新冒充当时）",
        )
    return selected


async def claim_as_of(
    store: Any,
    claim_id: str,
    *,
    as_of_seq: int | None = None,
    as_of_ts: datetime | None = None,
) -> Claim:
    """重放事件至指定点，重建当时的 Claim（含 version/证据链）。

    as_of_seq / as_of_ts 二选一（都给时取更严的交集语义：两条件都满足）。"""
    if as_of_seq is None and as_of_ts is None:
        raise VastaError(
            code="timetravel.missing_point",
            message="必须指定 as_of_seq 或 as_of_ts 之一",
        )
    events = _claim_events_up_to(
        store, claim_id, as_of_seq=as_of_seq, as_of_ts=as_of_ts
    )
    claim: Claim | None = None
    for event in events:
        payload = event.payload
        if event.type == "claim.proposed":
            claim = Claim.model_validate({
                "claim_id": claim_id,
                "memory_type": payload.get("memory_type", "working"),
                "statement": str(payload.get("statement", "")),
                "scope": dict(payload.get("scope", {})),
                "evidence": list(payload.get("evidence", [])),
                "counterevidence": list(payload.get("counterevidence", [])),
                "depends_on": list(payload.get("depends_on", [])),
                "confidence": float(payload.get("confidence", 0.5)),
                "version": int(payload.get("version", 1)),
                "run_id": payload.get("run_id"),
            })
        elif claim is not None:
            if event.type == "claim.supported":
                claim.status = "supported"
                claim.evidence.extend(payload.get("evidence", []))
            elif event.type == "claim.accepted":
                claim.status = "accepted"
            elif event.type == "claim.disputed":
                claim.status = "disputed"
                claim.counterevidence.extend(payload.get("counterevidence", []))
            elif event.type == "claim.refuted":
                claim.status = "refuted"
                claim.counterevidence.extend(payload.get("counterevidence", []))
            elif event.type == "claim.retired":
                claim.status = "retired"
            if event.type in (
                "claim.supported", "claim.accepted", "claim.disputed",
                "claim.refuted", "claim.retired",
            ):
                claim.version += 1  # 与 CognitionService 投影同构（评审修复）
    if claim is None:  # pragma: no cover——_claim_events_up_to 已保证非空
        raise VastaError(code="claim.not_found_at", message=claim_id)
    return claim


async def derived_recall(
    store: Any,
    derived_sha256: str,
    *,
    tenant_id: str = "t-default",
    project_id: str = "p-default",
) -> DerivedRecall:
    """派生物回链收口：血缘 + 校验三态 + 当时内容取回（只读）。"""
    rows = await store.lineage(
        derived_sha256, tenant_id=tenant_id, project_id=project_id
    )
    if not rows:
        raise VastaError(
            code="lineage.unknown_derived",
            message=f"派生物 {derived_sha256[:12]}… 无血缘记录",
        )
    verification = await store.verify_lineage(
        derived_sha256, tenant_id=tenant_id, project_id=project_id
    )
    derived_status = getattr(verification, "derived_status", "unknown")
    records = getattr(verification, "records", [])
    if derived_status == "ok" and all(
        getattr(r, "status", "") == "verified" for r in records
    ):
        status = "verified"
    else:
        status = next(
            (r.status for r in records if getattr(r, "status", "") != "verified"),
            derived_status,
        )
    payload: bytes | None = None
    with _swallow_not_found():
        payload = await store.get_artifact(
            derived_sha256, tenant_id=tenant_id, project_id=project_id
        )
    first = rows[0]
    return DerivedRecall(
        derived_sha256=derived_sha256,
        source_sha256=first.get("source_sha256", "")
        if isinstance(first, dict) else getattr(first, "source_sha256", ""),
        transform=first.get("transform", "")
        if isinstance(first, dict) else getattr(first, "transform", ""),
        status=str(status),
        payload=payload,
    )


class _swallow_not_found:
    """本体育缺失时置 None（三态已含 derived_missing），不掩盖其他错误。"""

    def __enter__(self) -> _swallow_not_found:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return exc_type is not None and issubclass(
            exc_type, VastaError
        ) and getattr(exc, "code", "") in {
            "artifact.unknown", "storage.unknown_artifact",
        }


__all__ = ["DerivedRecall", "claim_as_of", "derived_recall"]
