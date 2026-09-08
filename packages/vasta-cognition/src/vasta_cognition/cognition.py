"""认知资产：Claim 模型、记忆服务、冲突、失效传播、上下文装配。

Epic 5（FR-020~025，蓝图 §11）。挂接事件存储（claim.* 事件族）；
Policy 类记忆对 Agent 只读；被推翻的 Claim 不删除（改状态留影响链）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.envelope import EventEnvelope
from vasta_protocols.errors import VastaError

MemoryType = Literal[
    "working",
    "episodic",
    "fact",
    "hypothesis",
    "counterexample",
    "guide",
    "procedure",
    "preference",
    "policy",
]

ClaimStatus = Literal[
    "proposed", "supported", "accepted", "disputed", "refuted", "retired"
]

#: MVP 交付的四类（FR-020 后果：MVP 先交四类）。
MVP_MEMORY_TYPES: tuple[MemoryType, ...] = (
    "working",
    "hypothesis",
    "guide",
    "counterexample",
)


class Claim(BaseModel):
    """认知图节点（蓝图 §11.2）。"""

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1)
    memory_type: MemoryType
    statement: str = Field(min_length=1)
    scope: dict[str, str] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list, description="支持证据（sha/event seq）")
    counterevidence: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list, description="依赖主张 ID")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    status: ClaimStatus = "proposed"
    run_id: str | None = None


class CognitionService:
    """认知资产服务（挂接事件存储；当前状态为投影）。

    MVP 内存态投影 + 事件落库（claim.* 族）；Stage 3 持久化表。
    """

    def __init__(self, store: Any) -> None:  # SqliteStorage
        self.store = store
        self._claims: dict[str, Claim] = {}
        self._seq = -1
        self._last_event_id: str | None = None
        self._run_id = "cognition"
        self._tenant = "t-default"
        self._project = "p-default"
        # 恢复已有事件投影（AD-2：投影从事件流重建）
        self._rebuild()

    # ---- 事件层 ----
    def _rebuild(self) -> None:
        try:
            events = list(self.store.iter_run_events(self._run_id))
        except Exception:
            events = []
        for event in events:
            self._seq = max(self._seq, event.seq)
            self._last_event_id = event.event_id
            if event.type.startswith("claim."):
                self._apply_claim_event(event.type, event.payload)

    def _apply_claim_event(self, type_: str, payload: dict[str, Any]) -> None:
        claim_id = str(payload.get("claim_id", ""))
        if type_ == "claim.proposed":
            self._claims[claim_id] = Claim(
                claim_id=claim_id,
                memory_type=payload.get("memory_type", "working"),  # type: ignore[arg-type]
                statement=str(payload.get("statement", "")),
                scope=dict(payload.get("scope", {})),
                evidence=list(payload.get("evidence", [])),
                counterevidence=list(payload.get("counterevidence", [])),
                depends_on=list(payload.get("depends_on", [])),
                confidence=float(payload.get("confidence", 0.5)),
                run_id=payload.get("run_id"),
            )
        elif claim_id in self._claims:
            claim = self._claims[claim_id]
            if type_ == "claim.supported":
                claim.status = "supported"
                claim.evidence.extend(payload.get("evidence", []))
            elif type_ == "claim.accepted":
                claim.status = "accepted"
            elif type_ == "claim.disputed":
                claim.status = "disputed"
                claim.counterevidence.extend(payload.get("counterevidence", []))
            elif type_ == "claim.refuted":
                claim.status = "refuted"
                claim.counterevidence.extend(payload.get("counterevidence", []))
            elif type_ == "claim.retired":
                claim.status = "retired"

    async def _emit(self, type_: str, payload: dict[str, Any]) -> EventEnvelope:
        from vasta_protocols.ids import new_event_id, now_utc

        self._seq += 1
        envelope = EventEnvelope.model_validate(
            {
                "run_id": self._run_id,
                "seq": self._seq,
                "type": type_,
                "parent_event_id": self._last_event_id,
                "ts": now_utc(),
                "tenant_id": self._tenant,
                "project_id": self._project,
                "event_id": new_event_id(),
                "payload": payload,
            }
        )
        await self.store.append_event(envelope)
        self._last_event_id = envelope.event_id
        self._apply_claim_event(type_, payload)
        return envelope

    # ---- 公开 API ----
    async def propose(
        self,
        claim: Claim,
        *,
        evidence: list[str] | None = None,
    ) -> EventEnvelope:
        """创建主张（缺证据链路不得 accepted——FR-021 后果由状态机保证）。"""
        return await self._emit(
            "claim.proposed",
            {
                "claim_id": claim.claim_id,
                "memory_type": claim.memory_type,
                "statement": claim.statement,
                "scope": claim.scope,
                "evidence": evidence or claim.evidence,
                "counterevidence": claim.counterevidence,
                "depends_on": claim.depends_on,
                "confidence": claim.confidence,
                "run_id": claim.run_id,
            },
        )

    async def support(self, claim_id: str, evidence: list[str]) -> EventEnvelope:
        return await self._emit(
            "claim.supported", {"claim_id": claim_id, "evidence": evidence}
        )

    async def accept(self, claim_id: str) -> EventEnvelope:
        claim = self._claims.get(claim_id)
        if claim is None:
            raise VastaError(code="claim.not_found", message=claim_id)
        if not claim.evidence:
            raise VastaError(
                code="claim.no_evidence",
                message=f"主张 {claim_id!r} 缺证据链路，不得 accepted",
            )
        return await self._emit("claim.accepted", {"claim_id": claim_id})

    async def dispute(
        self, claim_id: str, counterevidence: list[str]
    ) -> EventEnvelope:
        return await self._emit(
            "claim.disputed",
            {"claim_id": claim_id, "counterevidence": counterevidence},
        )

    async def refute(
        self, claim_id: str, counterevidence: list[str]
    ) -> list[str]:
        """推翻主张（不删除）并做失效传播（Story 5.3）。

        返回受影响（级联 refuted）的主张 ID 清单。"""
        await self._emit(
            "claim.refuted",
            {"claim_id": claim_id, "counterevidence": counterevidence},
        )
        affected: list[str] = []
        # 失效传播：依赖该主张的其他主张级联 refuted（蓝图 §11.4）
        changed = True
        while changed:
            changed = False
            for other in self._claims.values():
                if other.claim_id == claim_id or other.status in (
                    "refuted", "retired"
                ):
                    continue
                if claim_id in other.depends_on or any(
                    d in affected for d in other.depends_on
                ):
                    await self._emit(
                        "claim.refuted",
                        {
                            "claim_id": other.claim_id,
                            "counterevidence": [],
                            "propagated_from": claim_id,
                        },
                    )
                    affected.append(other.claim_id)
                    changed = True
        return affected

    async def retire(self, claim_id: str) -> EventEnvelope:
        return await self._emit("claim.retired", {"claim_id": claim_id})

    # ---- 查询 ----
    def get(self, claim_id: str) -> Claim | None:
        return self._claims.get(claim_id)

    def list_by_type(self, memory_type: MemoryType) -> list[Claim]:
        return [c for c in self._claims.values() if c.memory_type == memory_type]

    def list_by_status(self, status: ClaimStatus) -> list[Claim]:
        return [c for c in self._claims.values() if c.status == status]


# ---- 显式冲突（Story 5.2）----

class Conflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conflict_id: str
    claim_ids: list[str] = Field(min_length=2)
    scope_key: str
    created_at: str = ""


class ConflictService:
    """同范围互斥主张 → 显式 Conflict（不静默覆盖）。"""

    def __init__(self) -> None:
        self.conflicts: dict[str, Conflict] = {}
        self._counter = 0

    def detect(
        self, claims: list[Claim], *, scope_key: str = "statement"
    ) -> Conflict | None:
        """同一 scope+scope_key 值下存在多条活跃主张 → 冲突。"""
        groups: dict[str, list[Claim]] = {}
        for claim in claims:
            if claim.status in ("refuted", "retired"):
                continue
            key = str(claim.scope.get(scope_key, claim.statement))
            groups.setdefault(key, []).append(claim)
        for key, group in groups.items():
            if len(group) >= 2:
                self._counter += 1
                conflict = Conflict(
                    conflict_id=f"conflict-{self._counter}",
                    claim_ids=[c.claim_id for c in group],
                    scope_key=key,
                )
                self.conflicts[conflict.conflict_id] = conflict
                return conflict
        return None

    def resolve(self, conflict_id: str, *, keep: str) -> Conflict:
        """解决冲突（保留一方，其余标 disputed 由调用方处理）。"""
        conflict = self.conflicts.get(conflict_id)
        if conflict is None:
            raise VastaError(code="conflict.not_found", message=conflict_id)
        if keep not in conflict.claim_ids:
            raise VastaError(
                code="conflict.bad_resolution",
                message=f"保留方 {keep!r} 不在冲突主张中",
            )
        return conflict


# ---- Context Builder（Story 5.4）----

class ContextSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    statement: str
    reason: str = Field(description="入选依据")


class ContextBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str
    selections: list[ContextSelection]
    budget: int = Field(ge=0)
    pruned: list[str] = Field(default_factory=list, description="被裁剪项（显式列出）")


class ContextBuilder:
    """按目标、相关性、风险与预算装配上下文（FR-025）。

    - 选择依据可追溯（每项带 reason）；
    - 超预算按优先级裁剪且显式列出被裁剪项（不静默截断）。"""

    #: 优先级（高→低）。
    PRIORITY_ORDER: tuple[str, ...] = ("policy", "guide", "fact", "procedure",
                                       "counterexample", "hypothesis", "working",
                                       "episodic", "preference")

    @classmethod
    def assemble(
        cls,
        *,
        goal: str,
        claims: list[Claim],
        budget: int,
        relevance_fn: Any = None,
    ) -> ContextBundle:
        relevance = relevance_fn or (lambda c: 1.0 if c.status == "accepted" else 0.5)
        def priority_index(memory_type: str) -> int:
            return cls.PRIORITY_ORDER.index(memory_type) if memory_type in cls.PRIORITY_ORDER else len(cls.PRIORITY_ORDER)

        ranked = sorted(
            claims,
            key=lambda c: (
                priority_index(c.memory_type),
                -relevance(c),
                -c.confidence,
            ),
        )
        selections: list[ContextSelection] = []
        pruned: list[str] = []
        for claim in ranked:
            if claim.status in ("refuted", "retired"):
                continue
            if len(selections) < budget:
                selections.append(
                    ContextSelection(
                        claim_id=claim.claim_id,
                        statement=claim.statement,
                        reason=(
                            f"type={claim.memory_type} status={claim.status} "
                            f"confidence={claim.confidence:.2f}"
                        ),
                    )
                )
            else:
                pruned.append(claim.claim_id)
        return ContextBundle(
            goal=goal, selections=selections, budget=budget, pruned=pruned
        )


__all__ = [
    "Claim",
    "ClaimStatus",
    "Conflict",
    "ConflictService",
    "ContextBuilder",
    "ContextBundle",
    "ContextSelection",
    "CognitionService",
    "MVP_MEMORY_TYPES",
    "MemoryType",
]
