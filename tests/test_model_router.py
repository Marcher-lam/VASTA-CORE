"""Story 8.6：模型路由、熔断与成本（FR-006/NFR-015，G3）。

路由选择/能力过滤 fail-closed/超时降级留痕/熔断开闭半开/成本归集。
"""

from __future__ import annotations

import asyncio

import pytest

from vasta_protocols.protocols import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
)
from vasta_storage import SqliteStorage
from vastacore.models.router import ModelRouter, RouterError


class FakeModel:
    protocol_version = "0.1.0"

    def __init__(self, *, content="ok", delay=0.0, fail=False,
                 capabilities=None, usage=None):
        self.content = content
        self.delay = delay
        self.fail = fail
        self.capabilities = capabilities or ModelCapabilities()
        self.usage = usage
        self.calls = 0

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("provider down")
        detail = {"usage": self.usage} if self.usage else {}
        return ModelResponse(content=self.content, detail=detail)


def make_router(models: dict, **kwargs) -> ModelRouter:
    return ModelRouter(models, **kwargs)


class TestRouting:
    async def test_cheapest_capable_selected(self) -> None:
        cheap = FakeModel(capabilities=ModelCapabilities(structured_output=True))
        pricey = FakeModel(capabilities=ModelCapabilities(structured_output=True))
        router = make_router({
            "cheap": (cheap, 0.001),
            "pricey": (pricey, 1.0),
        })
        resp = await router.generate(ModelRequest(prompt="p"),
                                     require=["structured_output"])
        assert resp.content == "ok"
        assert cheap.calls == 1 and pricey.calls == 0  # 最便宜胜出

    async def test_capability_filter_fail_closed(self) -> None:
        """无可行适配器 → fail-closed 报错（不猜测降级到不能力模型）。"""
        blind = FakeModel()  # 无结构化能力
        router = make_router({"blind": (blind, 0.001)})
        with pytest.raises(RouterError) as excinfo:
            await router.generate(ModelRequest(prompt="p"),
                                  require=["structured_output"])
        assert "no capable" in str(excinfo.value).lower()
        assert blind.calls == 0  # 未被调用

    async def test_explicit_chain_strategy(self) -> None:
        """显式降级链：按 chain 顺序尝试。"""
        a = FakeModel(content="from-a")
        b = FakeModel(content="from-b")
        router = make_router(
            {"a": (a, 1.0), "b": (b, 0.001)},
            strategy="chain", chain=["a", "b"],
        )
        resp = await router.generate(ModelRequest(prompt="p"))
        assert resp.content == "from-a"  # 链首优先（不按成本）
        assert b.calls == 0


class TestTimeoutDegrade:
    async def test_timeout_fails_over_and_degrades(self) -> None:
        """超时 → 沿链 failover（降级留痕于 trace）。"""
        slow = FakeModel(delay=0.5, capabilities=ModelCapabilities(
            structured_output=True))
        fast = FakeModel(content="fallback", capabilities=ModelCapabilities(
            structured_output=True))
        router = make_router(
            {"slow": (slow, 0.001), "fast": (fast, 0.01)},
            timeout_ms=80,
        )
        resp = await router.generate(ModelRequest(prompt="p"),
                                     require=["structured_output"])
        assert resp.content == "fallback"
        trace = router.last_trace()
        assert trace["degraded"] is True
        assert any(a["error"] for a in trace["attempts"])

    async def test_all_fail_aggregates(self) -> None:
        router = make_router({"a": (FakeModel(fail=True), 0.001)})
        with pytest.raises(RouterError) as excinfo:
            await router.generate(ModelRequest(prompt="p"))
        assert "a" in str(excinfo.value)

    async def test_retry_before_failover(self) -> None:
        """同适配器重试 N 次后才 failover。"""
        flaky = FakeModel(fail=True)
        backup = FakeModel(content="backup")
        router = make_router(
            {"flaky": (flaky, 0.001), "backup": (backup, 0.01)},
            retries=2,
        )
        resp = await router.generate(ModelRequest(prompt="p"))
        assert resp.content == "backup"
        assert flaky.calls == 3  # 首发 + 2 重试


