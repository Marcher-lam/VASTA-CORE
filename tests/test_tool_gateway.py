"""Story 3.2：Tool Gateway 与工具清单（FR-032，AD-4/AD-11）。"""

from __future__ import annotations

import pytest

from vasta_contracts import audit_six_segment, make_complete_contract
from vasta_policy import ApprovalRequestedError, PolicyEngine
from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import (
    Action,
    DryRunResult,
    Observation,
    ToolAdapter,
    ToolManifest,
    ToolResult,
)
from vasta_runtime import (
    Budget,
    DuplicateToolError,
    RunContext,
    RunEngine,
    ToolGateway,
    ToolNotRegisteredError,
    canonical_args_hash,
    idempotency_key,
)

from .fakes import FakeStorageAdapter


class WriteTool:
    """清单完整的写工具（R2，非只读，支持 dry_run/幂等）。"""

    protocol_version = "0.1.0"

    def __init__(self, *, name="set_status", risk="R2", allow_dry=True) -> None:
        self.manifest = ToolManifest(
            name=name,
            version="1.0",
            risk=risk,  # type: ignore[arg-type]
            read_only=False,
            idempotent=True,
            supports_dry_run=True,
        )
        self.execute_count = 0
        self._allow_dry = allow_dry

    async def dry_run(self, action: Action) -> DryRunResult:
        return DryRunResult(allowed=self._allow_dry, reason=None if self._allow_dry else "blocked")

    async def execute(self, action: Action, idempotency_key: str) -> ToolResult:
        self.execute_count += 1
        return ToolResult(ok=True, detail={"echo": action.args, "key": idempotency_key})

    async def read_back(self, action: Action) -> Observation:
        return Observation(kind="external")

    async def compensate(self, execution_detail: dict) -> ToolResult:
        return ToolResult(ok=True)


class ContractEnv:
    """占位环境（网关路径不触它）。"""

    protocol_version = "0.1.0"

    def __init__(self) -> None:
        self.execute_count = 0

    async def reset(self, seed=None):
        return Observation(kind="decision", available_actions=["x"])

    async def observe(self):
        return Observation(kind="decision", available_actions=["x"])

    async def execute(self, action: Action):
        self.execute_count += 1
        return [Observation(kind="transition"), Observation(kind="decision")]

    async def status(self):
        class S:
            running = True

        return S()


async def make_engine(gateway=None, budget=None, policy_engine=None):
    store = FakeStorageAdapter()
    engine = await RunEngine.create(
        env=ContractEnv(),
        store=store,
        budget=budget,
        run_context=RunContext.create(run_id="run-gw", seed=1),
        tool_gateway=gateway,
        policy_engine=policy_engine,
    )
    await engine.start()
    await engine.reset(seed=1)
    return engine, store


def types_of(store):
    return [e.type for e in store.iter_run_events("run-gw")]


class TestRegistrationAndClassification:
    def test_register_and_classify(self) -> None:
        gw = ToolGateway()
        tool = WriteTool()
        gw.register(tool)
        assert gw.registered_tools() == ["set_status"]
        assert gw.classify("set_status") == (False, "R2")  # 清单强制

    def test_unregistered_classify_rejected(self) -> None:
        gw = ToolGateway()
        with pytest.raises(ToolNotRegisteredError):
            gw.classify("nope")

    def test_duplicate_registration_rejected(self) -> None:
        gw = ToolGateway()
        gw.register(WriteTool())
        with pytest.raises(DuplicateToolError):
            gw.register(WriteTool())

    def test_manifest_incomplete_rejected_at_construction(self) -> None:
        """FR-032：缺风险/幂等声明的清单在 ToolManifest 构造期即拒。"""
        with pytest.raises(Exception):  # noqa: B017（pydantic 校验错误）
            ToolManifest(name="bad", version="1")  # 缺 risk/read_only/idempotent


class TestIdempotencyKey:
    def test_key_order_independent(self) -> None:
        assert canonical_args_hash({"a": 1, "b": [2, 3]}) == canonical_args_hash(
            {"b": [2, 3], "a": 1}
        )

    def test_formula(self) -> None:
        key = idempotency_key("run-1", "step-2", "tool", {"x": 1})
        assert key.startswith("run-1:step-2:tool:")
        assert key.endswith(canonical_args_hash({"x": 1}))


