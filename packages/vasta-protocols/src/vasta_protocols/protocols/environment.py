"""EnvironmentAdapter 协议（蓝图 §18.1）。

观察分五类（FR-005 / INV-04）：决策/过渡/终局/重置/外部——核验器与
回放不得把过渡帧或终局帧当作可行动状态。
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

#: Environment 协议版本（FR-001：协议携带版本字段）。
ENVIRONMENT_PROTOCOL_VERSION = "0.1.0"

ObservationKind = Literal["decision", "transition", "terminal", "reset", "external"]


class Observation(BaseModel):
    """一次环境观察。载荷本体是 Artifact 引用（哈希），不是内联大对象。"""

    model_config = ConfigDict(extra="forbid")

    kind: ObservationKind
    artifact_refs: list[str] = Field(default_factory=list, description="sha256 引用")
    available_actions: list[str] = Field(default_factory=list)
    detail: dict[str, Any] = Field(default_factory=dict)

    @property
    def actionable(self) -> bool:
        """只有决策帧是可行动状态（INV-04）。"""
        return self.kind == "decision"


class Action(BaseModel):
    """对环境/工具的动作请求。幂等键由 Tool Gateway 统一派生（AD-11）。"""

    model_config = ConfigDict(extra="forbid")

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class EnvironmentStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    running: bool
    detail: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class EnvironmentAdapter(Protocol):
    """环境端口。适配器实现本协议并注入 Runtime（AD-1：只被组装层引用）。"""

    protocol_version: str

    async def reset(self, seed: int | None = None) -> Observation: ...

    async def observe(self) -> Observation: ...

    async def execute(self, action: Action) -> list[Observation]: ...

    async def status(self) -> EnvironmentStatus: ...
