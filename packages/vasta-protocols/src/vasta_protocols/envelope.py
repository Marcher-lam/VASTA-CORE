"""事件信封 schema 与参考内存事件日志（AD-2 / AD-7）。

事件是追加式事实：Run 内单调序号 + 因果父项 + 类型；当前状态由投影重建。
13 族事件封闭集（约定）：run / observation / artifact / claim / memory /
plan / action / verification / world_model / evaluation / release / incident /
episode。新增族必须走 protocols minor 版本 + E0 变更评审。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .errors import DuplicateEventError, VastaError

#: 事件族封闭集（13 族，架构脊柱 Consistency Conventions）。
EVENT_FAMILIES: frozenset[str] = frozenset(
    {
        "run",
        "observation",
        "artifact",
        "claim",
        "memory",
        "plan",
        "action",
        "verification",
        "world_model",
        "evaluation",
        "release",
        "incident",
        "episode",
    }
)

#: 信封 schema 版本（FR-001：协议与 schema 均携带版本字段）。
ENVELOPE_SCHEMA_VERSION = "0.1.0"

#: 事件类型校验为"小写点分 + 13 族封闭集"语法形态；
#: past-tense 动词是**命名约定**（评审保证），不做形态学硬校验。
_EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


def _validate_event_type(value: str) -> str:
    if not _EVENT_TYPE_RE.match(value):
        raise ValueError(
            f"event type must be dot-delimited lowercase tokens, got {value!r}"
        )
    family = value.split(".", 1)[0]
    if family not in EVENT_FAMILIES:
        raise ValueError(
            f"event family {family!r} is outside the closed set of 13 families"
        )
    return value


class EventEnvelope(BaseModel):
    """追加式事件信封。

    字段（Story 1.1 AC）：run_id / seq / type / parent_event_id / ts /
    tenant_id / project_id；另携带 event_id（UUIDv7）与 schema_version。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    seq: int = Field(ge=0, description="Run 内单调序号，从 0 开始")
    type: str = Field(description="past-tense 点分事件类型，如 run.created")
    parent_event_id: str | None = Field(
        default=None, description="因果父项；Run 首事件为 None"
    )
    ts: datetime = Field(description="ISO8601 UTC 时间戳")
    tenant_id: str = Field(min_length=1, description="租户作用域键（AD-7）")
    project_id: str = Field(min_length=1, description="项目作用域键（AD-7）")
    event_id: str = Field(min_length=1, description="全局唯一事件 ID（UUIDv7）")
    schema_version: str = Field(default=ENVELOPE_SCHEMA_VERSION)
    trace_id: str | None = Field(
        default=None,
        description="NFR-010：分布式追踪关联（OTel 兼容——由 trace 上下文"
                    "自动注入；可选字段，schema 兼容性=可选新增非破坏）")
    payload: dict[str, object] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def _check_type(cls, value: str) -> str:
        return _validate_event_type(value)

    @field_validator("ts")
    @classmethod
    def _check_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("ts must carry tzinfo (ISO8601 UTC)")
        return value.astimezone(UTC)


class InMemoryEventLog:
    """参考实现：强制 (run_id, seq) 唯一（AD-2）+ event_id 全局唯一的
    追加式事件日志。

    存储 adapter（Story 1.4 SQLite）必须满足同一契约——由
    contract_suites.event_log.EventLogContractTests 驱动验证。
    Story 10.2 约束对齐：补 event_id 全局唯一模拟（此前缺失——
    G4-G6 评审 F1 的 seeded 接管撞号缺陷在 fake 面不可见即源于此；
    错误码与 sqlite 实现对齐：event_id 先查 → event.duplicate_id）。
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, int], EventEnvelope] = {}
        self._by_id: dict[str, EventEnvelope] = {}
        self._by_run: dict[str, list[EventEnvelope]] = {}

    def append(self, envelope: EventEnvelope) -> EventEnvelope:
        if envelope.event_id in self._by_id:
            raise VastaError(
                code="event.duplicate_id",
                message=f"event_id {envelope.event_id} already stored",
            )
        key = (envelope.run_id, envelope.seq)
        if key in self._by_key:
            raise DuplicateEventError(envelope.run_id, envelope.seq)
        self._by_key[key] = envelope
        self._by_id[envelope.event_id] = envelope
        self._by_run.setdefault(envelope.run_id, []).append(envelope)
        return envelope

    def get(self, run_id: str, seq: int) -> EventEnvelope:
        try:
            return self._by_key[(run_id, seq)]
        except KeyError as exc:
            raise VastaError(
                code="event.not_found",
                message=f"run {run_id} has no event at seq {seq}",
            ) from exc

    def iter_run(self, run_id: str) -> Iterator[EventEnvelope]:
        yield from self._by_run.get(run_id, [])

    def has(self, run_id: str, seq: int) -> bool:
        return (run_id, seq) in self._by_key


VerificationOutcome = Literal["pass", "deviation", "inconclusive", "system_error"]