class TestCircuitBreaker:
    async def test_opens_after_threshold_and_skips(self) -> None:
        dead = FakeModel(fail=True)
        alive = FakeModel(content="alive")
        incidents: list[tuple[str, dict]] = []

        async def emitter(type_: str, payload: dict) -> None:
            incidents.append((type_, payload))

        router = make_router(
            {"dead": (dead, 0.001), "alive": (alive, 0.01)},
            failure_threshold=2, emitter=emitter,
        )
        # 两次调用各失败一次 dead（由 alive 降级兜底）→ 熔断打开
        for _ in range(2):
            resp = await router.generate(ModelRequest(prompt="p"))
            assert resp.content == "alive"  # 降级链兜底成功
        assert router.breaker_state("dead") == "open"
        # incident 事件留痕
        assert any(t == "incident.opened" and
                   p.get("kind") == "circuit_breaker" for t, p in incidents)
        # 第三次调用直接跳过 dead（不再打它）
        resp = await router.generate(ModelRequest(prompt="p"))
        assert resp.content == "alive"
        assert dead.calls == 2  # 没有第三次失败尝试
        assert router.last_trace()["attempts"][0]["skipped"] == "circuit_open"

    async def test_half_open_recovery(self) -> None:
        flaky = FakeModel(fail=True)
        router = make_router(
            {"flaky": (flaky, 0.001)},
            failure_threshold=1, cooldown_s=0.05,
        )
        with pytest.raises(RouterError):
            await router.generate(ModelRequest(prompt="p"))
        assert router.breaker_state("flaky") == "open"
        await asyncio.sleep(0.06)
        assert router.breaker_state("flaky") == "half_open"  # 冷却后半开
        flaky.fail = False  # 恢复
        resp = await router.generate(ModelRequest(prompt="p"))
        assert resp.content == "ok"
        assert router.breaker_state("flaky") == "closed"  # 试探成功闭合


class TestTraceAndCost:
    async def test_trace_saved_to_cas(self, tmp_path) -> None:
        import hashlib

        store = SqliteStorage(tmp_path / "s")
        model = FakeModel(capabilities=ModelCapabilities(structured_output=True))
        router = make_router({"m": (model, 0.5)}, store=store)
        await router.generate(ModelRequest(prompt="p"),
                              require=["structured_output"])
        sha = router.last_trace_ref()
        assert sha is not None
        blob = await store.get_artifact(sha)
        assert hashlib.sha256(blob).hexdigest() == sha
        assert b'"selected"' in blob  # 路由决策在 trace 内
        store.close()

    async def test_cost_summary_aggregates_per_model(self) -> None:
        m1 = FakeModel(usage={"total_tokens": 2000})
        m2 = FakeModel(usage={"total_tokens": 500})
        router = make_router({"a": (m1, 0.01), "b": (m2, 0.02)})
        await router.generate(ModelRequest(prompt="x" * 10), prefer="a")
        await router.generate(ModelRequest(prompt="y" * 10), prefer="b")
        summary = router.cost_summary()
        assert summary["a"]["calls"] == 1
        assert summary["a"]["estimated_cost"] == pytest.approx(2000 / 1000 * 0.01)
        assert summary["b"]["estimated_cost"] == pytest.approx(500 / 1000 * 0.02)
        assert summary["a"]["basis"] == "usage"

    async def test_cost_char_fallback_estimated(self) -> None:
        m = FakeModel()  # 无 usage
        router = make_router({"m": (m, 0.02)})
        await router.generate(ModelRequest(prompt="p" * 3000))
        summary = router.cost_summary()
        assert summary["m"]["basis"] == "chars-estimated"
        assert summary["m"]["estimated_cost"] > 0

    async def test_prefer_directs_choice(self) -> None:
        a, b = FakeModel(content="a"), FakeModel(content="b")
        router = make_router({"a": (a, 0.5), "b": (b, 0.001)})
        resp = await router.generate(ModelRequest(prompt="p"), prefer="b")
        assert resp.content == "b" and a.calls == 0
