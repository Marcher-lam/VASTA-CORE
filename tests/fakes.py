"""契约套件驱动用假适配器（本目录测试专用，不入包）。"""

from __future__ import annotations

import hashlib

from vasta_protocols.envelope import EventEnvelope, InMemoryEventLog
from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import (
    ENVIRONMENT_PROTOCOL_VERSION,
    MODEL_PROTOCOL_VERSION,
    STORAGE_PROTOCOL_VERSION,
    TOOL_PROTOCOL_VERSION,
    VERIFIER_PROTOCOL_VERSION,
    Action,
    CompensationResult,
    DryRunResult,
    EnvironmentStatus,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    Observation,
    ToolManifest,
    ToolResult,
    Verification,
    VerifierManifest,
)


class FakeEnvironmentAdapter:
    protocol_version = ENVIRONMENT_PROTOCOL_VERSION

    async def reset(self, seed: int | None = None) -> Observation:
        return Observation(kind="decision", available_actions=["noop", "finish"])

    async def observe(self) -> Observation:
        return Observation(kind="decision", available_actions=["noop", "finish"])

    async def execute(self, action: Action) -> list[Observation]:
        return [
            Observation(kind="transition"),
            Observation(kind="decision", available_actions=["noop", "finish"]),
        ]

    async def status(self) -> EnvironmentStatus:
        return EnvironmentStatus(running=True)


class FakeModelAdapter:
    protocol_version = MODEL_PROTOCOL_VERSION
    capabilities = ModelCapabilities(context_window=128000)

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(content="pong")


class FakeToolAdapter:
    protocol_version = TOOL_PROTOCOL_VERSION
    manifest = ToolManifest(
        name="fake.echo",
        version="0.1.0",
        risk="R0",
        read_only=True,
        idempotent=True,
        supports_dry_run=True,
    )

    def __init__(self) -> None:
        self._executions: dict[str, ToolResult] = {}

    async def dry_run(self, action: Action) -> DryRunResult:
        return DryRunResult(allowed=True)

    async def execute(self, action: Action, idempotency_key: str) -> ToolResult:
        if idempotency_key in self._executions:
            return self._executions[idempotency_key].model_copy(update={"replayed": True})
        result = ToolResult(ok=True, detail={"echo": action.args})
        self._executions[idempotency_key] = result
        return result

    async def read_back(self, action: Action) -> Observation:
        return Observation(kind="external")

    async def compensate(self, execution_detail: dict) -> CompensationResult:
        return CompensationResult(ok=True)


class FakeStorageAdapter:
    protocol_version = STORAGE_PROTOCOL_VERSION

    def __init__(self) -> None:
        self.log = InMemoryEventLog()
        self._blobs: dict[str, bytes] = {}

    async def append_event(self, envelope: EventEnvelope) -> EventEnvelope:
        return self.log.append(envelope)

    async def get_event(self, run_id: str, seq: int) -> EventEnvelope:
        return self.log.get(run_id, seq)

    def iter_run_events(self, run_id: str):
        return self.log.iter_run(run_id)

    async def save_artifact(self, payload: bytes, **meta: object) -> str:
        sha = hashlib.sha256(payload).hexdigest()
        self._blobs[sha] = payload
        return sha

    async def get_artifact(self, sha256: str) -> bytes:
        if sha256 not in self._blobs:
            raise VastaError(code="artifact.not_found", message=sha256)
        return self._blobs[sha256]


class FakeVerifier:
    protocol_version = VERIFIER_PROTOCOL_VERSION
    manifest = VerifierManifest(name="fake.always_pass", version="0.1.0", kind="schema")

    async def verify(self, contract_ref: str, evidence: dict) -> Verification:
        return Verification(outcome="pass")
