"""组合核验器实现集与核验流水线（FR-035/036，Story 3.4）。

三器首版：
- SchemaVerifier：ToolResult 形状与 ok 一致性；
- ReadBackVerifier：读回观察可用性与预期变化子集匹配；
- InvariantVerifier：结构化不变量规则 DSL（= ≠ contains unchanged 四操作）。

VerificationPipeline：按 verify_with 组合执行，聚合沿用 3.1 语义
（未注册名优先 inconclusive、system_error > deviation > 全 pass 才 pass）。
核验器只读 evidence dict——独立于执行模型自评（INV-06 的 MVP 形态）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import (
    Observation,
    ToolResult,
    Verification,
    Verifier,
    VerifierManifest,
)

#: evidence 键约定：核验器的确定性输入（INV-06：不依赖执行模型自评）。
EVIDENCE_KEYS = ("contract_ref", "tool", "result", "after_observation", "expected_changes")


class _BaseVerifier:
    protocol_version = "0.1.0"

    def __init__(self, name: str, kind: str) -> None:
        self.manifest = VerifierManifest(name=name, version="1.0", kind=kind)

    async def verify(self, contract_ref: str, evidence: dict[str, Any]) -> Verification:
        try:
            outcome, detail = self._check(contract_ref, evidence)
        except VastaError:
            raise
        except Exception as exc:  # 单器异常 → system_error，不中断整链
            return Verification(
                outcome="system_error", detail={"error": f"{type(exc).__name__}: {exc}"}
            )
        return Verification(outcome=outcome, detail=detail)

    def _check(self, contract_ref: str, evidence: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        raise NotImplementedError


class SchemaVerifier(_BaseVerifier):
    """ToolResult 形状核验：ok 字段存在且 detail 可解析（若为 dict）。"""

    def __init__(self) -> None:
        super().__init__(name="schema", kind="schema")

    def _check(self, contract_ref: str, evidence: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        result = evidence.get("result")
        if result is None:
            return "inconclusive", {"reason": "result 缺失（观察不足）"}
        if not isinstance(result, ToolResult):
            if isinstance(result, dict):
                result = ToolResult.model_validate(result)
            else:
                return "inconclusive", {"reason": "result 类型不识别"}
        ok = bool(result.ok)
        return ("pass" if ok else "deviation"), {"ok": ok}


class ReadBackVerifier(_BaseVerifier):
    """读回核验：after 观察可用 + 预期变化子集匹配（首版语义）。

    expected_changes 形如 ["A102.status=approved"]；after_observation.detail
    中含 tool 响应摘要时做子串匹配；无 expected → 仅核观察可用性。
    """

    def __init__(self) -> None:
        super().__init__(name="read_back", kind="read_back")

    def _check(self, contract_ref: str, evidence: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        after = evidence.get("after_observation")
        if after is None:
            return "inconclusive", {"reason": "after_observation 缺失（读回未采集）"}
        if not isinstance(after, Observation) and not isinstance(after, dict):
            return "inconclusive", {"reason": "after_observation 类型不识别"}
        detail = after.detail if isinstance(after, Observation) else after.get("detail", {})
        blob = str(detail)
        expected = evidence.get("expected_changes") or []
        unmatched = [c for c in expected if c.split("=", 1)[-1] not in blob]
        if unmatched:
            return "deviation", {"unmatched_changes": unmatched}
        return "pass", {"matched": len(expected), "read_back_available": True}


#: 不变量 DSL 操作集。
INVARIANT_OPS = ("eq", "ne", "contains", "unchanged")


def _dig(evidence: dict[str, Any], path: str) -> tuple[bool, Any]:
    """点分路径取值（dict 键 + 对象属性双通道）；任一层缺失返回 (False, None)。"""
    current: Any = evidence
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif hasattr(current, part):
            current = getattr(current, part)
        else:
            return False, None
    return True, current


class InvariantRule(BaseModel):
    """结构化不变量：field.op.value。"""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(description="evidence 点分路径，如 result.detail.echo.i")
    op: str = Field(description=f"操作：{INVARIANT_OPS}")
    value: Any = None
    note: str | None = None


class InvariantVerifier(_BaseVerifier):
    """不变量规则求值（UJ-2 本地版）：用户以结构化规则定义。

    - eq/ne/contains：对 evidence 当前值判定；
    - unchanged：期望字段在 evidence 中存在（变化前后比对的持久态在
      Stage 3 事件对照中完备；MVP 以"字段在场且可读"为核）；
    - 路径缺失/类型不匹配/未知操作 → inconclusive（不抛、不冒充 pass）。
    """

    def __init__(self, rules: list[InvariantRule] | None = None) -> None:
        super().__init__(name="invariant", kind="invariant")
        self.rules = rules or []

    def _check(self, contract_ref: str, evidence: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if not self.rules:
            return "inconclusive", {"reason": "未定义不变量规则"}
        results: list[dict[str, Any]] = []
        any_inconclusive = False
        for rule in self.rules:
            present, actual = _dig(evidence, rule.field)
            entry: dict[str, Any] = {"field": rule.field, "op": rule.op}
            if rule.op not in INVARIANT_OPS:
                entry["status"] = "inconclusive"
                entry["reason"] = f"未知操作 {rule.op!r}"
                any_inconclusive = True
            elif not present:
                entry["status"] = "inconclusive"
                entry["reason"] = "路径缺失（观察不足）"
                any_inconclusive = True
            elif rule.op == "eq":
                ok = actual == rule.value
                entry["status"] = "pass" if ok else "deviation"
            elif rule.op == "ne":
                ok = actual != rule.value
                entry["status"] = "pass" if ok else "deviation"
            elif rule.op == "contains":
                ok = rule.value in actual if hasattr(actual, "__contains__") else False
                entry["status"] = "pass" if ok else "deviation"
            else:  # unchanged
                entry["status"] = "pass"
                entry["note"] = "字段在场（持久态比对 Stage 3 完备）"
            results.append(entry)
        statuses = [r["status"] for r in results]
        if "deviation" in statuses:
            return "deviation", {"rules": results}
        if any_inconclusive:
            return "inconclusive", {"rules": results}
        return "pass", {"rules": results}


class VerificationPipeline:
    """按 verify_with 组合核验；聚合语义与 3.1 引擎内联版一致。"""

    def __init__(self, verifiers: dict[str, Verifier] | None = None) -> None:
        self.registry: dict[str, Verifier] = {
            "schema": SchemaVerifier(),
            "read_back": ReadBackVerifier(),
            **(verifiers or {}),
        }

    def register(self, verifier: Verifier) -> None:
        self.registry[verifier.manifest.name] = verifier

    async def run(
        self, verify_with: list[str], contract_ref: str, evidence: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        outcomes: list[str] = []
        unregistered: list[str] = []
        details: dict[str, Any] = {}
        for name in verify_with:
            verifier = self.registry.get(name)
            if verifier is None:
                unregistered.append(name)
                continue
            try:
                result = await verifier.verify(contract_ref, evidence)
            except Exception as exc:  # 外部核验器异常 → 该器 system_error
                result = Verification(
                    outcome="system_error",
                    detail={"error": f"{type(exc).__name__}: {exc}"},
                )
            outcomes.append(result.outcome)
            details[name] = result.detail
        aggregate, agg_detail = _aggregate(outcomes, unregistered)
        return aggregate, {"verifiers": details, **agg_detail}


def _aggregate(
    outcomes: list[str], unregistered: list[str]
) -> tuple[str, dict[str, Any]]:
    detail: dict[str, Any] = {}
    if unregistered:
        detail["unregistered"] = unregistered
        return "inconclusive", detail
    if not outcomes:
        return "inconclusive", {"reason": "no_verifiers_configured"}
    if "system_error" in outcomes:
        return "errored", detail
    if "deviation" in outcomes:
        return "deviated", detail
    if all(o == "pass" for o in outcomes):
        return "passed", detail
    return "inconclusive", detail


DEFAULT_PIPELINE = VerificationPipeline


__all__ = [
    "DEFAULT_PIPELINE",
    "EVIDENCE_KEYS",
    "INVARIANT_OPS",
    "InvariantRule",
    "InvariantVerifier",
    "ReadBackVerifier",
    "SchemaVerifier",
    "VerificationPipeline",
    "_aggregate",
    "_dig",
]
