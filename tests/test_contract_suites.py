"""用假适配器驱动全部契约套件，证明套件本身可运行且判定有效。"""

from __future__ import annotations

from vasta_protocols.contract_suites import (
    EnvironmentAdapterContract,
    EventEnvelopeContract,
    EventLogContract,
    ModelAdapterContract,
    StorageAdapterContract,
    ToolAdapterContract,
    VerifierContract,
)
from vasta_protocols.envelope import InMemoryEventLog

from .fakes import (
    FakeEnvironmentAdapter,
    FakeModelAdapter,
    FakeStorageAdapter,
    FakeToolAdapter,
    FakeVerifier,
)


class TestEventEnvelopeSchema(EventEnvelopeContract):
    pass


class TestInMemoryEventLog(EventLogContract):
    def make_log(self) -> InMemoryEventLog:
        return InMemoryEventLog()


class TestFakeEnvironment(EnvironmentAdapterContract):
    def make_adapter(self):
        return FakeEnvironmentAdapter()


class TestFakeModel(ModelAdapterContract):
    def make_adapter(self):
        return FakeModelAdapter()


class TestFakeTool(ToolAdapterContract):
    def make_adapter(self):
        return FakeToolAdapter()


class TestFakeStorage(StorageAdapterContract):
    def make_adapter(self):
        return FakeStorageAdapter()


class TestFakeVerifier(VerifierContract):
    def make_verifier(self):
        return FakeVerifier()
