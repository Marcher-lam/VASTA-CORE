"""Story 10.5：认知三算子——revise/promote/narrow（FR-022，W-3 解除）。

显式事件携旧→新值；状态机守卫（version 递增/方向校验/真子集收窄）；
投影重放一致。
"""

from __future__ import annotations

import pytest

from vasta_cognition.cognition import Claim, CognitionService
from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


async def seed(store, **kw) -> CognitionService:
    cog = CognitionService(store)
    await cog.propose(Claim(
        claim_id="c1", memory_type="working", statement="订单超时取消",
        scope={"region": "prod", "tier": "paid"}, **kw))
    return cog


def events_of(store, type_: str) -> list:
    return [e for e in store.iter_run_events("cognition")
            if e.type == type_]


class TestRevise:
    async def test_revised_event_carries_old_new(self, store) -> None:
        cog = await seed(store)
        await cog.revise("c1", "订单超 30 分钟自动取消", reason="精确化")
        ev = events_of(store, "claim.revised")[-1]
        assert ev.payload["statement_old"] == "订单超时取消"
        assert ev.payload["statement_new"] == "订单超 30 分钟自动取消"
        assert ev.payload["reason"] == "精确化"
        claim = cog.get("c1")
        assert claim.statement == "订单超 30 分钟自动取消"
        assert claim.version == 2  # FR-021：迁移即 +1
        assert claim.status == "proposed"  # 状态不动（内容演化非状态变迁）

    async def test_revise_empty_statement_rejected(self, store) -> None:
        cog = await seed(store)
        for bad in ("", "   ", 123):
            with pytest.raises(VastaError) as excinfo:
                await cog.revise("c1", bad, reason="x")  # type: ignore[arg-type]
            assert excinfo.value.code == "claim.bad_statement"

    async def test_revise_terminal_rejected(self, store) -> None:
        cog = await seed(store)
        await cog.retire("c1")
        with pytest.raises(VastaError):
            await cog.revise("c1", "新陈述", reason="x")


class TestPromote:
    async def test_promotion_chain_and_events(self, store) -> None:
        cog = await seed(store)
        await cog.promote("c1", "hypothesis")
        await cog.promote("c1", "guide")
        evs = events_of(store, "claim.promoted")
        assert evs[0].payload == {
            "claim_id": "c1", "memory_type_old": "working",
            "memory_type_new": "hypothesis"}
        assert evs[1].payload["memory_type_new"] == "guide"
        claim = cog.get("c1")
        assert claim.memory_type == "guide"
        assert claim.version == 3  # propose(1) + 两次晋升

    async def test_skip_level_promotion_allowed(self, store) -> None:
        """跨级=强晋升（working→guide 一步到位——证据充分时合法）。"""
        cog = await seed(store)
        await cog.promote("c1", "guide")
        assert cog.get("c1").memory_type == "guide"

    async def test_demote_and_same_level_rejected(self, store) -> None:
        cog = await seed(store)
        await cog.promote("c1", "guide")
        with pytest.raises(VastaError) as e1:
            await cog.promote("c1", "working")  # 降级
        assert e1.value.code == "claim.bad_promotion"
        with pytest.raises(VastaError):
            await cog.promote("c1", "guide")  # 平级空操作

    async def test_counterexample_off_chain(self, store) -> None:
        """counterexample 是反例记忆——出入链均拒。"""
        cog = CognitionService(store)
        await cog.propose(Claim(claim_id="cx", memory_type="counterexample",
                                statement="反例", scope={}))
        with pytest.raises(VastaError) as excinfo:
            await cog.promote("cx", "guide")
        assert "不在晋升链上" in excinfo.value.message
        cog2 = await seed(store)
        with pytest.raises(VastaError):
            await cog2.promote("c1", "counterexample")  # 目标不在链


class TestNarrow:
    async def test_narrow_true_subset(self, store) -> None:
        cog = await seed(store)
        await cog.narrow("c1", {"region": "prod"}, reason="tier 条件不成立")
        ev = events_of(store, "claim.narrowed")[-1]
        assert ev.payload["scope_old"] == {"region": "prod", "tier": "paid"}
        assert ev.payload["scope_new"] == {"region": "prod"}
        claim = cog.get("c1")
        assert claim.scope == {"region": "prod"}
        assert claim.version == 2

    async def test_narrow_equal_rejected(self, store) -> None:
        cog = await seed(store)
        with pytest.raises(VastaError) as excinfo:
            await cog.narrow("c1", {"region": "prod", "tier": "paid"},
                             reason="x")
        assert excinfo.value.code == "claim.bad_narrow"
        assert "全等" in excinfo.value.message

    async def test_narrow_broaden_rejected(self, store) -> None:
        cog = await seed(store)
        with pytest.raises(VastaError) as e1:  # 新增键
            await cog.narrow("c1", {"region": "prod", "tier": "paid",
                                    "env": "staging"}, reason="x")
        assert e1.value.code == "claim.bad_narrow"
        with pytest.raises(VastaError) as e2:  # 改值（同键不同值）
            await cog.narrow("c1", {"region": "dev"}, reason="x")
        assert "新增/改值" in e2.value.message

    async def test_narrow_to_empty_rejected(self, store) -> None:
        """评审修复 M7：收到空 scope 语义是扩大到全域（且静默退出
        冲突互斥）——拒；撤回范围声明走 retire。"""
        cog = await seed(store)
        with pytest.raises(VastaError) as excinfo:
            await cog.narrow("c1", {}, reason="范围声明撤回")
        assert excinfo.value.code == "claim.bad_narrow"
        assert "retire" in excinfo.value.message
        assert cog.get("c1").scope == {"region": "prod", "tier": "paid"}


class TestReplayConsistency:
    async def test_operators_rebuild_from_stream(self, store) -> None:
        """AD-2 投影重建：三算子效果在新实例（事件流重放）后可见。"""
        cog = await seed(store)
        await cog.revise("c1", "精确陈述", reason="r")
        await cog.promote("c1", "hypothesis")
        await cog.narrow("c1", {"region": "prod"}, reason="n")
        rebuilt = CognitionService(store)
        claim = rebuilt.get("c1")
        assert claim.statement == "精确陈述"
        assert claim.memory_type == "hypothesis"
        assert claim.scope == {"region": "prod"}
        assert claim.version == 4  # propose + 三算子

    async def test_version_increments_per_operator(self, store) -> None:
        cog = await seed(store)
        v0 = cog.get("c1").version
        await cog.revise("c1", "s2", reason="r")
        await cog.promote("c1", "hypothesis")
        await cog.narrow("c1", {"region": "prod"}, reason="n")
        assert cog.get("c1").version == v0 + 3
