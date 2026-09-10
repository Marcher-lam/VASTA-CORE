"""定时、事件触发与批量 Run 调度（Story 9.9，FR-008，G4）。

- 调度配置（ScheduleSpec）：五字段 cron **或** 事件源（event_source——
  观察到该事件类型即触发），恰一（fail-closed：都无/都有拒）；
- 触发执行（Scheduler.tick / handle_event）：到点/匹配的调度过 9.8
  配额闸（速率 + 并发作用域）后执行批量任务清单（复用 8.9
  ``run_tasks_as_runs``——每次执行独立 Run）；
- 留痕（plan 族——AD-5 13 族封闭集内；AC 字面 schedule.created/fired
  的实现形态）：``plan.scheduled``（配置）/ ``plan.fired``（触发成功，
  携带批量汇总）/ ``plan.fire_failed``（重试耗尽，携带末次错误）；
- 触发失败重试有上限（max_retries；MVP 同步立即重试——生产应为
  退避，注释披露）；
- 执行器可注入（executor——测试替身/替换执行面零改动）；
- 时钟可注入（AD-15）；调度态（next_fire/attempt）为进程内——
  跨进程恢复属 Story 9.10。
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_eval import VastaLabTask
from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

_SCHEDULES_RUN = "schedules"

#: cron 字段域：(min, max)
_CRON_FIELDS = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day_of_month", 1, 31),
    ("month", 1, 12),
    ("day_of_week", 0, 6),  # 0=周日（cron 惯例）
)

#: next_after 扫描上限（分钟）——400 天（防畸形表达式死循环）。
_MAX_SCAN_MINUTES = 400 * 24 * 60


def _parse_field(expr: str, low: int, high: int) -> set[int]:
    """单字段解析：* / a / a-b / a-b/n / a,b（组合）→ 值集合。"""
    values: set[int] = set()
    for part in expr.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)
            if step < 1:
                raise ValueError(f"step 须 ≥1：{step_s!r}")
        if part == "*":
            start, end = low, high
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        if start < low or end > high or start > end:
            raise ValueError(f"{part!r} 超出 [{low},{high}] 或区间倒置")
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError("空字段")
    return values


class CronSpec:
    """五字段 cron（分 时 日 月 周）——``*``/``a``/``a-b``/``a-b/n``/``a,b``。

    简化（注释披露）：日/周同为限定时按 AND（标准 cron 的 dom|dow OR
    规则未实现——调度语义显式化，避免歧义）。"""

    def __init__(self, expression: str) -> None:
        parts = expression.split()
        if len(parts) != 5:
            raise VastaError(
                code="schedule.bad_cron",
                message=f"cron 须为五个空格分隔字段，得到 {expression!r}",
            )
        try:
            self._sets = tuple(
                _parse_field(part, low, high)
                for part, (_, low, high) in zip(parts, _CRON_FIELDS,
                                                strict=True)
            )
        except ValueError as exc:
            raise VastaError(
                code="schedule.bad_cron",
                message=f"cron 字段非法（{expression!r}）：{exc}",
            ) from exc
        self.expression = expression

    def matches(self, dt: datetime) -> bool:
        """该时刻是否命中（UTC 口径——调度统一 UTC；五字段 AND）。"""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        minute, hour, dom, month, dow = self._sets
        cron_dow = (dt.weekday() + 1) % 7  # 周一=1 … 周日=0（cron 惯例）
        return (dt.minute in minute and dt.hour in hour
                and dt.day in dom and dt.month in month
                and cron_dow in dow)

    def next_after(self, dt: datetime) -> datetime:
        """dt 之后的下一次命中（逐分钟扫描——MVP 规模；上限 400 天）。"""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        probe = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(_MAX_SCAN_MINUTES):
            if self.matches(probe):
                return probe
            probe += timedelta(minutes=1)
        raise VastaError(
            code="schedule.bad_cron",
            message=f"{self.expression!r} 在 400 天内无命中（畸形表达式）",
        )


class ScheduleSpec(BaseModel):
    """调度配置（cron 与 event_source 恰一）。"""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    schedule_id: str = Field(min_length=1)
    cron: str | None = None
    event_source: str | None = None  # 事件类型（如 release.transition）
    tasks: list[VastaLabTask] = Field(default_factory=list)
    root: str = "."  # 批量执行 store 根（复用 8.9）
    max_retries: int = Field(default=2, ge=0)

    def model_post_init(self, __context: Any) -> None:
        has_cron, has_source = self.cron is not None, \
            self.event_source is not None
        if has_cron == has_source:  # 都无或都有
            raise VastaError(
                code="schedule.bad_spec",
                message="cron 与 event_source 恰选其一"
                        "（都无=永不触发；都有=触发源歧义）",
            )
        if has_cron:
            CronSpec(self.cron)  # 构造期校验（fail-closed）
        if not self.tasks:
            raise VastaError(
                code="schedule.bad_spec",
                message="任务清单为空（批量执行至少一个任务）",
            )


class FireRecord(BaseModel):
    """单次触发记录。"""

    model_config = ConfigDict(extra="forbid")

    schedule_id: str
    success: bool
    attempts: int = Field(ge=1)
    runs: int = Field(default=0, ge=0)
    success_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    error: str | None = None


#: 执行器面（默认绑 batch.run_tasks_as_runs；可注入替身）。
Executor = Callable[[list[VastaLabTask], str], Awaitable[Any]]


class Scheduler:
    """调度器（tick 驱动 cron；handle_event 驱动事件源；触发过 9.8 配额闸）。"""

    def __init__(
        self, store: Any,
        *,
        enforcer: Any | None = None,
        executor: Executor | None = None,
        clock: Callable[[], datetime] | None = None,
        tenant_id: str = "t-default",
        project_id: str = "p-default",
    ) -> None:
        from .batch import run_tasks_as_runs

        self._store = store
        self._enforcer = enforcer
        self._executor: Executor = executor or (
            lambda tasks, root: run_tasks_as_runs(
                tasks, root=root, tenant_id=tenant_id,
                project_id=project_id)
        )
        self._clock = clock or datetime.now
        self._tenant = tenant_id
        self._project = project_id
        self._cron: dict[str, tuple[ScheduleSpec, CronSpec, datetime]] = {}
        self._event: dict[str, list[ScheduleSpec]] = {}
        self.fires: list[FireRecord] = []

    # ---- 注册 ----
    async def add(self, spec: ScheduleSpec) -> None:
        """注册调度 + 留痕（plan.scheduled）。"""
        if spec.cron is not None:
            cron = CronSpec(spec.cron)
            self._cron[spec.schedule_id] = (
                spec, cron, cron.next_after(self._clock()))
        else:
            self._event.setdefault(spec.event_source, []).append(spec)
        await self._emit("plan.scheduled", {
            "schedule_id": spec.schedule_id,
            "cron": spec.cron,
            "event_source": spec.event_source,
            "tasks": [t.task_id for t in spec.tasks],
            "max_retries": spec.max_retries,
        })

    # ---- 触发面 ----
    async def tick(self) -> list[FireRecord]:
        """时钟推进：到点 cron 调度逐个触发（返回本次触发记录）。"""
        now = self._clock()
        fired: list[FireRecord] = []
        due = [(sid, spec) for sid, (spec, _, nxt) in self._cron.items()
               if now >= nxt]
        for sid, spec in due:
            fired.append(await self._fire(sid, spec))
            # 下一次命中（从 now 起算——错过多个周期只触发一次，补跑
            # 属 9.10 恢复语义）
            _, cron, _ = self._cron[sid]
            self._cron[sid] = (spec, cron, cron.next_after(now))
        return fired

    async def handle_event(self, event_type: str) -> list[FireRecord]:
        """事件源触发：订阅该事件类型的调度逐个触发。"""
        fired: list[FireRecord] = []
        for spec in self._event.get(event_type, []):
            fired.append(await self._fire(spec.schedule_id, spec))
        return fired

    # ---- 内部 ----
    async def _fire(self, schedule_id: str, spec: ScheduleSpec) -> FireRecord:
        """触发一次：配额闸 → 执行 → 重试至上限 → 留痕。"""
        attempts = 0
        last_error = ""
        while attempts <= spec.max_retries:
            attempts += 1
            try:
                if self._enforcer is not None:
                    await self._enforcer.check_rate(
                        self._tenant, self._project)
                summary = await self._run_with_concurrency(spec)
                record = FireRecord(
                    schedule_id=schedule_id, success=True,
                    attempts=attempts, runs=summary.runs,
                    success_rate=summary.success_rate,
                )
                self.fires.append(record)
                await self._emit("plan.fired", {
                    "schedule_id": schedule_id,
                    "attempts": attempts,
                    "runs": summary.runs,
                    "success_rate": summary.success_rate,
                })
                return record
            except Exception as exc:  # noqa: BLE001——触发失败统一重试
                # VastaError 优先记 code（quota.* 等分类可审计）
                code = getattr(exc, "code", None)
                last_error = f"{code or type(exc).__name__}: {exc}"[:200]
        # 循环退出时 attempts = 总尝试数（1 首次 + max_retries 重试）
        record = FireRecord(
            schedule_id=schedule_id, success=False,
            attempts=attempts, error=last_error,
        )
        self.fires.append(record)
        await self._emit("plan.fire_failed", {
            "schedule_id": schedule_id,
            "attempts": attempts, "max_retries": spec.max_retries,
            "error": last_error,
        })
        return record

    async def _run_with_concurrency(self, spec: ScheduleSpec) -> Any:
        """并发闸内执行批量（9.8 复用——超限即 quota.concurrent_limit）。"""
        if self._enforcer is None:
            return await self._executor(spec.tasks, spec.root)
        async with self._enforcer.concurrency_scope(
                self._tenant, self._project):
            return await self._executor(spec.tasks, spec.root)

    async def _emit(self, type_: str, payload: dict[str, Any]) -> None:
        with contextlib.suppress(Exception):  # 留痕失败不掩盖触发本体
            sequencer = EventSequencer(
                self._store, _SCHEDULES_RUN,
                tenant_id=self._tenant, project_id=self._project,
            )
            await sequencer.emit(type_, payload)


__all__ = ["CronSpec", "FireRecord", "ScheduleSpec", "Scheduler"]
