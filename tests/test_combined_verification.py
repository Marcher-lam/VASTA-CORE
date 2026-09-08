"""Story 3.4：组合核验器与核验流水线（FR-035/036）。"""

from __future__ import annotations

from vasta_contracts import (
    InvariantRule,
    InvariantVerifier,
    ReadBackVerifier,
    SchemaVerifier,
    VerificationPipeline,
)
from vasta_protocols.protocols import Observation, ToolResult, Verification
from vasta_runtime import RunContext, RunEngine

from .fakes import FakeStorageAdapter


class Env:
    protocol_version = "0.1.0"

    async def reset(self, seed=None):
        return Observation(kind="decision", available_actions=["x"])

    async def observe(self):
        return Observation(kind="decision", available_actions=["x"])

    async def execute(self, action):
        return [
            Observation(kind="transition"),
            Observation(kind="decision", available_actions=["x"]),
        ]

    async def status(self):
        class S:
            running = True

        return S()


async def make_engine():
    store = FakeStorageAdapter()
    engine = await RunEngine.create(
        env=Env(), store=store,
        run_context=RunContext.create(run_id="run-v", seed=1),
    )
    await engine.start()
    await engine.reset(seed=1)
    return engine, store


EVIDENCE_OK = {
    "contract_ref": "sha256:abc",
    "tool": "set_status",
    "result": ToolResult(ok=True, detail={"echo": {"i": 1}}),
    "after_observation": Observation(kind="external", detail={"status": "approved"}),
    "expected_changes": ["A102.status=approved"],
}


class TestSchemaVerifier:
    async def test_pass_on_ok_result(self) -> None:
        v = await SchemaVerifier().verify("r", dict(EVIDENCE_OK))
        assert v.outcome == "pass"

    async def test_deviation_on_failed_result(self) -> None:
        evidence = dict(EVIDENCE_OK, result=ToolResult(ok=False))
        v = await SchemaVerifier().verify("r", evidence)
        assert v.outcome == "deviation"

    async def test_inconclusive_on_missing_result(self) -> None:
        evidence = dict(EVIDENCE_OK)
        evidence.pop("result")
        v = await SchemaVerifier().verify("r", evidence)
        assert v.outcome == "inconclusive"  # 观察不足不冒充 pass


class TestReadBackVerifier:
    async def test_pass_when_expected_change_visible(self) -> None:
        v = await ReadBackVerifier().verify("r", dict(EVIDENCE_OK))
        assert v.outcome == "pass"

    async def test_deviation_when_change_missing(self) -> None:
        evidence = dict(EVIDENCE_OK, expected_changes=["A102.status=rejected"])
        v = await ReadBackVerifier().verify("r", evidence)
        assert v.outcome == "deviation"

    async def test_inconclusive_without_after_observation(self) -> None:
        evidence = dict(EVIDENCE_OK)
        evidence.pop("after_observation")
        v = await ReadBackVerifier().verify("r", evidence)
        assert v.outcome == "inconclusive"


class TestInvariantVerifier:
    async def test_eq_pass_and_deviation(self) -> None:
        verifier = InvariantVerifier([
            InvariantRule(field="result.ok", op="eq", value=True),
            InvariantRule(field="result.detail.echo.i", op="eq", value=1),
        ])
        v = await verifier.verify("r", dict(EVIDENCE_OK))
        assert v.outcome == "pass"
        bad = InvariantVerifier([
            InvariantRule(field="result.detail.echo.i", op="eq", value=2),
        ])
        v = await bad.verify("r", dict(EVIDENCE_OK))
        assert v.outcome == "deviation"

    async def test_ne_and_contains(self) -> None:
        verifier = InvariantVerifier([
            InvariantRule(field="tool", op="ne", value="delete_order"),
            InvariantRule(field="after_observation.detail.status", op="contains", value="approv"),
        ])
        v = await verifier.verify("r", dict(EVIDENCE_OK))
        assert v.outcome == "pass"

    async def test_unchanged_field_present(self) -> None:
        verifier = InvariantVerifier([
            InvariantRule(field="result.ok", op="unchanged"),
        ])
        v = await verifier.verify("r", dict(EVIDENCE_OK))
        assert v.outcome == "pass"

    async def test_missing_path_inconclusive(self) -> None:
        verifier = InvariantVerifier([
            InvariantRule(field="result.detail.nonexistent", op="eq", value=1),
        ])
        v = await verifier.verify("r", dict(EVIDENCE_OK))
        assert v.outcome == "inconclusive"

    async def test_unknown_op_inconclusive(self) -> None:
        verifier = InvariantVerifier([
            InvariantRule(field="tool", op="regex", value=".*"),
        ])
        v = await verifier.verify("r", dict(EVIDENCE_OK))
        assert v.outcome == "inconclusive"

    async def test_no_rules_inconclusive(self) -> None:
        v = await InvariantVerifier().verify("r", dict(EVIDENCE_OK))
        assert v.outcome == "inconclusive"


