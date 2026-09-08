"""Verifier 协议（蓝图 §18.1）。核验四态为固定枚举（约定 / FR-036）。"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from ..envelope import VerificationOutcome

#: Verifier 协议版本。
VERIFIER_PROTOCOL_VERSION = "0.1.0"


class VerifierManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    kind: str = Field(
        description="schema|read_back|invariant|visual_diff|temporal|semantic|cross_model|human"
    )


class Verification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: VerificationOutcome
    detail: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class Verifier(Protocol):
    """核验器端口。执行模型不得成为自己的唯一裁判（INV-06）。"""

    protocol_version: str
    manifest: VerifierManifest

    async def verify(
        self, contract_ref: str, evidence: dict[str, Any]
    ) -> Verification: ...
