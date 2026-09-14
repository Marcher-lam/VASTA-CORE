"""证据签名与第三方独立验证（Story 12.9，FR-019，G4）。

不接触租户数据也能验证证据链完整性：

- **sign_evidence_set**：对证据哈希集签名（排序去重 → 规范形 →
  HMAC-SHA256——内容寻址：签名可独立复算，无需原始证据字节）；
- **verification_manifest**：导出第三方验证清单——仅哈希集 + 签名
  + 密钥标识（**不含任何证据 payload**——租户数据不出域）；
- **verify_evidence_set**：第三方独立验证（纯函数——无 store：对
  手中哈希集重算规范形并比对签名）；
- **record_verification**：验证结果回执留痕（``verification.passed``
  / ``verification.deviated``——verification 族）。
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

from ..governance.rbac import Principal
from .manifest import SIGNATURE_ALGORITHM, KeyResolver

_VERIFICATION_RUN = "evaluation"


class EvidenceSetSignature(BaseModel):
    """证据集签名（内容寻址——第三方可独立复算）。"""

    model_config = ConfigDict(extra="forbid")

    hashes: list[str] = Field(min_length=1,
                              description="证据 sha256 集（排序去重）")
    signature: str = Field(min_length=64)
    key_id: str = Field(min_length=1)
    algorithm: str = Field(default=SIGNATURE_ALGORITHM)


def canonical_hash_set(hashes: list[str]) -> bytes:
    """证据哈希集规范形：排序去重后换行连接。"""
    return "\n".join(sorted(set(hashes))).encode()


def sign_evidence_set(
    hashes: list[str], *, key_id: str, key: bytes,
) -> EvidenceSetSignature:
    """证据方签名：HMAC-SHA256(哈希集规范形, key)。"""
    if not hashes:
        raise VastaError(
            code="evidence.empty_set",
            message="证据集不可为空（空集签名无意义）",
        )
    if not key:
        raise VastaError(
            code="evidence.empty_signing_key",
            message="签名密钥不可为空（BYOK 注入面）",
        )
    signature = hmac.new(key, canonical_hash_set(hashes),
                         hashlib.sha256).hexdigest()
    return EvidenceSetSignature(hashes=sorted(set(hashes)),
                                signature=signature, key_id=key_id)


def verification_manifest(
    signed: EvidenceSetSignature,
) -> dict[str, Any]:
    """第三方验证清单：仅哈希+签名+密钥标识——不含证据 payload。"""
    return signed.model_dump(mode="json")


def verify_evidence_set(
    signed: EvidenceSetSignature, *, provided_hashes: list[str],
    key_resolver: KeyResolver,
) -> bool:
    """第三方独立验证（纯函数）：对手中哈希集重算并比对签名。

    provided_hashes 为第三方自己复算出的证据哈希集（从其收到的
    证据字节逐条 sha256）——与签名覆盖集一致且签名有效才通过。"""
    if signed.algorithm != SIGNATURE_ALGORITHM:
        raise VastaError(
            code="evidence.unknown_algorithm",
            message=f"签名算法 {signed.algorithm!r} 不受支持",
        )
    key = key_resolver(signed.key_id)
    expected = hmac.new(key, canonical_hash_set(signed.hashes),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signed.signature):
        return False  # 签名无效
    return canonical_hash_set(provided_hashes) == \
        canonical_hash_set(signed.hashes)


async def record_verification(
    store: Any, signed: EvidenceSetSignature, passed: bool, *,
    principal: Principal, verifier: str,
) -> None:
    """第三方验证结果回执留痕（verification 族——可审计）。"""
    from vastacore.governance.rbac import evaluate_access

    decision = evaluate_access(
        principal, "evidence", "write",
        tenant_id=principal.tenant_id, project_id=principal.project_id)
    if not decision.allowed:
        raise VastaError(
            code="access.denied",
            message=f"验证回执落盘需 evidence write（{decision.reason}）",
        )
    sequencer = EventSequencer(
        store, _VERIFICATION_RUN,
        tenant_id=principal.tenant_id, project_id=principal.project_id)
    await sequencer.emit(
        "verification.passed" if passed else "verification.deviated", {
            "verifier": verifier,
            "hash_count": len(signed.hashes),
            "digest": hashlib.sha256(
                canonical_hash_set(signed.hashes)).hexdigest(),
            "key_id": signed.key_id,
        })


__all__ = ["EvidenceSetSignature", "canonical_hash_set",
           "record_verification", "sign_evidence_set",
           "verification_manifest", "verify_evidence_set"]
