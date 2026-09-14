"""Story 12.9：证据签名与第三方独立验证（FR-019，G4）。"""

from __future__ import annotations

import hashlib

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.ecosystem.evidence_signing import (
    record_verification,
    sign_evidence_set,
    verification_manifest,
    verify_evidence_set,
)
from vastacore.governance.rbac import Principal, Role


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


KEY = b"third-party-key"


def key_resolver(key_id: str) -> bytes:
    return KEY


def operator() -> Principal:
    return Principal(user="op", role=Role.OPERATOR,
                     tenant_id="t", project_id="p")


def viewer() -> Principal:
    return Principal(user="v", role=Role.VIEWER,
                     tenant_id="t", project_id="p")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


HASHES = [sha(b"evidence-1"), sha(b"evidence-2"), sha(b"evidence-1")]


class TestSigning:
    def test_sign_canonical_dedup_sorted(self) -> None:
        """签名覆盖排序去重集——顺序/重复不影响规范形。"""
        signed = sign_evidence_set(HASHES, key_id="k1", key=KEY)
        assert signed.hashes == sorted(set(HASHES))
        again = sign_evidence_set(list(reversed(HASHES)), key_id="k1",
                                  key=KEY)
        assert again.signature == signed.signature

    def test_empty_set_rejected(self) -> None:
        with pytest.raises(VastaError):
            sign_evidence_set([], key_id="k1", key=KEY)

    def test_manifest_carries_no_payload(self) -> None:
        """AC：第三方清单不含租户数据——仅哈希+签名+密钥标识。"""
        signed = sign_evidence_set(HASHES, key_id="k1", key=KEY)
        manifest = verification_manifest(signed)
        assert set(manifest) == {"hashes", "signature", "key_id",
                                 "algorithm"}
        dumped = str(manifest)
        assert "evidence-1" not in dumped  # 原始证据字节不出域


class TestIndependentVerification:
    def test_third_party_verifies_own_hashes(self) -> None:
        """AC：第三方独立复算——对同集哈希重算比对签名通过。"""
        signed = sign_evidence_set(HASHES, key_id="k1", key=KEY)
        # 第三方从收到的证据字节自行复算哈希
        recomputed = [sha(b"evidence-2"), sha(b"evidence-1")]
        assert verify_evidence_set(signed, provided_hashes=recomputed,
                                   key_resolver=key_resolver)

    def test_missing_evidence_fails(self) -> None:
        """AC：证据缺漏检出——第三方集 ≠ 签名覆盖集即不通过。"""
        signed = sign_evidence_set(HASHES, key_id="k1", key=KEY)
        assert not verify_evidence_set(
            signed, provided_hashes=[sha(b"evidence-1")],
            key_resolver=key_resolver)

    def test_tampered_hash_fails(self) -> None:
        signed = sign_evidence_set(HASHES, key_id="k1", key=KEY)
        forged = [sha(b"tampered"), sha(b"evidence-1")]
        assert not verify_evidence_set(signed, provided_hashes=forged,
                                       key_resolver=key_resolver)

    def test_tampered_signature_rejected(self) -> None:
        signed = sign_evidence_set(HASHES, key_id="k1", key=KEY)
        tampered = signed.model_copy(
            update={"signature": "0" * 64})
        assert not verify_evidence_set(tampered, provided_hashes=HASHES,
                                       key_resolver=key_resolver)


class TestRecordReceipt:
    async def test_receipt_traced_verification_family(
            self, store) -> None:
        """AC：验证结果留痕（verification 族事件）。"""
        signed = sign_evidence_set(HASHES, key_id="k1", key=KEY)
        await record_verification(store, signed, True,
                                  principal=operator(),
                                  verifier="auditor-ext")
        events = [e for e in store.iter_run_events("evaluation")
                  if e.type == "verification.passed"]
        assert events[-1].payload["verifier"] == "auditor-ext"
        assert events[-1].payload["hash_count"] == len(set(HASHES))

    async def test_failed_verification_deviated(self, store) -> None:
        signed = sign_evidence_set(HASHES, key_id="k1", key=KEY)
        await record_verification(store, signed, False,
                                  principal=operator(),
                                  verifier="auditor-ext")
        types = [e.type for e in store.iter_run_events("evaluation")]
        assert "verification.deviated" in types

    async def test_viewer_cannot_record(self, store) -> None:
        signed = sign_evidence_set(HASHES, key_id="k1", key=KEY)
        with pytest.raises(VastaError) as e:
            await record_verification(store, signed, True,
                                      principal=viewer(),
                                      verifier="x")
        assert e.value.code == "access.denied"


class TestCatalogClosedLoop:
    def test_verification_events_in_catalog(self) -> None:
        """verification.passed/deviated 已在册（既有）——本 Story
        复用该族，目录零漂移由守卫锚定。"""
        from vasta_protocols.schema_registry import _EVENT_CATALOG

        assert {"passed", "deviated"} <= _EVENT_CATALOG["verification"]