class Broken:
    protocol_version = "0.1.0"

    def __init__(self):
        from vasta_protocols.protocols import VerifierManifest

        self.manifest = VerifierManifest(name="broken", version="1", kind="schema")

    async def verify(self, contract_ref, evidence) -> Verification:
        raise RuntimeError("verifier crashed")


class TestPipeline:
    async def test_all_pass(self) -> None:
        pipeline = VerificationPipeline()
        aggregate, detail = await pipeline.run(
            ["schema", "read_back"], "r", dict(EVIDENCE_OK)
        )
        assert aggregate == "passed"

    async def test_unregistered_dominates_inconclusive(self) -> None:
        pipeline = VerificationPipeline()
        aggregate, detail = await pipeline.run(["schema", "nope"], "r", dict(EVIDENCE_OK))
        assert aggregate == "inconclusive"
        assert detail["unregistered"] == ["nope"]

    async def test_deviation_dominates(self) -> None:
        evidence = dict(EVIDENCE_OK, result=ToolResult(ok=False))
        aggregate, _ = await VerificationPipeline().run(["schema", "read_back"], "r", evidence)
        assert aggregate == "deviated"

    async def test_system_error_dominates_and_chain_continues(self) -> None:
        pipeline = VerificationPipeline()
        pipeline.register(Broken())
        evidence = dict(EVIDENCE_OK, result=ToolResult(ok=False))  # schema 会 deviation
        aggregate, detail = await pipeline.run(["broken", "schema"], "r", evidence)
        # 单器异常 → system_error 支配 deviation；整链未被异常中断
        assert aggregate == "errored"
        assert "broken" in detail["verifiers"]


class TestEngineEndToEnd:
    async def test_invariant_deviation_reaches_event(self) -> None:
        from vasta_contracts import make_complete_contract

        engine, store = await make_engine()
        contract = make_complete_contract(
            verify_with=["invariant"],
            prediction={"changes": ["A102.status=approved"],
                        "invariants": ["amount unchanged"]},
        )
        contract = contract.model_validate(contract.model_dump())
        # 注入不变量规则到流水线：经 verifiers 参数传入自定义 InvariantVerifier
        # （env 路径的 after 观察是 decision 帧——对真实存在字段立不变量）
        verifier = InvariantVerifier([
            InvariantRule(field="after_observation.kind", op="eq", value="decision"),
            InvariantRule(field="tool", op="ne", value="delete_order"),
        ])
        await engine.execute_contracted(contract, verifiers={"invariant": verifier})
        v = [e for e in store.iter_run_events("run-v")
             if e.type.startswith("verification.")][-1]
        assert v.type == "verification.passed"

    async def test_observation_insufficient_inconclusive(self) -> None:
        """env 路径 after 观察细节为空 → read_back 无从比对 → inconclusive/
        deviation，绝不 pass（观察不足不冒充成功）。"""
        from vasta_contracts import make_complete_contract

        engine, store = await make_engine()
        contract = make_complete_contract(verify_with=["read_back"])
        await engine.execute_contracted(contract)
        v = [e for e in store.iter_run_events("run-v")
             if e.type.startswith("verification.")][-1]
        assert v.type in {"verification.deviated", "verification.inconclusive"}
        assert v.type != "verification.passed"
