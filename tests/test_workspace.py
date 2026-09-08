"""工作区完整性：十个 vasta-* 包可安装、可导入、带版本字段（AC 1）。"""

from __future__ import annotations

import vasta_adapters
import vasta_cognition
import vasta_contracts
import vasta_eval
import vasta_model_lab
import vasta_policy
import vasta_protocols
import vasta_runtime
import vasta_storage
import vastacore

PACKAGES = [
    ("vasta_protocols", vasta_protocols),
    ("vasta_storage", vasta_storage),
    ("vasta_cognition", vasta_cognition),
    ("vasta_contracts", vasta_contracts),
    ("vasta_policy", vasta_policy),
    ("vasta_runtime", vasta_runtime),
    ("vasta_model_lab", vasta_model_lab),
    ("vasta_eval", vasta_eval),
    ("vastacore", vastacore),
    ("vasta_adapters", vasta_adapters),
]


def test_ten_packages_importable_with_version() -> None:
    assert len(PACKAGES) == 10
    for name, module in PACKAGES:
        assert module.__version__ == "0.1.0", name


def test_protocols_surface() -> None:
    assert vasta_protocols.PROTOCOL_VERSION == "0.1.0"
    for proto_version in (
        vasta_protocols.MODEL_PROTOCOL_VERSION,
        vasta_protocols.ENVIRONMENT_PROTOCOL_VERSION,
        vasta_protocols.TOOL_PROTOCOL_VERSION,
        vasta_protocols.STORAGE_PROTOCOL_VERSION,
        vasta_protocols.VERIFIER_PROTOCOL_VERSION,
        vasta_protocols.ENVELOPE_SCHEMA_VERSION,
    ):
        assert proto_version == "0.1.0"


def test_runtime_checkable_protocol_instances() -> None:
    from vasta_protocols.protocols import (
        EnvironmentAdapter,
        ModelAdapter,
        StorageAdapter,
        ToolAdapter,
        Verifier,
    )

    from .fakes import (
        FakeEnvironmentAdapter,
        FakeModelAdapter,
        FakeStorageAdapter,
        FakeToolAdapter,
        FakeVerifier,
    )

    assert isinstance(FakeEnvironmentAdapter(), EnvironmentAdapter)
    assert isinstance(FakeModelAdapter(), ModelAdapter)
    assert isinstance(FakeToolAdapter(), ToolAdapter)
    assert isinstance(FakeStorageAdapter(), StorageAdapter)
    assert isinstance(FakeVerifier(), Verifier)


def test_no_intra_repo_imports_in_protocols_source() -> None:
    """AD-1 的测试级冗余校验（正式校验由 import-linter 承担）。"""
    import pathlib

    src = pathlib.Path(vasta_protocols.__file__).parent
    banned = {name for name, _ in PACKAGES if name != "vasta_protocols"}
    for py in src.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for pkg in banned:
            assert f"import {pkg}" not in text, f"{py} imports {pkg}"
            assert f"from {pkg}" not in text, f"{py} imports {pkg}"
