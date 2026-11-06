"""Story 8.14：Middleware 接入形态（FR-002 第四形态，蓝图 §18.5-2）。

既有编排器零改造：decide 保持 dict→dict 签名（零 VastaCore 类型），
动作自动走六段链；核验偏差记录不抛（有界恢复引擎内管）；fail-closed
异常原样穿透。
"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import (
    DryRunResult,
    EnvironmentAdapter,
    Observation,
    ToolAdapter,
    ToolManifest,
    ToolResult,
)
from vastacore.execution.agent import AgentSession
from vastacore.execution.middleware import VastaMiddleware

# ---- 被接入方（与 test_agent_sdk 同款最小 env/工具——自包含惯例）----

class TodoEnv(EnvironmentAdapter):
    protocol_version = "0.1.0"

    def __init__(self) -> None:
        self.status = "pending"

    async def reset(self, seed=None):
        self.status = "pending"
        return Observation(kind="decision", detail={"status": self.status},
                           available_actions=["read_status", "set_status"])

    async def observe(self):
        return Observation(kind="decision", detail={"status": self.status})

    async def execute(self, action):
        if action.tool == "set_status":
            self.status = action.args.get("status", "done")
        return [
            Observation(kind="transition", detail={"status": self.status}),
            Observation(kind="decision", detail={"status": self.status}),
        ]

    async def status(self):
        class S:
            running = True
        return S()


class SetStatusTool(ToolAdapter):
    protocol_version = "0.1.0"
    manifest = ToolManifest(
        name="set_status", version="1.0", risk="R2",
        read_only=False, idempotent=True, supports_read_back=True,
    )

    def __init__(self) -> None:
        self._results: dict[str, ToolResult] = {}

    async def execute(self, action, idempotency_key=None):
        if idempotency_key in self._results:
            return self._results[idempotency_key].model_copy(update={"replayed": True})
        result = ToolResult(ok=True, detail={"status": action.args.get("status")})
        self._results[idempotency_key] = result
        return result

    async def dry_run(self, action):
        return DryRunResult(allowed=True)

    async def read_back(self, action, result):
        return Observation(kind="decision", detail={"status": result.detail["status"]})

    async def compensate(self, action, result):
        return ToolResult(ok=True, detail={"compensated": True})


STATUS_CONTRACT = dict(
    tool="set_status",
    goal="标记待办为完成",
    preconditions=["status=pending"],
    prediction={"changes": ["status=done"], "invariants": ["item count unchanged"]},
    success_criteria=["read-back status=done"],
    failure_criteria=["status unchanged"],
    verify_with=["read_back"],
    timeout_ms=5000,
)


async def make_session(tmp_path, *, contracts=None, seed=7) -> AgentSession:
    return await AgentSession.create(
        env=TodoEnv(),
        tools=[SetStatusTool()],
        contracts=contracts if contracts is not None else {"set_status": STATUS_CONTRACT},
        root=tmp_path / "store",
        seed=seed,
        budget={"max_actions": 10},
    )


class TestMiddleware:
    async def test_wrapped_decide_walks_six_segments(self, tmp_path) -> None:
        """AC：decide 纯 dict 进出，动作自动六段链（与 SDK 同证据口径）。"""
        session = await make_session(tmp_path)
        mw = VastaMiddleware(session)

        async def decide(obs: dict) -> dict:
            assert isinstance(obs, dict)  # 观察 dict 喂入
            if obs["detail"]["status"] == "pending":
                return {"tool": "set_status", "args": {"status": "done"}}
            return {"tool": "read_status"}

        wrapped = mw.wrap(decide)
        async with session:
            await session.start()
            await session.reset()
            obs = await mw.observe_dict()
            await wrapped(obs)
            types = [e.type for e in session.events()]
            assert "action.contracted" in types
            assert "action.executed" in types
            assert "verification.passed" in types
            assert mw.last_verdict == "passed"

    async def test_deviation_recorded_not_raised(self, tmp_path) -> None:
        """偏差不向用户循环抛——verdicts 记录（FR-037 有界恢复引擎内管）。

        构造：契约预期 status=done，实参 status=blocked → read_back
        预期变化不匹配 → verification.deviated。"""
        session = await make_session(tmp_path)
        mw = VastaMiddleware(session)

        async def decide(obs: dict) -> dict:
            return {"tool": "set_status", "args": {"status": "blocked"}}

        async with session:
            await session.start()
            await session.reset()
            verdicts = await mw.run(decide, steps=1)  # 不抛——循环可继续
            assert verdicts == ["deviated"]
            assert mw.last_verdict == "deviated"
            assert "verification.deviated" in [e.type for e in session.events()]

    async def test_fail_closed_passthrough(self, tmp_path) -> None:
        """AD-12 穿透：注册工具无模板 → sdk.contract_template_missing 原样抛。"""
        session = await make_session(tmp_path, contracts={})
        mw = VastaMiddleware(session)
        async with session:
            await session.start()
            await session.reset()
            with pytest.raises(VastaError) as excinfo:
                await mw.execute_action({"tool": "set_status",
                                         "args": {"status": "done"}})
            assert excinfo.value.code == "sdk.contract_template_missing"
            assert "action.executed" not in [e.type for e in session.events()]

    async def test_action_shape_rejected_before_chain(self, tmp_path) -> None:
        """缺 tool 键的决策产物在本层即拒（不进链、不耗预算）。"""
        session = await make_session(tmp_path)
        mw = VastaMiddleware(session)
        async with session:
            await session.start()
            await session.reset()
            with pytest.raises(VastaError) as excinfo:
                await mw.execute_action({"args": {"status": "done"}})
            assert excinfo.value.code == "middleware.action_shape"
            with pytest.raises(VastaError) as excinfo2:
                await mw.execute_action("set_status")  # type: ignore[arg-type]
            assert excinfo2.value.code == "middleware.action_shape"

    async def test_run_respects_step_bound_and_observation_path(self, tmp_path
                                                                ) -> None:
        """run() 有界：steps 用尽即停；未注册工具走观察路径（无核验记录）。"""
        session = await make_session(tmp_path)
        mw = VastaMiddleware(session)

        async def decide(obs: dict) -> dict:
            return {"tool": "read_status"}  # 未注册 → env.step 观察路径

        async with session:
            await session.start()
            await session.reset()
            verdicts = await mw.run(decide, steps=3)
            assert len(verdicts) == 3
            assert all(v == "no_verification" for v in verdicts)
            assert mw.verdicts == []  # 观察路径不产核验结论
