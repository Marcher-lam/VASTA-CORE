"""Story 9.7：契约预留段激活——事务批次（FR-038，G3）。

多步写操作要么全成（settled）、要么逆序补偿（aborted）；
dry-run 整体门；幂等键跨批次稳定（AD-11）。
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
from vastacore import AgentSession
from vastacore.governance.transactions import TransactionBatch, execute_batch

# ---- 测试替身 ----

class LedgerEnv(EnvironmentAdapter):
    protocol_version = "0.1.0"

    def __init__(self) -> None:
        self.entries: list[str] = []

    async def reset(self, seed=None):
        return Observation(kind="decision", detail={"entries": []})

    async def observe(self):
        return Observation(kind="decision", detail={"entries": self.entries})

    async def execute(self, action):
        self.entries.append(f"{action.tool}:{action.args.get('id', '')}")
        return [Observation(kind="transition", detail={}),
                Observation(kind="decision", detail={})]

    async def status(self):
        class S:
            running = True
        return S


class StepTool(ToolAdapter):
    """可配置成败的多步工具——compensate 记录留痕。"""

    protocol_version = "0.1.0"

    def __init__(self, name: str = "step", fail_on: set[str] | None = None):
        self._fail_on = fail_on or set()
        self.compensations: list[str] = []
        manifest = ToolManifest(
            name=name, version="1.0", risk="R2", read_only=False,
            idempotent=True, supports_dry_run=True, supports_read_back=True,
        )
        self.manifest = manifest

    async def execute(self, action, idempotency_key=None):
        step_id = action.args.get("id", "")
        if step_id in self._fail_on:
            raise RuntimeError(f"step {step_id} intentionally failed")
        return ToolResult(ok=True, detail={"id": step_id, "done": True})

    async def dry_run(self, action):
        return DryRunResult(allowed=True)

    async def read_back(self, action, result):
        return Observation(kind="decision", detail=dict(result.detail))

    async def compensate(self, action, result):
        self.compensations.append(f"comp:{action.args.get('id', '')}")
        return ToolResult(ok=True, detail={"compensated": True})


CONTRACT = dict(
    goal="测试事务批次",
    preconditions=["环境就绪"],
    prediction={"changes": ["done=True"], "invariants": ["环境不变"]},
    success_criteria=["done=True"],
    failure_criteria=["error"],
    verify_with=["read_back"],
    timeout_ms=5000,
)


async def make_session(tmp_path, tool: StepTool, name: str = "step") -> AgentSession:
    return await AgentSession.create(
        env=LedgerEnv(), tools=[tool],
        contracts={name: CONTRACT},
        root=tmp_path, seed=1,
    )


class TestTransactionBatch:
    async def test_all_success_settled(self, tmp_path) -> None:
        """AC：全成 → transaction.settled。"""
        tool = StepTool()
        session = await make_session(tmp_path, tool)
        async with session:
            await session.start()
            await session.reset()
            batch = TransactionBatch(batch_id="tx-1", steps=[
                {"tool": "step", "args": {"id": "a"}},
                {"tool": "step", "args": {"id": "b"}},
                {"tool": "step", "args": {"id": "c"}},
            ])
            result = await execute_batch(session, batch)
            assert result.status == "settled"
            assert len(result.executed) == 3
            assert result.compensated == []
            assert tool.compensations == []
            types = [e.type for e in session.events()]
            assert "action.batch_settled" in types

    async def test_mid_failure_compensates_reverse(self, tmp_path) -> None:
        """AC：中步失败 → 逆序补偿已成功步 → transaction.aborted。"""
        tool = StepTool(fail_on={"b"})  # b 步失败
        session = await make_session(tmp_path, tool)
        async with session:
            await session.start()
            await session.reset()
            batch = TransactionBatch(batch_id="tx-2", steps=[
                {"tool": "step", "args": {"id": "a"}},
                {"tool": "step", "args": {"id": "b"}},  # 失败
                {"tool": "step", "args": {"id": "c"}},  # 不执行
            ])
            result = await execute_batch(session, batch)
            assert result.status == "aborted"
            assert result.executed == ["a"]  # 只有 a 成功
            assert result.compensated == ["a"]  # 逆序补偿 a
            assert tool.compensations == ["comp:a"]  # c 未执行不补偿
            types = [e.type for e in session.events()]
            assert "action.batch_aborted" in types

    async def test_empty_batch_rejected(self, tmp_path) -> None:
        tool = StepTool()
        session = await make_session(tmp_path, tool)
        async with session:
            await session.start()
            await session.reset()
            batch = TransactionBatch(batch_id="tx-empty", steps=[])
            with pytest.raises(VastaError):
                await execute_batch(session, batch)

    async def test_events_logged_per_step(self, tmp_path) -> None:
        """每步 transaction.step_executed 留痕。"""
        tool = StepTool()
        session = await make_session(tmp_path, tool)
        async with session:
            await session.start()
            await session.reset()
            batch = TransactionBatch(batch_id="tx-3", steps=[
                {"tool": "step", "args": {"id": "x"}},
                {"tool": "step", "args": {"id": "y"}},
            ])
            await execute_batch(session, batch)
            step_events = [e for e in session.events()
                           if e.type == "action.batch_step_executed"]
            assert len(step_events) == 2

    async def test_batch_id_stable_keys(self, tmp_path) -> None:
        """幂等键 batch_id:step_N 前缀稳定（AD-11）。"""
        tool = StepTool()
        session = await make_session(tmp_path, tool)
        async with session:
            await session.start()
            await session.reset()
            batch = TransactionBatch(batch_id="idem-tx", steps=[
                {"tool": "step", "args": {"id": "s1"}},
            ])
            from vastacore.governance.transactions import _step_idempotency_key

            key = _step_idempotency_key(batch, 0)
            assert key.startswith("idem-tx:step_0:")


class TestReviewFixes:
    """Epic 9 G1-G3 评审修复锚定（快道推进/引擎离场/dry-run 门/补偿留痕）。"""

    async def test_engine_departure_signals_failure(self, tmp_path) -> None:
        """评审缺口 G7：act 不抛但引擎离场 started → 步骤判失败并补偿
        （恢复掩盖偏差——「不抛≠成功」的引擎信号面）。"""
        from vasta_runtime.state import RunState

        tool = StepTool()
        session = await make_session(tmp_path, tool)
        async with session:
            await session.start()
            await session.reset()
            real_act = session.act
            calls = {"n": 0}

            async def act_then_depart(action):
                result = await real_act(action)
                calls["n"] += 1
                if calls["n"] == 1:  # 第一步正常返回但引擎离场
                    session._engine._state = RunState.FAILED  # noqa: SLF001
                return result

            session.act = act_then_depart  # type: ignore[method-assign]
            batch = TransactionBatch(batch_id="tx-dep", steps=[
                {"tool": "step", "args": {"id": "a"}},
                {"tool": "step", "args": {"id": "b"}},
            ])
            result = await execute_batch(session, batch)
            assert result.status == "aborted"
            assert result.failed_step == "step"  # 第一步即判失败
            assert result.executed == []
            types = [e.type for e in session.events()]
            assert "action.batch_step_failed" in types

    async def test_unregistered_tool_rejected(self, tmp_path) -> None:
        """评审修复：未注册工具拒整批（dry-run fail-closed——曾静默放行）。"""
        tool = StepTool()
        session = await make_session(tmp_path, tool)
        async with session:
            await session.start()
            await session.reset()
            batch = TransactionBatch(batch_id="tx-ghost", steps=[
                {"tool": "ghost.tool", "args": {}},
            ])
            result = await execute_batch(session, batch)
            assert result.status == "dry_run_rejected"
            assert result.failed_step == "ghost.tool"

    async def test_dry_run_exception_rejected(self, tmp_path) -> None:
        """评审修复：dry_run 抛异常 → 整批拒（fail-closed，不裸逃）。"""

        class ExplodingDryRun(StepTool):
            async def dry_run(self, action):
                raise RuntimeError("dry-run backend down")

        tool = ExplodingDryRun()
        session = await make_session(tmp_path, tool)
        async with session:
            await session.start()
            await session.reset()
            batch = TransactionBatch(batch_id="tx-boom", steps=[
                {"tool": "step", "args": {"id": "a"}},
            ])
            result = await execute_batch(session, batch)
            assert result.status == "dry_run_rejected"
            assert result.failed_step == "step"

    async def test_compensation_failure_leaves_trace(self, tmp_path) -> None:
        """评审修复：补偿失败不再静默——事件留痕 + 结果字段可审计。"""

        class BadCompensate(StepTool):
            async def compensate(self, action, result):
                raise RuntimeError("compensation backend down")

        tool = BadCompensate(fail_on={"b"})
        session = await make_session(tmp_path, tool)
        async with session:
            await session.start()
            await session.reset()
            batch = TransactionBatch(batch_id="tx-comp-fail", steps=[
                {"tool": "step", "args": {"id": "a"}},
                {"tool": "step", "args": {"id": "b"}},  # 失败步
            ])
            result = await execute_batch(session, batch)
            assert result.status == "aborted"
            assert result.executed == ["a"]
            assert result.compensated == []
            assert result.compensation_failed == ["a"]  # 悬空步可审计
            types = [e.type for e in session.events()]
            assert "action.batch_step_compensation_failed" in types
            aborted = [e for e in session.events()
                       if e.type == "action.batch_aborted"][-1]
            assert aborted.payload["compensation_failed"] == ["a"]
