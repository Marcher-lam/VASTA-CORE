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
            # 评审修复：原先没有任何规则能置 done——goal_check 不可达，
            # BFS 目标测试因此只能写成恒真断言
            "finish": {"set": {"done": 1}},
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
        signals = MetaSignals(planning_horizon=8, real_action_risk="R3")
        assert decide_meta(signals) is MetaDecision.BUILD
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
        """评审修复：goal 真可达（finish 置 done），断言非恒真。"""
        m = grid_dsl()
        actions = [{"tool": "right"}, {"tool": "down"}, {"tool": "left"},
                   {"tool": "up"}, {"tool": "finish"}]
        plan = plan_bfs(
            m, {"detail": {"row": 0, "col": 0, "done": 0}},
            actions=actions, caps=PlanCaps(max_depth=6),
        )
        assert plan and plan[-1] == {"tool": "finish"}  # 找到真目标
        # 计划在模型内回放确为 goal
        state = m.init_state({"detail": {"row": 0, "col": 0, "done": 0}})
        for action in plan:
            state = m.transition(state, action)
        assert m.outcome(state) == "goal"

    def test_goal_at_exact_max_depth_accepted(self) -> None:
        """评审修复：恰落在 max_depth 的目标路径不再被深度截断丢弃。"""
        m = grid_dsl()
        plan = plan_bfs(
            m, {"detail": {"row": 0, "col": 0, "done": 0}},
            actions=[{"tool": "finish"}], caps=PlanCaps(max_depth=1),
        )
        assert plan == [{"tool": "finish"}]

    def test_max_cost_prunes_expensive_branches(self) -> None:
        """评审修复：max_cost 原先不参与搜索，现在生效（成本剪枝）。"""
        m = grid_dsl()
        cheap = [{"tool": "finish", "cost": 1.0}]
        plan = plan_bfs(
            m, {"detail": {"row": 0, "col": 0, "done": 0}},
            actions=cheap, caps=PlanCaps(max_cost=0.5),
        )
        assert plan == []  # 唯一动作超成本 → 剪除

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


class TestReviewGuards:
    """Epic 4-7 code-review 修复的守卫（沙箱接线/白名单/STOP/留痕/清单）。"""

    def test_stop_decision_reachable(self) -> None:
        """评审修复：MetaDecision.STOP 原为不可达枚举。"""
        assert decide_meta(
            MetaSignals(repeated_prediction_failure=5, has_validated_model=False)
        ) is MetaDecision.STOP

    async def test_meta_decision_emits_event(self) -> None:
        """FR-040：元决策留痕（评审实锤：原 decide_meta 不落事件）。"""
        from vasta_model_lab import emit_meta_decision

        store = FakeStorageAdapter()
        signals = MetaSignals(planning_horizon=8, real_action_risk="R3")
        await emit_meta_decision(store, MetaDecision.BUILD, signals,
                                 reason="长视野+高风险且无验证模型")
        events = list(store.iter_run_events("cognition"))
        assert events[-1].type == "world_model.meta_decision"
        assert events[-1].payload["decision"] == "build"
        assert events[-1].payload["signals"]["planning_horizon"] == 8

    def test_from_import_whitelist_enforced(self) -> None:
        """评审实锤：`from X import Y` 形态原先绕过 import 白名单。"""
        manifest = grid_manifest("evil")
        with pytest.raises(VastaError) as excinfo:
            PythonWorldModel(
                manifest,
                "result = {'x': 1}\nfrom socket import socket\n",
            )
        assert excinfo.value.code == "model_lab.forbidden_import"

    def test_reflection_builtins_rejected(self) -> None:
        """评审修复：getattr/globals/vars 等反射通道入禁止模式。"""
        manifest = grid_manifest("evil2")
        with pytest.raises(VastaError) as excinfo:
            PythonWorldModel(
                manifest, "result = getattr(state, 'keys')()\n"
            )
        assert excinfo.value.code == "model_lab.forbidden_pattern"

    def test_manifest_requires_unknowns_and_coverage(self) -> None:
        """FR-043：unknowns/coverage 必填且非空（原空清单可过）。"""
        with pytest.raises(ValueError):
            WorldModelManifest(
                name="m", version="1", scope="s",
                unknowns=[], coverage=["a"],
            )
        with pytest.raises(ValueError):
            WorldModelManifest(
                name="m", version="1", scope="s",
                unknowns=["u"], coverage=[],
            )

    def test_replay_zero_overlap_fails(self) -> None:
        """评审修复：预测与观察零键重叠 = 回放空转，不再判通过。"""
        m = grid_dsl()
        traj = Trajectory(
            {"detail": {"row": 0, "col": 0}},
            [{"tool": "right"}],
            [{"unrelated_key": 42}],  # 与预测（含 kind）零键交集
            "ongoing",
        )
        report = validate_model(m, [traj])
        assert not report.all_replay_passed

    async def test_sandbox_run_rejects_forbidden_code(self) -> None:
        """评审修复：SandboxExecutor.run 前置静态检查（原先不查）。"""
        executor = SandboxExecutor(timeout_s=2)
        with pytest.raises(VastaError) as excinfo:
            await executor.run("import os\nresult = 1\n", {"state": {}, "action": {}})
        assert excinfo.value.code == "model_lab.forbidden_import"

    async def test_sandbox_timeout_emits_system_event(self) -> None:
        """AD-15：沙箱超时留 system.timeout 事件（评审实锤缺失）。"""
        emitted: list[tuple[str, dict]] = []

        async def emitter(type_: str, payload: dict) -> None:
            emitted.append((type_, payload))

        executor = SandboxExecutor(timeout_s=0.3, emitter=emitter)
        with pytest.raises(VastaError) as excinfo:
            await executor.run(
                "x = 0\nwhile True: x = x + 1\n", {"state": {}, "action": {}}
            )
        assert excinfo.value.code == "sandbox.timeout"
        assert emitted and emitted[0][0] == "system.timeout"

    def test_python_model_wired_to_sandbox(self) -> None:
        """评审实锤：PythonWorldModel 声称沙箱执行实则进程内 exec——
        现在 sandbox= 装配后 transition 走受限子进程。"""
        code = "result = {'col': state['col'] + 1, '_steps': state.get('_steps', 0) + 1}"
        sandboxed = PythonWorldModel(
            grid_manifest("sbx"), code, sandbox=SandboxExecutor(timeout_s=5.0)
        )
        state = sandboxed.init_state({"detail": {"col": 0, "_steps": 0}})
        nxt = sandboxed.transition(state, {"tool": "right"})
        assert nxt["col"] == 1 and nxt["_steps"] == 1

    def test_local_exec_builtins_restricted(self) -> None:
        """受限 builtins：open 静态拦截；iter 等未入白名单的内置在
        运行期 NameError（本地直跑不再挂全量 builtins）。"""
        with pytest.raises(VastaError):
            PythonWorldModel(
                grid_manifest("noio"), "result = {'ok': True}\nopen('x.txt')\n"
            )
        m = PythonWorldModel(
            grid_manifest("noiter"), "result = {'i': iter([1])}\n"
        )
        with pytest.raises(NameError):
            m.transition({"col": 0}, {"tool": "right"})
