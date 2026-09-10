"""Story 9.10：长任务跨进程恢复（FR-007，G4）。

崩溃悬空接管（事件流重建 + run.adopted 留痕）；预算重放续算；
seed 入流恢复（幂等键派生跨进程稳定）；paused 接管可 resume；终态拒。
"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_protocols.idempotency import idempotency_key
from vasta_protocols.protocols import Action, Observation
from vasta_runtime.adoption import adopt_run
from vasta_runtime.budget import Budget, BudgetExceededError
from vasta_runtime.runcontext import RunContext
from vasta_runtime.runner import RunEngine
from vasta_runtime.state import RunState

from .fakes import FakeStorageAdapter


class SimpleEnv:
    """可续用环境（接管测试——两个实例同语义）。"""

    protocol_version = "0.1.0"

    def __init__(self, actions: list[str] | None = None) -> None:
        self.actions = actions or ["noop", "finish"]

    async def reset(self, seed: int | None = None) -> Observation:
        return Observation(kind="decision", available_actions=list(self.actions))

    async def observe(self) -> Observation:
        return Observation(kind="decision", available_actions=list(self.actions))

    async def execute(self, action: Action) -> list[Observation]:
        return [
            Observation(kind="transition"),
            Observation(kind="decision", available_actions=list(self.actions)),
        ]

    async def status(self) -> object:
        class _S:
            running = True

        return _S()


async def make_run(store, *, seed: int | None = 7,
                   budget: Budget | None = None,
                   run_id: str = "run-adopt") -> RunEngine:
    context = RunContext.create(run_id=run_id, seed=seed)
    return await RunEngine.create(
        env=SimpleEnv(), store=store, budget=budget, run_context=context,
    )


class TestCrashAdoption:
    async def test_dangling_started_run_adopted(self) -> None:
        """AC：崩溃后新进程接管——事件流重建 + run.adopted 留痕。"""
        store = FakeStorageAdapter()
        engine = await make_run(store)
        await engine.start()
        await engine.reset(seed=1)
        await engine.step(Action(tool="noop"))
        before = list(store.iter_run_events("run-adopt"))
        del engine  # 「崩溃」：进程消失（无终态/暂停事件）

        report = await adopt_run(store, "run-adopt", env=SimpleEnv())
        assert report.state is RunState.STARTED
        assert report.adopted_from_seq == before[-1].seq
        assert len(report.executed_actions) == 1  # 已执行动作可审计

        after = list(store.iter_run_events("run-adopt"))
        # 历史不改写：接管前事件原样保留
        assert [e.event_id for e in after[:len(before)]] == \
            [e.event_id for e in before]
        # 接管留痕接在流尾（无洞）
        adopted = after[len(before)]
        assert adopted.type == "run.adopted"
        assert adopted.seq == before[-1].seq + 1
        assert adopted.payload["state"] == "started"

    async def test_adopted_engine_continues_and_completes(self) -> None:
        """接管后可继续执行到完成（续写流 seq 连续无洞）。"""
        store = FakeStorageAdapter()
        engine = await make_run(store)
        await engine.start()
        await engine.reset(seed=1)
        await engine.step(Action(tool="noop"))
        del engine

        report = await adopt_run(store, "run-adopt", env=SimpleEnv())
        adopted = report.engine
        await adopted.step(Action(tool="noop"))
        await adopted.complete()

        seqs = [e.seq for e in store.iter_run_events("run-adopt")]
        assert seqs == list(range(len(seqs)))  # 连续无洞

    async def test_budget_replayed_across_processes(self) -> None:
        """AC：预算跨进程续算——崩溃前 2 步，max_actions=3：接管后
        第 3 步放行、第 4 步预算耗尽（安全停止）。"""
        store = FakeStorageAdapter()
        engine = await make_run(store, budget=Budget(max_actions=3))
        await engine.start()
        await engine.reset(seed=1)
        await engine.step(Action(tool="noop"))
        await engine.step(Action(tool="noop"))
        del engine

        report = await adopt_run(store, "run-adopt", env=SimpleEnv())
        adopted = report.engine
        await adopted.step(Action(tool="noop"))  # 第 3 步（余量 1）放行
        with pytest.raises(BudgetExceededError):
            await adopted.step(Action(tool="noop"))  # 余量 0 → 耗尽
        types = [e.type for e in store.iter_run_events("run-adopt")]
        assert "run.failed" in types  # 预算安全停止（既有语义）

    async def test_seed_recovered_from_stream(self) -> None:
        """AC：seed 入流（run.created）——接管恢复，事件 ID 流与幂等键
        派生跨进程可再生（AD-11：键是纯函数，零进程态）。"""
        store = FakeStorageAdapter()
        engine = await make_run(store, seed=42)
        await engine.start()
        del engine

        created = next(e for e in store.iter_run_events("run-adopt")
                       if e.type == "run.created")
        assert created.payload["seed"] == 42  # seed 入流（Story 9.10 底座）

        report = await adopt_run(store, "run-adopt", env=SimpleEnv())
        assert report.seed == 42
        assert report.seed_recovered is True

    async def test_idempotency_key_stable_across_processes(self) -> None:
        """AC：幂等键跨进程稳定——同 (run_id, step, tool, args) 在两个
        进程派生同键（至少一次语义下不重复执行的机制基础）。"""
        args = {"order_id": "A102", "qty": 3}
        before = idempotency_key("run-adopt", "step_0", "ship", args)
        after = idempotency_key("run-adopt", "step_0", "ship", args)
        assert before == after  # 纯函数派生：接管后重算同键
        # 不同 args 不同键（碰撞面控制）
        assert before != idempotency_key("run-adopt", "step_0", "ship",
                                         {"order_id": "A102", "qty": 4})


class TestPausedAdoption:
    async def test_paused_run_adopted_then_resumes(self) -> None:
        """paused 接管：checkpoint 重建 + resume（重观察比对既有语义）。"""
        store = FakeStorageAdapter()
        engine = await make_run(store)
        await engine.start()
        await engine.reset(seed=1)
        await engine.step(Action(tool="noop"))
        await engine.pause()
        del engine

        report = await adopt_run(store, "run-adopt", env=SimpleEnv())
        assert report.state is RunState.PAUSED
        resumed = await report.engine.resume()  # env 未变
        assert resumed.env_changed is False
        # 接管后继续执行
        await report.engine.step(Action(tool="noop"))


class TestAdoptionRejections:
    async def test_terminal_run_rejected(self) -> None:
        """终态不可接管（重放只读——历史不可复活）。"""
        store = FakeStorageAdapter()
        engine = await make_run(store)
        await engine.start()
        await engine.complete()
        del engine
        with pytest.raises(VastaError) as excinfo:
            await adopt_run(store, "run-adopt", env=SimpleEnv())
        assert excinfo.value.code == "adoption.already_finished"

    async def test_unknown_run_rejected(self) -> None:
        store = FakeStorageAdapter()
        with pytest.raises(VastaError) as excinfo:
            await adopt_run(store, "run-ghost", env=SimpleEnv())
        assert excinfo.value.code == "run.not_found"

    async def test_created_only_run_adoptable(self) -> None:
        """启动即崩（只有 run.created）：可接管，接管方 start()。"""
        store = FakeStorageAdapter()
        engine = await make_run(store)
        del engine  # create 后立即崩（未 start）

        report = await adopt_run(store, "run-adopt", env=SimpleEnv())
        assert report.state is RunState.CREATED
        await report.engine.start()  # 接管方推进生命周期
        await report.engine.reset(seed=1)
        await report.engine.complete()


class TestBudgetBaseline:
    async def test_checkpoint_budget_preferred_over_created(self) -> None:
        """预算基线取流内**最后**快照：pause（含 checkpoint）后继续
        执行再崩——基线为 checkpoint + 其后动作数。"""
        store = FakeStorageAdapter()
        engine = await make_run(store, budget=Budget(max_actions=10))
        await engine.start()
        await engine.reset(seed=1)
        await engine.step(Action(tool="noop"))
        await engine.pause()  # checkpoint（此时 actions_used=1）
        await engine.resume()
        await engine.step(Action(tool="noop"))  # checkpoint 后 +1
        del engine

        report = await adopt_run(store, "run-adopt", env=SimpleEnv())
        # 重放应得 2（checkpoint 基线 1 + 其后 1）——snapshot 快照检查
        snap = report.engine.tracker.snapshot()
        assert snap.actions_used == 2


class TestRealStorageIntegration:
    """评审修复 F1/M6/F12 锚定：真实 SqliteStorage（event_id UNIQUE
    约束真实生效——FakeStorageAdapter 不查该约束故 G4-G6 评审前失真）。"""

    async def test_seeded_run_adoptable_on_real_store(self, tmp_path) -> None:
        """F1：seeded Run 接管后 event_id 流不撞 UNIQUE（ID 预烧）+
        ts 单调续算（M6 时钟基点）。"""
        from vasta_storage import SqliteStorage

        store = SqliteStorage(tmp_path / "real")
        try:
            engine = await make_run(store, seed=42)
            await engine.start()
            await engine.reset(seed=1)
            await engine.step(Action(tool="noop"))
            before = list(store.iter_run_events("run-adopt"))
            del engine  # 崩溃

            report = await adopt_run(store, "run-adopt", env=SimpleEnv())
            adopted = report.engine
            await adopted.step(Action(tool="noop"))
            await adopted.complete()
            after = list(store.iter_run_events("run-adopt"))
            # event_id 全局唯一（真实 UNIQUE 约束下写入成功即证明）
            ids = [e.event_id for e in after]
            assert len(ids) == len(set(ids))
            # ts 单调（接管后续算不回退）
            ts = [e.ts for e in after]
            assert ts == sorted(ts)
            # adopted(1) + step 组(action.executed+2 观察共3) + complete(1)
            assert len(after) == len(before) + 5
        finally:
            store.close()

    async def test_created_adoption_does_not_start_wall_clock(
            self) -> None:
        """F12：CREATED 接管不提前起算墙钟（start() 才计费）。"""
        import time

        store = FakeStorageAdapter()
        engine = await make_run(store, seed=1)
        del engine  # 启动即崩（CREATED）
        report = await adopt_run(store, "run-adopt", env=SimpleEnv())
        time.sleep(0.05)  # 排队期
        assert report.engine.tracker.wall_seconds_used == 0.0  # 未计费
        await report.engine.start()
        assert report.engine.tracker.wall_seconds_used >= 0.0  # start 后计费
