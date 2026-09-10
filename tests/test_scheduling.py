"""Story 9.9：定时、事件触发与批量 Run 调度（FR-008，G4）。

cron/事件源二选一；到点触发批量（复用 8.9——每次执行独立 Run）；
plan 族留痕；重试有上限；并发受配额约束（复用 9.8）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from vasta_eval import VastaLabTask
from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.quotas import QuotaEnforcer, QuotaSpec
from vastacore.scheduling import CronSpec, Scheduler, ScheduleSpec


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


def task(task_id: str = "t1") -> VastaLabTask:
    return VastaLabTask(task_id=task_id)


class FakeClock:
    """可推进壁钟（调度测试确定性——AD-15）。"""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now = self.now + timedelta(**kwargs)


class FakeSummary:
    """executor 返回替身（BatchRunSummary 形态）。"""

    def __init__(self, runs: int = 1, success_rate: float = 1.0) -> None:
        self.runs = runs
        self.success_rate = success_rate


def make_executor(calls: list, *, fail_times: int = 0,
                  summary: FakeSummary | None = None):
    """可编程执行器：前 fail_times 次抛错，之后返回 summary。"""

    async def executor(tasks, root):
        calls.append((tuple(t.task_id for t in tasks), root))
        if len(calls) <= fail_times:
            raise RuntimeError(f"exec failure #{len(calls)}")
        return summary or FakeSummary()

    return executor


class TestCronSpec:
    def test_star_every_minute(self) -> None:
        cron = CronSpec("* * * * *")
        assert cron.matches(datetime(2026, 9, 10, 12, 0, tzinfo=UTC))
        assert cron.matches(datetime(2026, 9, 10, 12, 30, tzinfo=UTC))

    def test_step_minutes(self) -> None:
        cron = CronSpec("*/5 * * * *")
        assert cron.matches(datetime(2026, 9, 10, 12, 0, tzinfo=UTC))
        assert cron.matches(datetime(2026, 9, 10, 12, 55, tzinfo=UTC))
        assert not cron.matches(datetime(2026, 9, 10, 12, 3, tzinfo=UTC))

    def test_daily_at_3am(self) -> None:
        cron = CronSpec("0 3 * * *")
        assert cron.matches(datetime(2026, 9, 10, 3, 0, tzinfo=UTC))
        assert not cron.matches(datetime(2026, 9, 10, 15, 0, tzinfo=UTC))

    def test_day_of_week_sunday_zero(self) -> None:
        """cron 惯例：dow 0=周日（2026-09-13 是周日）。"""
        cron = CronSpec("* * * * 0")
        assert cron.matches(datetime(2026, 9, 13, 8, 0, tzinfo=UTC))
        assert not cron.matches(datetime(2026, 9, 14, 8, 0, tzinfo=UTC))

    def test_range_and_list(self) -> None:
        cron = CronSpec("0 9-17 * * 1,3")
        assert cron.matches(datetime(2026, 9, 9, 9, 0, tzinfo=UTC))  # 周三
        assert cron.matches(datetime(2026, 9, 7, 17, 0, tzinfo=UTC))  # 周一
        assert not cron.matches(datetime(2026, 9, 9, 18, 0, tzinfo=UTC))

    def test_next_after(self) -> None:
        cron = CronSpec("*/15 * * * *")
        nxt = cron.next_after(datetime(2026, 9, 10, 12, 7, tzinfo=UTC))
        assert nxt == datetime(2026, 9, 10, 12, 15, tzinfo=UTC)

    def test_bad_expressions_rejected(self) -> None:
        for bad in ("* * * *", "61 * * * *", "* 24 * * *", "*/0 * * * *",
                    "5-1 * * * *", "a * * * *"):
            with pytest.raises(VastaError) as excinfo:
                CronSpec(bad)
            assert excinfo.value.code == "schedule.bad_cron"


class TestScheduleSpec:
    def test_cron_or_event_exactly_one(self) -> None:
        with pytest.raises(VastaError) as e1:  # 都无
            ScheduleSpec(schedule_id="s", tasks=[task()])
        assert e1.value.code == "schedule.bad_spec"
        with pytest.raises(VastaError):  # 都有
            ScheduleSpec(schedule_id="s", cron="* * * * *",
                         event_source="release.transition", tasks=[task()])

    def test_empty_tasks_rejected(self) -> None:
        with pytest.raises(VastaError):
            ScheduleSpec(schedule_id="s", cron="* * * * *", tasks=[])

    def test_bad_cron_rejected_at_construction(self) -> None:
        with pytest.raises(VastaError):
            ScheduleSpec(schedule_id="s", cron="99 * * * *", tasks=[task()])


class TestSchedulerCron:
    async def test_add_leaves_trace(self, store) -> None:
        """AC：调度本身留痕（plan.scheduled——13 族 plan 内）。"""
        clock = FakeClock(datetime(2026, 9, 10, 12, 0, tzinfo=UTC))
        scheduler = Scheduler(store, executor=make_executor([]),
                              clock=clock)
        await scheduler.add(ScheduleSpec(schedule_id="nightly",
                                         cron="0 3 * * *", tasks=[task()]))
        events = [e for e in store.iter_run_events("schedules")
                  if e.type == "plan.scheduled"]
        assert len(events) == 1
        assert events[0].payload["schedule_id"] == "nightly"
        assert events[0].payload["cron"] == "0 3 * * *"

    async def test_due_schedule_fires(self, store) -> None:
        """AC：到点触发批量执行（fake executor——执行面复用 8.9 由
        独立测试锚定）。"""
        clock = FakeClock(datetime(2026, 9, 10, 12, 0, tzinfo=UTC))
        calls: list = []
        scheduler = Scheduler(store, executor=make_executor(calls),
                              clock=clock)
        await scheduler.add(ScheduleSpec(schedule_id="every-min",
                                         cron="* * * * *", tasks=[task("a")],
                                         root="runs/r1"))
        clock.advance(minutes=1)  # 注册后等下一周期（12:00 → 12:01 命中）
        fired = await scheduler.tick()
        assert len(fired) == 1
        assert fired[0].success and fired[0].runs == 1
        assert calls == [(("a",), "runs/r1")]  # 任务清单 + root 透传
        # plan.fired 留痕
        events = [e for e in store.iter_run_events("schedules")
                  if e.type == "plan.fired"]
        assert len(events) == 1
        assert events[0].payload["runs"] == 1

    async def test_not_due_no_fire(self, store) -> None:
        """未到点不触发；到点后触发（时钟推进）。"""
        clock = FakeClock(datetime(2026, 9, 10, 12, 0, tzinfo=UTC))
        calls: list = []
        scheduler = Scheduler(store, executor=make_executor(calls),
                              clock=clock)
        await scheduler.add(ScheduleSpec(schedule_id="at-13",
                                         cron="0 13 * * *", tasks=[task()]))
        assert await scheduler.tick() == []  # 12:00 未到 13:00
        clock.advance(hours=1)
        fired = await scheduler.tick()
        assert len(fired) == 1

    async def test_one_fire_per_tick_no_catchup(self, store) -> None:
        """错过多个周期一次 tick 只触发一次（补跑属 9.10 恢复语义）。"""
        clock = FakeClock(datetime(2026, 9, 10, 12, 0, tzinfo=UTC))
        calls: list = []
        scheduler = Scheduler(store, executor=make_executor(calls),
                              clock=clock)
        await scheduler.add(ScheduleSpec(schedule_id="m",
                                         cron="* * * * *", tasks=[task()]))
        clock.advance(minutes=30)  # 错过 30 个周期
        fired = await scheduler.tick()
        assert len(fired) == 1  # 不补跑
        # 且 next 已重算——再 tick（同分钟内推进 1s 不跨分钟）不重复触发
        clock.advance(seconds=30)
        assert await scheduler.tick() == []

    async def test_executor_reuses_batch_semantics(self, tmp_path) -> None:
        """AC：每次执行独立 Run——默认执行器真绑 run_tasks_as_runs
        （复用 8.9；store 里出现 vlrun-{task_id} 的完整 Run）。"""
        store = SqliteStorage(tmp_path / "s")
        try:
            clock = FakeClock(datetime(2026, 9, 10, 12, 0, tzinfo=UTC))
            scheduler = Scheduler(store, clock=clock)  # 默认 executor
            await scheduler.add(ScheduleSpec(
                schedule_id="real", cron="* * * * *",
                tasks=[VastaLabTask(task_id="lab1")],
                root=str(tmp_path / "runs"),
            ))
            clock.advance(minutes=1)  # 到点
            fired = await scheduler.tick()
            assert fired[0].success
            assert fired[0].runs == 1
            assert isinstance(fired[0].success_rate, float)
            # 独立 Run 落盘（8.9 语义）
            batch_store = SqliteStorage(tmp_path / "runs" / "store")
            try:
                assert list(batch_store.iter_run_events("vlrun-lab1"))
            finally:
                batch_store.close()
        finally:
            store.close()


class TestSchedulerEventSource:
    async def test_event_source_triggers(self, store) -> None:
        """AC：事件源触发——订阅 release.transition 的调度被事件唤起。"""
        calls: list = []
        scheduler = Scheduler(store, executor=make_executor(calls),
                              clock=FakeClock(
                                  datetime(2026, 9, 10, 12, 0, tzinfo=UTC)))
        await scheduler.add(ScheduleSpec(
            schedule_id="on-release", event_source="release.transition",
            tasks=[task("x")]))
        fired = await scheduler.handle_event("release.transition")
        assert len(fired) == 1 and fired[0].success
        # 不匹配的事件类型不触发
        assert await scheduler.handle_event("run.created") == []


class TestRetryPolicy:
    async def test_retry_until_success(self, store) -> None:
        """首次失败重试成功：attempts=2、success=True、单次 plan.fired。"""
        calls: list = []
        scheduler = Scheduler(store, executor=make_executor(
            calls, fail_times=1),
            clock=FakeClock(datetime(2026, 9, 10, 12, 0, tzinfo=UTC)))
        await scheduler.add(ScheduleSpec(
            schedule_id="r", event_source="run.completed",
            tasks=[task()], max_retries=3))
        fired = await scheduler.handle_event("run.completed")
        assert fired[0].success and fired[0].attempts == 2
        assert len(calls) == 2

    async def test_retry_exhaustion_failed(self, store) -> None:
        """AC：重试有上限——耗尽后 plan.fire_failed + 失败记录。"""
        calls: list = []
        scheduler = Scheduler(store, executor=make_executor(
            calls, fail_times=99),
            clock=FakeClock(datetime(2026, 9, 10, 12, 0, tzinfo=UTC)))
        await scheduler.add(ScheduleSpec(
            schedule_id="doomed", event_source="run.completed",
            tasks=[task()], max_retries=2))
        fired = await scheduler.handle_event("run.completed")
        assert not fired[0].success
        assert fired[0].attempts == 3  # 1 首次 + 2 重试
        assert len(calls) == 3
        failed = [e for e in store.iter_run_events("schedules")
                  if e.type == "plan.fire_failed"]
        assert len(failed) == 1
        assert failed[0].payload["max_retries"] == 2

    async def test_zero_retries_single_attempt(self, store) -> None:
        calls: list = []
        scheduler = Scheduler(store, executor=make_executor(
            calls, fail_times=1),
            clock=FakeClock(datetime(2026, 9, 10, 12, 0, tzinfo=UTC)))
        await scheduler.add(ScheduleSpec(
            schedule_id="once", event_source="run.completed",
            tasks=[task()], max_retries=0))
        fired = await scheduler.handle_event("run.completed")
        assert not fired[0].success and fired[0].attempts == 1


class TestQuotaIntegration:
    async def test_rate_limit_rejects_second_fire(self, store) -> None:
        """AC：并发受配额约束（复用 9.8）——同窗口第二次触发被速率闸拒。"""
        enforcer = QuotaEnforcer(store)
        await enforcer.configure("t-default", "p-default",
                                 QuotaSpec(requests_per_min=1))
        calls: list = []
        scheduler = Scheduler(store, enforcer=enforcer,
                              executor=make_executor(calls),
                              clock=FakeClock(
                                  datetime(2026, 9, 10, 12, 0, tzinfo=UTC)))
        # 两个调度订阅同一事件——同一次 handle_event 内先后触发
        await scheduler.add(ScheduleSpec(
            schedule_id="first", event_source="run.completed",
            tasks=[task()], max_retries=0))
        await scheduler.add(ScheduleSpec(
            schedule_id="second", event_source="run.completed",
            tasks=[task()], max_retries=0))
        fired = await scheduler.handle_event("run.completed")
        assert fired[0].success  # 第 1 次过闸
        assert not fired[1].success  # 第 2 次超速率（1/min）
        assert "quota.rate_limited" in (fired[1].error or "")
        assert len(calls) == 1  # 被拒的未执行
        failed = [e for e in store.iter_run_events("schedules")
                  if e.type == "plan.fire_failed"]
        assert len(failed) == 1
        assert failed[0].payload["schedule_id"] == "second"

    async def test_concurrency_scope_wraps_execution(self, store) -> None:
        """执行期间持并发闸——作用域内并发计数可见。"""
        enforcer = QuotaEnforcer(store)
        await enforcer.configure("t-default", "p-default",
                                 QuotaSpec(max_concurrent=1))
        seen_inflight: list[int] = []

        async def executor(tasks, root):
            key = ("t-default", "p-default")
            seen_inflight.append(enforcer._inflight.get(key, 0))  # noqa: SLF001
            return FakeSummary()

        scheduler = Scheduler(store, enforcer=enforcer, executor=executor,
                              clock=FakeClock(
                                  datetime(2026, 9, 10, 12, 0, tzinfo=UTC)))
        await scheduler.add(ScheduleSpec(schedule_id="c",
                                         event_source="run.completed",
                                         tasks=[task()]))
        fired = await scheduler.handle_event("run.completed")
        assert fired[0].success
        assert seen_inflight == [1]  # 执行中在闸内
