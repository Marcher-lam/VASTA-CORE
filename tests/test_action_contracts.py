"""Story 3.1：ActionContract 模型与缺段拒执行（FR-030/031，NFR-001/AC-02）。"""

from __future__ import annotations

import pytest

from vasta_contracts import (
    REQUIRED_SEGMENTS,
    ActionContract,
    ContractIncompleteError,
    Prediction,
    audit_six_segment,
    make_complete_contract,
    missing_segments,
)
from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action, Observation, Verification, VerifierManifest
from vasta_runtime import PolicyDeniedError, PolicyOutcome, RunConfig, RunEngine

from .fakes import FakeStorageAdapter


class ContractEnv:
    """接受任意工具调用的环境（契约路径测试用）。"""

    protocol_version = "0.1.0"
    deterministic = True

    def __init__(self) -> None:
        self.execute_count = 0

    async def reset(self, seed: int | None = None) -> Observation:
        return Observation(kind="decision", available_actions=["set_status"])

    async def observe(self) -> Observation:
        return Observation(kind="decision", available_actions=["set_status"])

    async def execute(self, action: Action) -> list[Observation]:
        self.execute_count += 1
        return [
            Observation(kind="transition"),
            Observation(kind="decision", available_actions=["set_status"]),
        ]

    async def status(self) -> object:
        class _S:
            running = True

        return _S()


class ExplodingContractEnv(ContractEnv):
    async def execute(self, action: Action) -> list[Observation]:
        raise RuntimeError("tool crashed")


async def make_engine(env=None):
    store = FakeStorageAdapter()
    engine = await RunEngine.create(
        env=env or ContractEnv(), store=store, config=RunConfig(run_id="run-c3")
    )
    await engine.start()
    await engine.reset(seed=1)
    return engine, store


class PassVerifier:
    protocol_version = "0.1.0"
    manifest = VerifierManifest(name="read_back", version="1", kind="read_back")

    async def verify(self, contract_ref: str, evidence: dict) -> Verification:
        return Verification(outcome="pass")


class DeviationVerifier:
    protocol_version = "0.1.0"
    manifest = VerifierManifest(name="visual", version="1", kind="visual_diff")

    async def verify(self, contract_ref: str, evidence: dict) -> Verification:
        return Verification(outcome="deviation")


def types_of(store) -> list[str]:
    return [e.type for e in store.iter_run_events("run-c3")]


class TestMissingSegments:
    def test_complete_contract_has_no_missing(self) -> None:
        assert missing_segments(make_complete_contract()) == []

    @pytest.mark.parametrize(
        ("overrides", "expected_missing"),
        [
            ({"preconditions": None}, ["preconditions"]),
            ({"preconditions": []}, ["preconditions"]),  # 空也缺
            ({"prediction": None}, ["prediction.changes", "prediction.invariants"]),
            ({"prediction": Prediction(changes=[], invariants=["x"])}, ["prediction.changes"]),
            ({"prediction": Prediction(changes=["x"], invariants=[])}, ["prediction.invariants"]),
            ({"success_criteria": []}, ["success_criteria"]),
            ({"failure_criteria": None}, ["failure_criteria"]),
            ({"verify_with": []}, ["verify_with"]),
            ({"timeout_ms": None}, ["timeout_ms"]),
            ({"timeout_ms": 0}, ["timeout_ms"]),  # 非正数即缺
        ],
    )
    def test_each_segment_missing(self, overrides, expected_missing) -> None:
        contract = make_complete_contract(**overrides)
        assert missing_segments(contract) == expected_missing

    def test_required_segments_constant_matches(self) -> None:
        assert len(REQUIRED_SEGMENTS) == 7


class TestRejectOnIncomplete:
    async def test_missing_segment_rejects_without_execution(self) -> None:
        engine, store = await make_engine()
        env: ContractEnv = engine.env  # type: ignore[assignment]
        contract = make_complete_contract(verify_with=None)  # 缺核验器段

        with pytest.raises(ContractIncompleteError) as excinfo:
            await engine.execute_contracted(contract)
        assert "verify_with" in excinfo.value.missing

        assert env.execute_count == 0  # 未触环境
        assert engine.tracker.snapshot().actions_used == 0  # 未耗预算
        types = types_of(store)
        assert "action.policy_denied" in types
        assert "action.contracted" not in types
        assert "action.executed" not in types
        denied = [e for e in store.iter_run_events("run-c3")
                  if e.type == "action.policy_denied"][-1]
        assert denied.payload["phase"] == "contract"
        assert denied.payload["missing_segments"] == ["verify_with"]

    async def test_rejected_chain_counts_as_rejected_in_audit(self) -> None:
        """缺段链在审计中记为 rejected（合法终态），不进 NFR-001 分母。"""
        engine, store = await make_engine()
        contract = make_complete_contract(timeout_ms=None)
        with pytest.raises(ContractIncompleteError):
            await engine.execute_contracted(contract)
        audit = audit_six_segment(list(store.iter_run_events("run-c3")))
        assert audit.total == 0  # 拒发生在 contracted 事件之前——无链可审

    async def test_policy_deny_after_contract_emits_rejected_chain(self) -> None:
        engine, store = await make_engine()
        env: ContractEnv = engine.env  # type: ignore[assignment]
        contract = make_complete_contract()

        def deny(_c) -> PolicyOutcome:
            return PolicyOutcome(decision="deny", reason="超出当日限额")

        with pytest.raises(PolicyDeniedError):
            await engine.execute_contracted(contract, policy_check=deny)
        assert env.execute_count == 0
        types = types_of(store)
        assert types[-1] == "action.policy_denied"
        audit = audit_six_segment(list(store.iter_run_events("run-c3")))
        assert audit.total == 1 and audit.rejected == 1
        assert audit.all_success_paths_complete