class TestGatewayReplay:
    async def test_same_key_returns_original_never_reexecutes(self) -> None:
        gw = ToolGateway()
        tool = WriteTool()
        gw.register(tool)
        first = await gw.execute(
            run_id="r", plan_step_id="s", action=Action(tool="set_status", args={"i": 1})
        )
        second = await gw.execute(
            run_id="r", plan_step_id="s", action=Action(tool="set_status", args={"i": 1})
        )
        assert tool.execute_count == 1  # 绝不静默重执行
        assert second.replayed is True
        assert second.detail == first.detail
        assert second.ok == first.ok

    async def test_different_args_different_key(self) -> None:
        gw = ToolGateway()
        tool = WriteTool()
        gw.register(tool)
        await gw.execute(run_id="r", plan_step_id="s",
                         action=Action(tool="set_status", args={"i": 1}))
        await gw.execute(run_id="r", plan_step_id="s",
                         action=Action(tool="set_status", args={"i": 2}))
        assert tool.execute_count == 2

    async def test_dry_run_gate_blocks_execution(self) -> None:
        gw = ToolGateway()
        tool = WriteTool(allow_dry=False)
        gw.register(tool)
        result = await gw.execute(
            run_id="r", plan_step_id="s", action=Action(tool="set_status", args={})
        )
        assert result.ok is False
        assert result.detail["phase"] == "dry_run"
        assert tool.execute_count == 0


class TestEngineGatewayPath:
    async def test_unregistered_tool_rejected_without_execution(self) -> None:
        engine, store = await make_engine(gateway=ToolGateway())  # 空网关
        env: ContractEnv = engine.env  # type: ignore[assignment]
        contract = make_complete_contract(tool="set_status")

        with pytest.raises(VastaError) as excinfo:
            await engine.execute_contracted(contract)
        assert excinfo.value.code == "tool.not_registered"
        assert env.execute_count == 0  # 未触环境
        assert engine.tracker.snapshot().actions_used == 0  # 未耗预算
        types = types_of(store)
        assert types[-1] == "action.policy_denied"
        denied = [e for e in store.iter_run_events("run-gw")
                  if e.type == "action.policy_denied"][-1]
        assert denied.payload["phase"] == "tool"

    async def test_gateway_path_six_segments_and_evidence(self) -> None:
        gw = ToolGateway()
        tool = WriteTool(risk="R3")
        gw.register(tool)
        engine, store = await make_engine(
            gateway=gw, policy_engine=PolicyEngine()
        )
        contract = make_complete_contract(tool="set_status", risk="R0")  # 自报 R0

        with pytest.raises(ApprovalRequestedError):
            await engine.execute_contracted(contract, plan_step_id="step-1")
        # 清单 R3 → 请求批准（清单强制，自报 R0 无效）——走批准闭环
        observations = await engine.approve_pending(contract, plan_step_id="step-1")
        assert observations[0].kind == "external"
        executed = [e for e in store.iter_run_events("run-gw")
                    if e.type == "action.executed"][-1]
        # AD-4：分类由清单强制——自报 R0 无效，effective R3
        assert executed.payload["risk_declared"] == "R0"
        assert executed.payload["risk_effective"] == "R3"
        assert executed.payload["read_only"] is False
        # FR-010：工具原始响应先落 CAS 且可回读
        import json as jsonlib

        result_payload = jsonlib.loads(
            await store.get_artifact(executed.payload["result_ref"])
        )
        assert result_payload["ok"] is True
        # 六段链审计：批准重入后 complete（首链 pending→被批准续行覆盖）
        audit = audit_six_segment(list(store.iter_run_events("run-gw")))
        assert audit.complete >= 1
        executed = [e for e in store.iter_run_events("run-gw")
                    if e.type == "action.executed"]
        assert len(executed) == 1  # 一次逻辑执行

    async def test_replay_no_budget_no_reexecution(self) -> None:
        gw = ToolGateway()
        tool = WriteTool()
        gw.register(tool)
        engine, store = await make_engine(gateway=gw, budget=Budget(max_actions=1))
        contract = make_complete_contract(tool="set_status")

        await engine.execute_contracted(contract, plan_step_id="s1")
        assert engine.tracker.snapshot().actions_used == 1
        # 同 plan_step_id 重放：不耗预算、适配器不重执行
        await engine.execute_contracted(contract, plan_step_id="s1")
        assert tool.execute_count == 1
        assert engine.tracker.snapshot().actions_used == 1
        executed = [e for e in store.iter_run_events("run-gw")
                    if e.type == "action.executed"]
        assert executed[-1].payload["replayed"] is True

    async def test_credentials_only_in_gateway(self) -> None:
        """AD-4 结构性断言：引擎不持有任何 ToolAdapter。"""
        gw = ToolGateway()
        gw.register(WriteTool())
        engine, _ = await make_engine(gateway=gw)
        for value in engine.__dict__.values():
            assert not isinstance(value, ToolAdapter)
        # 适配器只在网关注册表里
        found = [v for v in gw.__dict__.values() if isinstance(v, dict)
                 and any(isinstance(t, ToolAdapter) for t in v.values())]
        assert found  # 网关持有

    async def test_no_gateway_env_path_unchanged(self) -> None:
        engine, store = await make_engine()  # 无网关
        env: ContractEnv = engine.env  # type: ignore[assignment]
        contract = make_complete_contract(tool="set_status")
        observations = await engine.execute_contracted(contract)
        assert env.execute_count == 1  # env 直连路径
        assert len(observations) == 2
        executed = [e for e in store.iter_run_events("run-gw")
                    if e.type == "action.executed"][-1]
        assert "risk_effective" not in executed.payload  # 3.1 形态不变
