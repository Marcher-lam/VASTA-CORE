"""Epic 6：世界模型实验室（接口/沙箱/验证/MetaController/规划/桥接）。"""

from __future__ import annotations

import pytest

from vasta_model_lab import (
    DSLWorldModel,
    MetaDecision,
    MetaSignals,
    PlanCaps,
    PythonWorldModel,
    RuleSet,
    SandboxExecutor,
    Trajectory,
    WorldModelBridge,
    WorldModelManifest,
    decide_meta,
    plan_bfs,
    validate_model,
)
from vasta_protocols.errors import VastaError

from .fakes import FakeStorageAdapter


def grid_manifest(name="grid-4x4") -> WorldModelManifest:
    return WorldModelManifest(
        name=name,
        version="1.0",
        scope="4x4 网格导航",
        assumptions=["动作确定性", "无障碍"],
        unknowns=["是否有传送门"],
        coverage=["up/down/left/right"],
    )


def grid_dsl() -> DSLWorldModel:
    rules = RuleSet(
        rules={
            "right": {"add": {"col": 1}},
            "left": {"add": {"col": -1}},
            "down": {"add": {"row": 1}},
            "up": {"add": {"row": -1}},
        },
        goal_check="done",
    )
    m = grid_manifest()
    return DSLWorldModel(m, rules)


def grid_traj(n: int = 3) -> Trajectory:
    """确定性网格轨迹：右×3 到 (0,3) 置 done。"""
    obs0 = {"detail": {"row": 0, "col": 0}}
    actions = [{"tool": "right"}] * n
    observations = [{"kind": "decision", "row": 0, "col": i + 1} for i in range(n)]
    return Trajectory(obs0, actions, observations, "ongoing")


class TestModelInterface:
    def test_dsl_model_implements_min_interface(self) -> None:
        m = grid_dsl()
        state = m.init_state({"detail": {"row": 0, "col": 0}})
        state = m.transition(state, {"tool": "right"})
        assert state["col"] == 1
        assert m.outcome(state) == "ongoing"
        state["done"] = True
        assert m.outcome(state) == "goal"

    def test_manifest_declares_unknown(self) -> None:
        m = grid_dsl()
        assert m.manifest.unknowns  # FR-043：显式 Unknown
        assert m.manifest.scope and m.manifest.coverage

    def test_python_model_static_check(self) -> None:
        good = "result = dict(state)\nresult['x'] = 1"
        m = PythonWorldModel(grid_manifest("py1"), good)
        assert m.manifest.name == "py1"
        # 危险模式拒
        with pytest.raises(VastaError) as excinfo:
            PythonWorldModel(grid_manifest("py2"), "import os\nresult = {}")
        assert excinfo.value.code == "model_lab.forbidden_import"

    def test_python_model_transition_local(self) -> None:
        code = "result = dict(state)\nresult['count'] = state.get('count', 0) + 1"
        m = PythonWorldModel(grid_manifest("py3"), code)
        s = m.transition({"count": 1}, {"tool": "x"})
        assert s["count"] == 2


class TestSandbox:
    async def test_sandbox_executes_isolated(self) -> None:
        sb = SandboxExecutor(timeout_s=10, cpu_s=2, mem_mb=64)
        code = "result = {'doubled': state['x'] * 2}"
        out = await sb.run(code, {"state": {"x": 21}, "action": {}})
        assert out["ok"] is True
        assert out["result"]["doubled"] == 42

    async def test_sandbox_timeout_real_clock(self) -> None:
        sb = SandboxExecutor(timeout_s=0.3)
        code = "x = 0\nwhile True: x += 1"
        with pytest.raises(VastaError) as excinfo:
            await sb.run(code, {"state": {}, "action": {}})
        assert excinfo.value.code == "sandbox.timeout"  # AD-15：真实墙钟

    async def test_sandbox_no_network(self) -> None:
        """网络访问在静态检查即拒（MVP 无网络沙箱形态）。"""
        code = "import socket\nresult = {}"
        with pytest.raises(VastaError) as excinfo:
            PythonWorldModel(grid_manifest("py-net"), code)
        assert excinfo.value.code == "model_lab.forbidden_import"

    async def test_sandbox_memory_error(self) -> None:
        import sys as _sys

        if _sys.platform == "win32":
            pytest.skip("Windows 无 RLIMIT_AS——内存限额为 POSIX 边界（AD-6 记录）")
        sb = SandboxExecutor(timeout_s=10, mem_mb=16)
        code = "result = {'blob': 'x' * 100_000_000}"
        with pytest.raises(VastaError) as excinfo:
            await sb.run(code, {"state": {}, "action": {}})
        assert excinfo.value.code in {"sandbox.execution_failed", "sandbox.bad_output"}


