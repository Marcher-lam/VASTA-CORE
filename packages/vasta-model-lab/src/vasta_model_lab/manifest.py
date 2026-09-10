"""模型清单、最小协议与轻量观察（蓝图 §13.3，Story 6.1）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class WorldModelManifest(BaseModel):
    """模型清单（FR-043）：声明范围/假设/Unknown/覆盖/版本/依赖。

    unknowns / coverage 为必填且至少一项——「无未知」与「无覆盖」本身
    也是声明，空清单表示模型未做任何覆盖刻画，拒绝（评审修复）。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    scope: str = Field(min_length=1, description="适用环境/机制范围")
    assumptions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(min_length=1, description="显式未知项（必填）")
    coverage: list[str] = Field(min_length=1, description="覆盖的动作/观察（必填）")
    depends_on_claims: list[str] = Field(default_factory=list)
    state_schema: dict[str, str] = Field(default_factory=dict)


@dataclass
class Observation_:
    """轻量观察（模型实验室内部用，避免与 protocols Observation 混淆）。"""

    kind: str = "decision"
    detail: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return {"kind": self.kind, "detail": self.detail, "artifacts": self.artifacts}


@runtime_checkable
class PartialWorldModel(Protocol):
    """蓝图 §13.3 最小接口（FR-041：两种形态都实现它）。"""

    manifest: WorldModelManifest

    def init_state(self, observation: dict[str, Any]) -> dict[str, Any]: ...
    def transition(self, state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]: ...
    def observe(self, state: dict[str, Any]) -> dict[str, Any]: ...
    def outcome(self, state: dict[str, Any]) -> str: ...


