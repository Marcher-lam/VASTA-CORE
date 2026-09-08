"""ToolAdapter 协议（蓝图 §18.1）与工具清单（FR-032 数据形态）。

风险分级（蓝图 §12.4）：R0 只读 → R4 不可逆默认禁止。
工具清单未声明风险与幂等语义的工具不得被写动作调用（FR-032 后果）。
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from .environment import Action, Observation

#: Tool 协议版本。
TOOL_PROTOCOL_VERSION = "0.1.0"

RiskLevel = Literal["R0", "R1", "R2", "R3", "R4"]


class ToolManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    risk: RiskLevel
    read_only: bool
    idempotent: bool
    compensable: bool = False
    supports_dry_run: bool = False
    supports_read_back: bool = False
    permissions: list[str] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list, description="副作用边界描述")


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    replayed: bool = Field(default=False, description="幂等命中原结果（AD-11）")
    artifact_ref: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class DryRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason: str | None = None


class CompensationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    detail: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class ToolAdapter(Protocol):
    """工具端口。凭证只存在于 Tool Gateway（AD-4），适配器不得自持凭证。"""

    protocol_version: str
    manifest: ToolManifest

    async def dry_run(self, action: Action) -> DryRunResult: ...

    async def execute(self, action: Action, idempotency_key: str) -> ToolResult: ...

    async def read_back(self, action: Action) -> Observation: ...

    async def compensate(self, execution_detail: dict[str, Any]) -> CompensationResult: ...
