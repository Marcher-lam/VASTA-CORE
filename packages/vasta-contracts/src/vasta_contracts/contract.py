"""ActionContract 模型与六段链审计（FR-030/031，Story 3.1）。

- 必填段（FR-031）：前置 / 预期变化 / 不变量 / 成功条件 / 失败条件 /
  核验器 / 超时——None **或空**均算缺段（写动作的契约必须实质存在）；
- 幂等键与补偿为预留可选字段（AD-11/FR-038，Stage 3 激活）；
- audit_six_segment：对事件流中的每条 action.contracted 分类
  complete / rejected / incomplete——NFR-001（AC-02）的可复用断言工具。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.envelope import EventEnvelope
from vasta_protocols.errors import VastaError

#: FR-031 必填段（缺任一即拒）。
REQUIRED_SEGMENTS: tuple[str, ...] = (
    "preconditions",
    "prediction.changes",
    "prediction.invariants",
    "success_criteria",
    "failure_criteria",
    "verify_with",
    "timeout_ms",
)


class ContractIncompleteError(VastaError):
    def __init__(self, missing: list[str]) -> None:
        super().__init__(
            code="contract.incomplete",
            message=f"契约缺必填段: {missing}；写动作不执行",
            retryable=False,
        )
        self.missing = missing


class Prediction(BaseModel):
    """预期：会变什么 & 什么必须不变。"""

    model_config = ConfigDict(extra="forbid")

    changes: list[str] = Field(
        default_factory=list, description="预期变化（如 A102.status=approved）"
    )
    invariants: list[str] = Field(default_factory=list, description="不变量（如 amount unchanged）")


class ActionContract(BaseModel):
    """行动契约（蓝图 §12.1）。"""

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)
    goal: str | None = Field(default=None, description="本次动作的业务目标")
    risk: Literal["R0", "R1", "R2", "R3", "R4"]
    preconditions: list[str] | None = None
    prediction: Prediction | None = None
    success_criteria: list[str] | None = None
    failure_criteria: list[str] | None = None
    verify_with: list[str] | None = None
    timeout_ms: int | None = Field(default=None)  # 非正数由 missing_segments 判缺
    # 预留（AD-11 / FR-038，Stage 3 激活）
    idempotency_key: str | None = None
    compensation: str | None = None


def missing_segments(contract: ActionContract) -> list[str]:
    """缺段检测（纯函数）：None 或空集合均算缺；超时须为正。"""
    missing: list[str] = []
    if not contract.preconditions:
        missing.append("preconditions")
    prediction = contract.prediction or Prediction()
    if not prediction.changes:
        missing.append("prediction.changes")
    if not prediction.invariants:
        missing.append("prediction.invariants")
    if not contract.success_criteria:
        missing.append("success_criteria")
    if not contract.failure_criteria:
        missing.append("failure_criteria")
    if not contract.verify_with:
        missing.append("verify_with")
    if contract.timeout_ms is None or contract.timeout_ms <= 0:
        missing.append("timeout_ms")
    return missing


def make_complete_contract(
    *, tool: str = "set_status", risk: str = "R2", **overrides: Any
) -> ActionContract:
    """测试/引导用完整契约工厂（全部必填段就位）。"""
    fields: dict[str, Any] = dict(
        tool=tool,
        args={"id": "A102", "status": "approved"},
        goal="批准已核验订单",
        risk=risk,  # type: ignore[arg-type]
        preconditions=["status=pending", "amount and currency verified"],
        prediction=Prediction(
            changes=["A102.status=approved"],
            invariants=["amount unchanged", "other orders unchanged"],
        ),
        success_criteria=["write accepted", "read-back status=approved"],
        failure_criteria=["duplicate side effect", "unexpected dialog"],
        verify_with=["read_back"],
        timeout_ms=10_000,
    )
    fields.update(overrides)
    return ActionContract.model_validate(fields)


# ---- 六段链审计（NFR-001 / AC-02）----

_SEGMENT_ORDER = ("before", "contract", "policy", "execution", "after", "verification")


class ChainReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contracted_seq: int
    tool: str
    status: Literal["complete", "rejected", "pending", "failed", "incomplete"]
    missing: list[str] = Field(default_factory=list)


class SixSegmentAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chains: list[ChainReport]

    @property
    def total(self) -> int:
        return len(self.chains)

    @property
    def complete(self) -> int:
        return sum(1 for c in self.chains if c.status == "complete")

    @property
    def rejected(self) -> int:
        return sum(1 for c in self.chains if c.status == "rejected")

    @property
    def all_success_paths_complete(self) -> bool:
        """NFR-001：所有链处于合法终态/挂起态（complete/rejected/pending/failed）。

        failed = 执行异常/超时/预算——已妥善失败的链不算缺段（评审修复）。"""
        return all(
            c.status in {"complete", "rejected", "pending", "failed"}
            for c in self.chains
        )


def audit_six_segment(events: list[EventEnvelope]) -> SixSegmentAudit:
    """对事件流中每条 action.contracted 审计六段链。

    - rejected：出现 action.policy_denied（契约期或策略期拒）——合法终态；
    - complete：before / contract / policy_cleared / execution / after /
      verification 六段全部出现；
    - incomplete：成功路径缺段（NFR-001 违反）。
    """
    reports: list[ChainReport] = []
    for index, event in enumerate(events):
        if event.type != "action.contracted":
            continue
        missing: list[str] = []
        # before：契约事件之前存在观察
        if not any(e.type.startswith("observation.") for e in events[:index]):
            missing.append("before")
        # 链作用域：到下一条 action.contracted 或流尾（评审修复：消魔法窗口
        # 与跨链污染）
        after_events = events[index + 1 :]
        scope_end = next(
            (i for i, e in enumerate(after_events) if e.type == "action.contracted"),
            len(after_events),
        )
        scope = after_events[:scope_end]
        denied = any(e.type == "action.policy_denied" for e in scope)
        if denied:
            reports.append(
                ChainReport(
                    contracted_seq=event.seq,
                    tool=str(event.payload.get("tool", "")),
                    status="rejected",
                )
            )
            continue
        # 失败终态：action.failed / run.failed（超时/异常/预算）——合法
        failed = any(e.type in ("action.failed", "run.failed") for e in scope)
        # 等待人工批准（未执行也未拒）——合法挂起态
        awaiting = any(e.type == "action.approval_requested" for e in scope)
        has_resolution = any(
            e.type in ("action.approved", "action.executed") for e in scope
        )
        if awaiting and not has_resolution:
            reports.append(
                ChainReport(
                    contracted_seq=event.seq,
                    tool=str(event.payload.get("tool", "")),
                    status="pending",
                )
            )
            continue
        if not any(
            e.type in ("action.policy_cleared", "action.approved") for e in scope
        ):
            missing.append("policy")
        executed = [e for e in scope if e.type == "action.executed"]
        if not executed:
            if failed:
                reports.append(
                    ChainReport(
                        contracted_seq=event.seq,
                        tool=str(event.payload.get("tool", "")),
                        status="failed",
                    )
                )
                continue
            missing.append("execution")
        exec_index = after_events.index(executed[0]) if executed else len(after_events)
        tail = after_events[exec_index:] if executed else []
        if executed and not any(
            e.type.startswith("observation.") for e in tail[1:]
        ):
            missing.append("after")
        if executed and not any(
            e.type.startswith("verification.") for e in tail[1:]
        ):
            missing.append("verification")
        reports.append(
            ChainReport(
                contracted_seq=event.seq,
                tool=str(event.payload.get("tool", "")),
                status="complete" if not missing else "incomplete",
                missing=missing,
            )
        )
    return SixSegmentAudit(chains=reports)


__all__ = [
    "ActionContract",
    "ChainReport",
    "ContractIncompleteError",
    "Prediction",
    "REQUIRED_SEGMENTS",
    "SixSegmentAudit",
    "audit_six_segment",
    "make_complete_contract",
    "missing_segments",
]
