"""模型路由、熔断与成本（Story 8.6，FR-006/NFR-015，G3）。

- 路由：能力过滤（capability view 可注入——默认自声明，接 8.5 探测报告的
  effective_capabilities）→ 成本升序（cheapest-capable）或显式降级链（chain）；
  无可行适配器 fail-closed（不猜测）。
- 熔断：连续失败达阈值 open；冷却后半开试探（成闭合败重开）；open 跳过。
- 超时/重试/降级：单次 wait_for(timeout_ms)；同适配器重试 N 次后沿链
  failover（降级留痕）；全链失败抛聚合错误。
- 留痕：每次调用产 routing-trace Artifact 入 CAS（AD-5：候选/过滤/选择/
  尝试/熔断状态/降级/成本）；熔断开闭经 emitter 落 incident.opened。
- 成本（NFR-015 MVP 档）：usage tokens 优先，否则字符估算——按模型归集。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import (
    ModelAdapter,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
)


class RouterError(VastaError):
    def __init__(self, message: str) -> None:
        super().__init__(code="router.failed", message=message)


class _Breaker:
    """单适配器熔断器（closed/open/half_open）。"""

    def __init__(self, threshold: int, cooldown_s: float,
                 clock: Callable[[], float]) -> None:
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.clock = clock
        self.failures = 0
        self.state = "closed"
        self.opened_at: float | None = None

    def can_attempt(self) -> bool:
        if self.state == "closed":
            return True
        now = self.clock()
        if self.state == "open" and self.opened_at is not None:
            if now - self.opened_at >= self.cooldown_s:
                self.state = "half_open"  # 冷却期满 → 允许一次试探
                return True
            return False
        return self.state == "half_open"  # 半开：试探中（单并发假设，MVP）

    def record_success(self) -> None:
        self.failures = 0
        self.state = "closed"

    def record_failure(self) -> None:
        self.failures += 1
        if self.state == "half_open":
            self.state = "open"  # 试探失败重开
            self.opened_at = self.clock()
        elif self.failures >= self.threshold:
            self.state = "open"
            self.opened_at = self.clock()


class CostEntry(BaseModel):
    """单模型成本归集条目（NFR-015 MVP：估算口径显式标注）。"""

    model_config = ConfigDict(extra="forbid")

    calls: int = 0
    estimated_cost: float = 0.0
    basis: str = "usage"  # usage | chars-estimated


class ModelRouter:
    """按能力+成本+健康路由模型调用（换模型不动代码）。"""

    def __init__(
        self,
        models: dict[str, tuple[ModelAdapter, float]],
        *,
        strategy: str = "cheapest-capable",
        chain: list[str] | None = None,
        timeout_ms: int = 10_000,
        retries: int = 0,
        failure_threshold: int = 3,
        cooldown_s: float = 30.0,
        capability_views: dict[str, ModelCapabilities] | None = None,
        store: Any = None,
        emitter: Callable[[str, dict[str, Any]], Any] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.models = dict(models)
        self.strategy = strategy
        self.chain = list(chain or [])
        self.timeout_ms = timeout_ms
        self.retries = retries
        monotonic = clock or time.monotonic  # 安全机制真实钟（AD-15）
        self.breakers = {
            name: _Breaker(failure_threshold, cooldown_s, monotonic)
            for name in models
        }
        self.capability_views = capability_views or {}  # 8.5 探测报告注入
        self.store = store
        self.emitter = emitter
        self._costs: dict[str, CostEntry] = {}
        self._last_trace: dict[str, Any] | None = None
        self._last_trace_ref: str | None = None

    # ---- 查询面 ----
    def breaker_state(self, name: str) -> str:
        breaker = self.breakers.get(name)
        if breaker is None:
            raise RouterError(f"未注册模型 {name!r}")
        if breaker.state == "open" and breaker.can_attempt():
            pass  # can_attempt 副作用：冷却期满迁移 half_open（查询即反映）
        return breaker.state

    def last_trace(self) -> dict[str, Any]:
        if self._last_trace is None:
            raise RouterError("尚无调用——last_trace 为空")
        return self._last_trace

    def last_trace_ref(self) -> str | None:
        return self._last_trace_ref

    def cost_summary(self) -> dict[str, dict[str, Any]]:
        return {name: e.model_dump() for name, e in self._costs.items()}

    # ---- 能力视图 ----
    def _caps(self, name: str) -> ModelCapabilities:
        view = self.capability_views.get(name)
        return view if view is not None else self.models[name][0].capabilities

    def _candidates(self, require: list[str]) -> list[str]:
        capable = [
            name for name, _ in self.models.items()
            if all(getattr(self._caps(name), cap, False) for cap in require)
        ]
        if not capable:
            raise RouterError(
                f"no capable adapter for {require}（fail-closed，不猜测降级）"
            )
        if self.strategy == "chain":
            ordered = [n for n in self.chain if n in capable]
            ordered += [n for n in capable if n not in ordered]
            return ordered
        return sorted(capable, key=lambda n: self.models[n][1])  # 成本升序

    # ---- 主路径 ----
    async def generate(
        self,
        request: ModelRequest,
        *,
        require: list[str] | None = None,
        prefer: str | None = None,
    ) -> ModelResponse:
        require = require or []
        candidates = self._candidates(require)
        if prefer and prefer in candidates:
            candidates = [prefer] + [c for c in candidates if c != prefer]

        attempts: list[dict[str, Any]] = []
        degraded = False
        for index, name in enumerate(candidates):
            if index > 0:
                degraded = True  # failover 即降级
            breaker = self.breakers[name]
            if not breaker.can_attempt():
                attempts.append({"model": name, "skipped": "circuit_open"})
                continue
            for attempt in range(self.retries + 1):
                try:
                    resp = await asyncio.wait_for(
                        self.models[name][0].generate(request),
                        timeout=self.timeout_ms / 1000,
                    )
                except Exception as exc:  # noqa: BLE001——统一记失败
                    breaker.record_failure()
                    await self._maybe_emit_open(name)
                    attempts.append({
                        "model": name, "attempt": attempt,
                        "error": f"{type(exc).__name__}: {exc}"[:120],
                    })
                    continue
                breaker.record_success()
                self._record_cost(name, request, resp)
                attempts.append({"model": name, "attempt": attempt, "ok": True})
                trace = {
                    "require": require, "prefer": prefer,
                    "candidates": candidates,
                    "filtered_out": [n for n in self.models
                                     if n not in candidates],
                    "selected": name, "degraded": degraded,
                    "attempts": attempts,
                    "breaker_states": {n: b.state for n, b in self.breakers.items()},
                    "cost": self._costs[name].model_dump(),
                }
                await self._save_trace(trace)
                return resp
        await self._save_trace({
            "require": require, "candidates": candidates, "selected": None,
            "degraded": degraded, "attempts": attempts,
            "breaker_states": {n: b.state for n, b in self.breakers.items()},
        })
        raise RouterError(f"全链失败（候选 {candidates}）: "
                          f"{[a for a in attempts if a.get('error')]}")

    # ---- 内部 ----
    async def _maybe_emit_open(self, name: str) -> None:
        breaker = self.breakers[name]
        if breaker.state == "open" and self.emitter is not None:
            with contextlib.suppress(Exception):  # 留痕失败不掩盖调用本体
                maybe = self.emitter(
                    "incident.opened",
                    {"kind": "circuit_breaker", "model": name,
                     "failures": breaker.failures},
                )
                if asyncio.iscoroutine(maybe):
                    await maybe  # 确定性留痕：当次调用前完成

    def _record_cost(self, name: str, request: ModelRequest,
                     resp: ModelResponse) -> None:
        entry = self._costs.setdefault(name, CostEntry())
        entry.calls += 1
        per_1k = self.models[name][1]
        usage = (resp.detail or {}).get("usage") or {}
        tokens = usage.get("total_tokens")
        if isinstance(tokens, (int, float)) and tokens >= 0:
            entry.estimated_cost += tokens / 1000 * per_1k
            entry.basis = "usage"
        else:
            chars = len(request.prompt) + len(resp.content)
            entry.estimated_cost += chars / 1000 * per_1k
            entry.basis = "chars-estimated"

    async def _save_trace(self, trace: dict[str, Any]) -> None:
        self._last_trace = trace
        self._last_trace_ref = None
        if self.store is not None:
            with contextlib.suppress(Exception):  # 留痕失败不掩盖调用本体
                self._last_trace_ref = await self.store.save_artifact(
                    json.dumps(trace, ensure_ascii=False, sort_keys=True)
                    .encode("utf-8"),
                    mime="application/json", source="model-router",
                    classification="routing-trace",
                )


__all__ = ["CostEntry", "ModelRouter", "RouterError"]