class TestSixSegmentChain:
    async def test_happy_path_six_segments_complete(self) -> None:
        engine, store = await make_engine()
        contract = make_complete_contract()
        observations = await engine.execute_contracted(
            contract, verifiers={"read_back": PassVerifier()}
        )
        assert len(observations) == 2
        types = types_of(store)
        # 六段链事件齐备且有序
        assert "action.contracted" in types
        assert "action.policy_cleared" in types
        assert "action.executed" in types
        assert "verification.passed" in types
        # 审计：complete 100%
        audit = audit_six_segment(list(store.iter_run_events("run-c3")))
        assert audit.total == 1
        assert audit.complete == 1
        assert audit.all_success_paths_complete is True

    async def test_contract_persisted_before_reference(self) -> None:
        """AD-3：契约 JSON 先落 CAS，事件引用其 sha。"""
        import json as jsonlib

        engine, store = await make_engine()
        contract = make_complete_contract()
        await engine.execute_contracted(
            contract, verifiers={"read_back": PassVerifier()}
        )
        contracted = [e for e in store.iter_run_events("run-c3")
                      if e.type == "action.contracted"][-1]
        ref = contracted.payload["contract_ref"]
        payload = await store.get_artifact(ref)
        roundtrip = ActionContract.model_validate(jsonlib.loads(payload))
        assert roundtrip == contract  # 契约完整可回读
        # 预留字段可见（Stage 3 激活）
        assert contracted.payload["idempotency_key"] is None
        assert contracted.payload["compensation"] is None

    async def test_causal_chain_intact(self) -> None:
        engine, store = await make_engine()
        await engine.execute_contracted(
            make_complete_contract(), verifiers={"read_back": PassVerifier()}
        )
        events = list(store.iter_run_events("run-c3"))
        for prev, cur in zip(events, events[1:], strict=False):
            assert cur.parent_event_id == prev.event_id

    async def test_after_observation_carries_last_action(self) -> None:
        engine, store = await make_engine()
        await engine.execute_contracted(
            make_complete_contract(), verifiers={"read_back": PassVerifier()}
        )
        after = [e for e in store.iter_run_events("run-c3")
                 if e.type == "observation.transition"][-1]
        assert after.payload["last_action"] == "set_status"


class TestVerificationAggregation:
    async def test_unregistered_verifier_inconclusive(self) -> None:
        """3.4 语义：默认流水线注册 schema/read_back/invariant——用注册表外
        的名字测未注册路径。"""
        engine, store = await make_engine()
        contract = make_complete_contract(verify_with=["schema", "visual_diff"])
        await engine.execute_contracted(contract)
        v = [e for e in store.iter_run_events("run-c3")
             if e.type.startswith("verification.")][-1]
        assert v.type == "verification.inconclusive"
        assert v.payload["unregistered"] == ["visual_diff"]

    async def test_default_read_back_deviation_on_env_path(self) -> None:
        """env 直连路径：默认 ReadBack 核验器对空观察细节判 deviation
        （预期变化未在 after 观察中体现——不冒充 pass）。"""
        engine, store = await make_engine()
        await engine.execute_contracted(make_complete_contract())
        v = [e for e in store.iter_run_events("run-c3")
             if e.type.startswith("verification.")][-1]
        assert v.type == "verification.deviated"

    async def test_deviation_dominates(self) -> None:
        engine, store = await make_engine()
        contract = make_complete_contract(verify_with=["a", "b"])
        await engine.execute_contracted(
            contract,
            verifiers={"a": PassVerifier(), "b": DeviationVerifier()},
        )
        v = [e for e in store.iter_run_events("run-c3")
             if e.type.startswith("verification.")][-1]
        assert v.type == "verification.deviated"


class TestGuardsOnContractedPath:
    async def test_requires_started(self) -> None:
        store = FakeStorageAdapter()
        engine = await RunEngine.create(
            env=ContractEnv(), store=store, config=RunConfig(run_id="run-c3")
        )
        with pytest.raises(VastaError):
            await engine.execute_contracted(make_complete_contract())

    async def test_budget_counts_and_stops(self) -> None:
        from vasta_runtime import Budget, BudgetExceededError, RunContext

        store = FakeStorageAdapter()
        engine = await RunEngine.create(
            env=ContractEnv(), store=store, budget=Budget(max_actions=1),
            run_context=RunContext.create(run_id="run-c3", seed=1),
        )
        await engine.start()
        await engine.reset(seed=1)
        await engine.execute_contracted(
            make_complete_contract(), verifiers={"read_back": PassVerifier()}
        )
        assert engine.tracker.snapshot().actions_used == 1
        with pytest.raises(BudgetExceededError):
            await engine.execute_contracted(make_complete_contract())
        assert engine.state.value == "failed"

    async def test_execution_exception_fails_with_action_failed(self) -> None:
        engine, store = await make_engine(env=ExplodingContractEnv())
        with pytest.raises(RuntimeError):
            await engine.execute_contracted(make_complete_contract())
        types = types_of(store)
        assert "action.failed" in types
        assert types[-1] == "run.failed"
        assert engine.state.value == "failed"
        audit = audit_six_segment(list(store.iter_run_events("run-c3")))
        assert audit.total == 1
        # 评审修复：执行异常链 = failed（合法终态，NFR-001 不误报）
        assert audit.chains[0].status == "failed"
        assert audit.all_success_paths_complete is True
