"""认知资产：Claim 模型、记忆服务、冲突、失效传播、上下文装配。

Epic 5（FR-020~025，蓝图 §11）。挂接事件存储（claim.* 事件族）；
Policy 类记忆对 Agent 只读；被推翻的 Claim 不删除（改状态留影响链）。

评审修复（Epic 4-7 code-review）：
- seq 分配每次发射前与存储同步——与 world_model 桥接共用 "cognition"
  run 时不再撞 DuplicateEventError（两个分配器冲突实锤）；
- support/dispute/refute/retire 校验主张存在且非终态；重复 propose 拒绝；
- Claim 增加 version（FR-021：状态变更版本化）；
- refute 级联可穿透「已推翻」中间节点（visited 防环），retired 不穿透；
- 冲突检测幂等、走 propose 路径自动触发并落事件，resolve 落事件；
- ContextBuilder 补风险维度与目标相关默认函数，reason 记录依据数值。
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.envelope import EventEnvelope
from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

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

#: 终态：不可再发生状态迁移（评审修复：原实现可复活已推翻主张）。
_TERMINAL_STATUSES: tuple[ClaimStatus, ...] = ("refuted", "retired")

#: MVP 交付的四类（FR-020 后果：MVP 先交四类）。
MVP_MEMORY_TYPES: tuple[MemoryType, ...] = (
    "working",
    "hypothesis",
    "guide",
    "counterexample",
)


class Claim(BaseModel):
    """认知图节点（蓝图 §11.2）。version 随状态迁移递增（FR-021）。"""

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
    version: int = Field(default=1, ge=1, description="状态版本（迁移即 +1）")
    run_id: str | None = None


class CognitionService:
    """认知资产服务（挂接事件存储；当前状态为投影）。

    MVP 内存态投影 + 事件落库（claim.* 族）；Stage 3 持久化表。
    同一 "cognition" run 可能被 world_model 桥接（AD-13）并发写入——
    每次发射前从存储同步 seq/parent（全量扫描，MVP 规模可接受）。"""

    def __init__(
        self,
        store: Any,  # SqliteStorage
        *,
        tenant_id: str = "t-default",
        project_id: str = "p-default",
    ) -> None:
        self.store = store
        self._claims: dict[str, Claim] = {}
        self._run_id = "cognition"
        self._tenant = tenant_id
        self._project = project_id
        # 统一序列器（Story 9.1）：系统流模式（每发全量同步——桥接并发安全）
        self._sequencer = EventSequencer(
            store, self._run_id,
            tenant_id=tenant_id, project_id=project_id,
        )
        self._known_conflicts: set[frozenset[str]] = set()
        # 恢复已有事件投影（AD-2：投影从事件流重建）
        self._rebuild()

    # ---- 事件层 ----
    def _rebuild(self) -> None:
        try:
            events = list(self.store.iter_run_events(self._run_id))
        except Exception:
            events = []
        # 统一序列器（系统流模式）每发全量同步——重放恢复无需手动对齐游标
        for event in events:
            if event.type.startswith("claim."):
                self._apply_claim_event(event.type, event.payload)

    def _sync_from_store(self) -> None:
        """与存储对齐——桥接（AD-13）可能已在本 run 追加事件。

        统一序列器（Story 9.1）：同步策略收敛进 EventSequencer（系统流模式）。"""
        self._sequencer._sync_from_store()  # noqa: SLF001——同对象内部状态对齐

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
                version=int(payload.get("version", 1)),
                run_id=payload.get("run_id"),
            )
        elif claim_id in self._claims:
            claim = self._claims[claim_id]
            if type_ == "claim.supported":
                claim.status = "supported"
                claim.evidence.extend(payload.get("evidence", []))
                claim.version += 1
            elif type_ == "claim.accepted":
                claim.status = "accepted"
                claim.version += 1
            elif type_ == "claim.disputed":
                claim.status = "disputed"
                claim.counterevidence.extend(payload.get("counterevidence", []))
                claim.version += 1
            elif type_ == "claim.refuted":
                claim.status = "refuted"
                claim.counterevidence.extend(payload.get("counterevidence", []))
                claim.version += 1
            elif type_ == "claim.retired":
                claim.status = "retired"
                claim.version += 1

    async def _emit(self, type_: str, payload: dict[str, Any]) -> EventEnvelope:
        envelope = await self._sequencer.emit(type_, payload)
        self._apply_claim_event(type_, payload)
        return envelope

    def _require_active(self, claim_id: str) -> Claim:
        """存在且非终态（评审修复：原实现对不存在/已推翻主张静默发事件）。"""
        claim = self._claims.get(claim_id)
        if claim is None:
            raise VastaError(code="claim.not_found", message=claim_id)
        if claim.status in _TERMINAL_STATUSES:
            raise VastaError(
                code="claim.terminal",
                message=f"主张 {claim_id!r} 已处终态 {claim.status}，拒绝迁移",
            )
        return claim

    # ---- 公开 API ----
    async def propose(
        self,
        claim: Claim,
        *,
        evidence: list[str] | None = None,
    ) -> EventEnvelope:
        """创建主张（缺证据链路不得 accepted——FR-021 后果由状态机保证）。

        评审修复：claim_id 已存在 → 拒绝（原先静默覆盖投影）；
        同范围出现第二条活跃主张 → 自动落 claim.conflict_detected。"""
        if claim.claim_id in self._claims:
            raise VastaError(
                code="claim.duplicate",
                message=f"主张 {claim.claim_id!r} 已存在（事件溯源不覆盖，"
                        "如需重提请先 retire 再用新 ID）",
            )
        envelope = await self._emit(
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
                "version": 1,
                "run_id": claim.run_id,
            },
        )
        conflict = self._detect_conflict_inline()
        if conflict is not None:
            await self._emit(
                "claim.conflict_detected",
                {
                    "claim_ids": conflict.claim_ids,
                    "scope_key": conflict.scope_key,
                    "triggered_by": claim.claim_id,
                },
            )
        return envelope

    def _detect_conflict_inline(self) -> Conflict | None:
        """propose 路径的自动冲突检测（幂等：同主张集合只报一次）。"""
        active = [c for c in self._claims.values() if c.status not in _TERMINAL_STATUSES]
        groups: dict[str, list[Claim]] = {}
        for claim in active:
            if not claim.scope:
                continue  # 未声明范围 → 不参与互斥判定
            key = json.dumps(claim.scope, sort_keys=True, ensure_ascii=False)
            groups.setdefault(key, []).append(claim)
        for key, group in groups.items():
            if len(group) >= 2:
                members = frozenset(c.claim_id for c in group)
                if members in self._known_conflicts:
                    return None  # 幂等：已报过的组合不重复报
                self._known_conflicts.add(members)
                return Conflict(
                    conflict_id=f"conflict-{len(self._known_conflicts)}",
                    claim_ids=[c.claim_id for c in group],
                    scope_key=key,
                )
        return None

    async def support(self, claim_id: str, evidence: list[str]) -> EventEnvelope:
        self._require_active(claim_id)
        return await self._emit(
            "claim.supported", {"claim_id": claim_id, "evidence": evidence}
        )

    async def accept(self, claim_id: str) -> EventEnvelope:
        claim = self._require_active(claim_id)
        if not claim.evidence:
            raise VastaError(
                code="claim.no_evidence",
                message=f"主张 {claim_id!r} 缺证据链路，不得 accepted",
            )
        return await self._emit("claim.accepted", {"claim_id": claim_id})

    async def dispute(
        self, claim_id: str, counterevidence: list[str]
    ) -> EventEnvelope:
        self._require_active(claim_id)
        return await self._emit(
            "claim.disputed",
            {"claim_id": claim_id, "counterevidence": counterevidence},
        )

    async def refute(
        self, claim_id: str, counterevidence: list[str]
    ) -> list[str]:
        """推翻主张（不删除）并做失效传播（Story 5.3）。

        返回受影响（级联 refuted）的主张 ID 清单。评审修复：传播按
        依赖闭包遍历——可穿透「已推翻」中间节点（其下游仍需失效），
        visited 集防环；retired 节点不穿透（退役主张的下游已被显式处理）。"""
        self._require_active(claim_id)
        await self._emit(
            "claim.refuted",
            {"claim_id": claim_id, "counterevidence": counterevidence},
        )
        affected: list[str] = []
        visited: set[str] = {claim_id}
        frontier: list[str] = [claim_id]
        while frontier:
            current = frontier.pop()
            for other in self._claims.values():
                if other.claim_id in visited:
                    continue
                if current not in other.depends_on:
                    continue
                visited.add(other.claim_id)
                if other.status == "retired":
                    continue  # 不穿透退役节点
                frontier.append(other.claim_id)
                if other.status != "refuted":
                    await self._emit(
                        "claim.refuted",
                        {
                            "claim_id": other.claim_id,
                            "counterevidence": [],
                            "propagated_from": claim_id,
                        },
                    )
                    affected.append(other.claim_id)
                # 已 refuted 的中间节点：不发重复事件，但继续穿透其下游
        return affected

    async def retire(self, claim_id: str) -> EventEnvelope:
        self._require_active(claim_id)
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
    resolved: bool = Field(default=False, description="评审修复：解决状态可查")
    kept: str | None = Field(default=None, description="解决时保留的主张 ID")


class ConflictService:
    """同范围互斥主张 → 显式 Conflict（不静默覆盖）。

    评审修复：
    - detect 幂等（同一主张集合不重复建冲突）；
    - resolve 落 claim.conflict_resolved 事件（挂存储时）并标记状态；
    - 默认按完整 scope 分组——原 ``scope_key="statement"`` 下键取
      ``scope.get("statement", statement)``，几乎不可能产生分组。"""

    def __init__(self, store: Any | None = None) -> None:
        self.conflicts: dict[str, Conflict] = {}
        self._counter = 0
        self._known_sets: set[frozenset[str]] = set()
        self._store = store

    def detect(
        self, claims: list[Claim], *, scope_key: str | None = None
    ) -> Conflict | None:
        """同一（非空）scope 下存在多条活跃主张 → 冲突。

        scope_key：显式指定时只按该字段分组；None（默认）按完整 scope。"""
        groups: dict[str, list[Claim]] = {}
        for claim in claims:
            if claim.status in _TERMINAL_STATUSES:
                continue
            if scope_key is not None:
                if scope_key not in claim.scope:
                    continue
                key = str(claim.scope[scope_key])
            else:
                if not claim.scope:
                    continue
                key = json.dumps(claim.scope, sort_keys=True, ensure_ascii=False)
            groups.setdefault(key, []).append(claim)
        for key, group in groups.items():
            if len(group) >= 2:
                members = frozenset(c.claim_id for c in group)
                if members in self._known_sets:
                    continue  # 幂等：同一组合已有冲突记录
                self._known_sets.add(members)
                self._counter += 1
                conflict = Conflict(
                    conflict_id=f"conflict-{self._counter}",
                    claim_ids=[c.claim_id for c in group],
                    scope_key=key,
                )
                self.conflicts[conflict.conflict_id] = conflict
                return conflict
        return None

    async def resolve(self, conflict_id: str, *, keep: str) -> Conflict:
        """解决冲突（保留一方，其余标 disputed 由调用方处理）。

        评审修复：标记 resolved/kept 并（挂存储时）落 claim.conflict_resolved。"""
        conflict = self.conflicts.get(conflict_id)
        if conflict is None:
            raise VastaError(code="conflict.not_found", message=conflict_id)
        if conflict.resolved:
            raise VastaError(
                code="conflict.already_resolved",
                message=f"冲突 {conflict_id!r} 已解决（kept={conflict.kept!r}）",
            )
        if keep not in conflict.claim_ids:
            raise VastaError(
                code="conflict.bad_resolution",
                message=f"保留方 {keep!r} 不在冲突主张中",
            )
        conflict.resolved = True
        conflict.kept = keep
        if self._store is not None:
            # 统一序列器（Story 9.1）：系统流模式（原为第六处手工构造）
            await EventSequencer(self._store, "cognition").emit(
                "claim.conflict_resolved",
                {
                    "conflict_id": conflict_id,
                    "claim_ids": conflict.claim_ids,
                    "kept": keep,
                },
            )
        return conflict


# ---- Context Builder（Story 5.4）----

class ContextSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    statement: str
    reason: str = Field(description="入选依据（含相关性与风险数值）")
    relevance: float = Field(default=0.0, ge=0.0, description="目标相关性")
    risk: int = Field(default=0, ge=0, description="风险分（反证计数+争议态）")


class ContextBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str
    selections: list[ContextSelection]
    budget: int = Field(ge=0)
    pruned: list[str] = Field(default_factory=list, description="被裁剪项（显式列出）")


def _default_relevance(goal: str) -> Any:
    """目标感知默认相关性：goal 与 statement 的词元重合率 + 状态加成。

    评审修复：原默认只看 status，goal 完全不参与排序。"""
    goal_tokens = {t for t in goal.split() if len(t) >= 2}

    def relevance(claim: Claim) -> float:
        tokens = {t for t in claim.statement.split() if len(t) >= 2}
        overlap = len(goal_tokens & tokens) / len(goal_tokens) if goal_tokens else 0.0
        status_bonus = 0.5 if claim.status == "accepted" else 0.2
        return min(1.0, overlap + status_bonus * 0.5)

    return relevance


def claim_risk(claim: Claim) -> int:
    """风险分：反证条数 +（争议态 +2）（评审修复：补 FR-025 风险维度）。"""
    return len(claim.counterevidence) + (2 if claim.status == "disputed" else 0)


class ContextBuilder:
    """按目标、相关性、风险与预算装配上下文（FR-025）。

    - 选择依据可追溯（每项带 reason + relevance/risk 数值）；
    - 排序键含目标相关性（默认目标感知函数）与风险降序；
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
        relevance = relevance_fn or _default_relevance(goal)
        def priority_index(memory_type: str) -> int:
            return (
                cls.PRIORITY_ORDER.index(memory_type)
                if memory_type in cls.PRIORITY_ORDER
                else len(cls.PRIORITY_ORDER)
            )

        ranked = sorted(
            claims,
            key=lambda c: (
                priority_index(c.memory_type),
                -relevance(c),
                -claim_risk(c),
                -c.confidence,
            ),
        )
        selections: list[ContextSelection] = []
        pruned: list[str] = []
        for claim in ranked:
            if claim.status in _TERMINAL_STATUSES:
                continue
            if len(selections) < budget:
                rel = float(relevance(claim))
                risk = claim_risk(claim)
                selections.append(
                    ContextSelection(
                        claim_id=claim.claim_id,
                        statement=claim.statement,
                        reason=(
                            f"type={claim.memory_type} status={claim.status} "
                            f"confidence={claim.confidence:.2f} "
                            f"relevance={rel:.2f} risk={risk}"
                        ),
                        relevance=rel,
                        risk=risk,
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
    "claim_risk",
]
