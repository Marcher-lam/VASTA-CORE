"""Story 8.1：AgentSession 高层 SDK（G1 接入面，FR-002，SM-5）。

六段链对开发者透明：act() 对网关注册工具自动走 execute_contracted；
无契约模板 fail-closed；未注册工具走观察路径；同 seed 字节级复现。
"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import (
    Action,
    DryRunResult,
    EnvironmentAdapter,
    Observation,
    ToolAdapter,
    ToolManifest,
    ToolResult,
)
from vastacore.agent import AgentSession

# ---- 被接入方（「外部团队」自带的 env 与工具）----

class TodoEnv(EnvironmentAdapter):
    """演示用最小环境：一个待办项可标记。"""

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
    """写工具：标记待办状态。"""

    protocol_version = "0.1.0"
    manifest = ToolManifest(
        name="set_status", version="1.0", risk="R2",
        read_only=False, idempotent=True, supports_read_back=True,
    )

    async def execute(self, action, idempotency_key=None):
        return ToolResult(ok=True, detail={"status": action.args.get("status")})

    async def dry_run(self, action):
        return DryRunResult(would_execute=True)

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


class TestAgentSession:
    async def test_registered_tool_auto_walks_six_segments(self, tmp_path) -> None:
        """AC：写动作自动走六段链——开发者不手工编排核验。"""
        session = await make_session(tmp_path)
        async with session:
            await session.start()
            await session.reset()
            observations = await session.act(
                Action(tool="set_status", args={"status": "done"})
            )
            assert observations  # 有观察返回
            events = session.events()
            types = [e.type for e in events]
            assert "action.contracted" in types
            assert "action.executed" in types
            assert "verification.passed" in types  # read_back 核验自动过
            # 六段链审计完整（NFR-001 工具）
            from vasta_contracts import audit_six_segment

            audit = audit_six_segment(events)
            assert audit.chains and audit.chains[-1].status == "complete"

    async def test_missing_template_fails_closed(self, tmp_path) -> None:
        """AC/AD-12：注册工具无契约模板 → 拒执行，不降级裸跑。"""
        session = await make_session(tmp_path, contracts={})  # 无模板
        async with session:
            await session.start()
            await session.reset()
            with pytest.raises(VastaError) as excinfo:
                await session.act(Action(tool="set_status", args={"status": "done"}))
            assert excinfo.value.code == "sdk.contract_template_missing"
            # 未产生执行事件（拒之门外）
            types = [e.type for e in session.events()]
            assert "action.executed" not in types

    async def test_unregistered_tool_takes_observation_path(self, tmp_path) -> None:
        """未注册网关的工具 → env.step 观察路径（无六段链要求）。"""
        session = await make_session(tmp_path)
        async with session:
            await session.start()
            await session.reset()
            observations = await session.act(Action(tool="set_status",
                                                    args={"status": "done"}),
                                             use_gateway=False)
            assert observations
            types = [e.type for e in session.events()]
            assert "action.contracted" not in types
            assert "observation.transition" in types

    async def test_same_seed_byte_identical_replay(self, tmp_path) -> None:
        """AC：同 seed 字节级复现（两个独立 store 根）。"""
        run_ids = []
        for sub in ("r1", "r2"):
            session = await AgentSession.create(
                env=TodoEnv(), tools=[SetStatusTool()],
                contracts={"set_status": STATUS_CONTRACT},
                root=tmp_path / sub, seed=11, budget={"max_actions": 5},
            )
            async with session:
                await session.start()
                await session.reset()
                await session.act(Action(tool="set_status", args={"status": "done"}))
                run_ids.append((session.run_id, session.normalized_stream()))
        assert run_ids[0][1] == run_ids[0][1]  # 自身稳定
        assert run_ids[0][1] == run_ids[1][1]  # 两根目录逐字节一致

    async def test_session_closes_store_exactly_once(self, tmp_path) -> None:
        session = await make_session(tmp_path)
        await session.start()
        await session.complete()
        session.close()
        assert session.store_closed  # 幂等关闭
        session.close()

    async def test_summary_reports_run(self, tmp_path) -> None:
        session = await make_session(tmp_path)
        async with session:
            await session.start()
            await session.reset()
            await session.act(Action(tool="set_status", args={"status": "done"}))
            await session.complete()
            summary = await session.summary()
            assert summary.run_id == session.run_id
            assert summary.events >= 8
            assert summary.state == "completed"


class TestContractTemplate:
    def test_template_validation_requires_segments(self) -> None:
        """模板本身缺必填段 → 构造期即拒（不等到执行才发现）。"""
        with pytest.raises(VastaError) as excinfo:
            AgentSession.contract_from_template(
                {"tool": "set_status", "risk": "R2"},  # 缺全部段
                Action(tool="set_status", args={}),
            )
        assert excinfo.value.code == "contract.incomplete"