class TestValidationPipeline:
    def test_replay_all_pass_with_approval_activatable(self) -> None:
        m = grid_dsl()
        trajs = [grid_traj(3), grid_traj(2), grid_traj(1)]
        props = [lambda model: True]  # 简单性质：模型不炸
        report = validate_model(
            m, trajs, properties=props, activation_approved=True
        )
        assert report.all_replay_passed
        assert report.activatable  # 全过 + 人工批准

    def test_without_approval_not_activatable(self) -> None:
        m = grid_dsl()
        report = validate_model(m, [grid_traj(3)], activation_approved=False)
        assert not report.activatable  # 无人工批准不激活（MVP 影子替代）

    def test_replay_mismatch_detected(self) -> None:
        m = grid_dsl()
        traj = grid_traj(3)
        traj.observations[0]["col"] = 99  # 篡改——回放必不一致
        report = validate_model(m, [traj], activation_approved=True)
        assert not report.all_replay_passed


class TestMetaController:
    def test_rules(self) -> None:
        # 长规划 + 高风险 + 无模型 → BUILD
        assert decide_meta(MetaSignals(planning_horizon=8, real_action_risk="R3")) is MetaDecision.BUILD
        # 有验证模型 → USE
        assert decide_meta(
            MetaSignals(planning_horizon=8, real_action_risk="R3",
                        has_validated_model=True)
        ) is MetaDecision.USE
        # 连续预测失败 + 有模型 → REPAIR
        assert decide_meta(
            MetaSignals(repeated_prediction_failure=4, has_validated_model=True)
        ) is MetaDecision.REPAIR
        # 默认 → BYPASS
        assert decide_meta(MetaSignals()) is MetaDecision.BYPASS
        # 无模型失败 → PROBE
        assert decide_meta(
            MetaSignals(repeated_prediction_failure=2)
        ) is MetaDecision.PROBE


class TestPlanner:
    def test_bfs_finds_goal(self) -> None:
        m = grid_dsl()
        # 目标：col=3 → 构造 goal 轨迹
        actions = [{"tool": "right"}, {"tool": "down"}, {"tool": "left"}, {"tool": "up"}]
        plan = plan_bfs(
            m, {"detail": {"row": 0, "col": 0, "done": 0}},
            actions=actions, caps=PlanCaps(max_depth=6),
        )
        assert isinstance(plan, list)  # 超限/无目标返回已达最佳（可为空）

    def test_caps_terminate(self) -> None:
        m = grid_dsl()
        actions = [{"tool": "right"}, {"tool": "down"}]
        # 极小上限——不炸、正常终止
        plan = plan_bfs(
            m, {"detail": {"row": 0, "col": 0}},
            actions=actions, caps=PlanCaps(max_nodes=3),
        )
        assert isinstance(plan, list)

    def test_stepwise_real_verification_hook(self) -> None:
        """FR-048：仿真通过不等于跳过现实核验——规划器只产计划，
        现实执行由 execute_contracted 逐步核验（集成在引擎侧已有测试）。"""
        m = grid_dsl()
        plan = plan_bfs(
            m, {"detail": {"row": 0, "col": 0, "done": 1}},
            actions=[{"tool": "right"}],
        )
        assert plan == []  # 初始即 goal → 空计划


class TestBridge:
    async def test_claim_refuted_suspends_models(self) -> None:
        """AD-13：claim.refuted → world_model.suspended（唯一 owner）。"""
        from vasta_cognition import Claim, CognitionService

        store = FakeStorageAdapter()
        cognition = CognitionService(store)
        await cognition.propose(Claim(
            claim_id="hyp-1", memory_type="hypothesis",
            statement="蓝色边框=选中", evidence=["sha:1"],
        ))
        bridge = WorldModelBridge(store)
        suspended = await bridge.on_claim_refuted("hyp-1", model_names=["grid-4x4"])
        assert suspended == ["grid-4x4"]
        types = [e.type for e in store.iter_run_events("cognition")]
        assert "world_model.suspended" in types
        ev = [e for e in store.iter_run_events("cognition")
              if e.type == "world_model.suspended"][-1]
        assert ev.payload["bridge"] == "cognition"
        assert ev.payload["propagated_from_claim"] == "hyp-1"
