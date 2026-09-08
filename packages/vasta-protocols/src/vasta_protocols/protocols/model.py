"""ModelAdapter 协议（蓝图 §18.1）。"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

#: Model 协议版本。
MODEL_PROTOCOL_VERSION = "0.1.0"


class ModelCapabilities(BaseModel):
    """能力探测结果（FR-003 数据形态；探测本身在 Stage 2 实现）。"""

    model_config = ConfigDict(extra="forbid")

    vision: bool = False
    structured_output: bool = False
    tool_calling: bool = False
    streaming: bool = False
    context_window: int = Field(ge=0, default=0)
    detail: dict[str, Any] = Field(default_factory=dict)


class ModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str
    context: dict[str, Any] = Field(default_factory=dict)


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
    artifact_ref: str | None = Field(
        default=None, description="请求/响应整体落盘的 Artifact 哈希（AD-5）"
    )
    detail: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class ModelAdapter(Protocol):
    protocol_version: str
    capabilities: ModelCapabilities

    async def generate(self, request: ModelRequest) -> ModelResponse: ...
