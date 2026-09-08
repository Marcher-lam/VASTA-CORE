"""RunContext：时钟/随机/配置/身份的注入点（AD-5，Story 1.5）。

决策与数据路径的一切时间与随机都从这里取——直接读系统时钟/随机/环境
违反 AD-5，由 tests/test_determinism_guards.py 静态扫描强制（白名单仅
protocols/ids.py 供给点与 storage 簿记）。

- record 模式（默认）：真实时钟（经 protocols.ids 供给）+ UUIDv7 事件 ID。
- seeded 模式：确定性时钟（固定基点 + 每次 +1ms）+ random.Random(seed) +
  种子派生事件 ID（rng.getrandbits(128) 构造 UUID——与约定 UUIDv7 的
  偏差：确定性重放要求 ID 可再生，已记录于 Story 1.5）。
- replay 模式：seeded + 重放守卫——引擎拒绝非确定性替身适配器，除非
  real_tools_authorized 显式授权。
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from vasta_protocols.ids import new_event_id, now_utc

_SEED_TS_BASE = datetime(2026, 1, 1, tzinfo=UTC)
_STEP_US = 1000


class _SeededClock:
    """确定性时钟：固定基点，每次调用 +1ms。"""

    def __init__(self, base: datetime = _SEED_TS_BASE) -> None:
        self._base = base
        self._ticks = 0

    def __call__(self) -> datetime:
        result = self._base.fromtimestamp(
            self._base.timestamp() + self._ticks * _STEP_US / 1_000_000, tz=UTC
        )
        self._ticks += 1
        return result


@dataclass(frozen=True)
class RunContext:
    run_id: str
    tenant_id: str
    project_id: str
    clock: Callable[[], datetime]
    rng: random.Random
    seed: int | None = None
    replay_mode: bool = False
    real_tools_authorized: bool = False
    config: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        tenant_id: str = "t-default",
        project_id: str = "p-default",
        seed: int | None = None,
        clock: Callable[[], datetime] | None = None,
        replay_mode: bool = False,
        real_tools_authorized: bool = False,
        config: Mapping[str, Any] | None = None,
    ) -> RunContext:
        if replay_mode and seed is None:
            raise ValueError(
                "replay mode requires a seed — without it the replay is not reproducible"
            )
        id_rng: random.Random | None = None
        if seed is not None:
            effective_clock: Callable[[], datetime] = clock or _SeededClock()
            # 双流（评审修复）：事件 ID 与应用随机分离，插入一个事件
            # 不再平移后续所有随机数。
            rng = random.Random(seed)
            id_rng = random.Random(f"{seed}:event-id")
        else:
            effective_clock = clock or now_utc
            rng = random.Random()
        instance = cls(
            run_id=run_id,
            tenant_id=tenant_id,
            project_id=project_id,
            clock=effective_clock,
            rng=rng,
            seed=seed,
            replay_mode=replay_mode,
            real_tools_authorized=real_tools_authorized,
            config=MappingProxyType(dict(config or {})),
        )
        object.__setattr__(instance, "_id_rng", id_rng)
        return instance

    def new_event_id(self) -> str:
        """事件 ID：seeded 模式由独立 ID 流派生（可再生且与应用随机解耦），
        否则 UUIDv7。"""
        id_rng = self.__dict__.get("_id_rng")
        if id_rng is not None:
            return str(uuid.UUID(int=id_rng.getrandbits(128)))
        return new_event_id()

    def require_replay_adapter(self, adapter: Any) -> None:
        """重放守卫：replay 模式下只放行确定性替身，真实适配器需显式授权。"""
        if not self.replay_mode:
            return
        if getattr(adapter, "deterministic", False):
            return
        if self.real_tools_authorized:
            return
        from vasta_protocols.errors import VastaError

        raise VastaError(
            code="replay.real_env_unauthorized",
            message=(
                "replay mode requires deterministic stand-in adapters; "
                "set real_tools_authorized to use real adapters"
            ),
        )
