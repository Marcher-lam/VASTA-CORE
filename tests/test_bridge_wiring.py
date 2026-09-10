"""Story 9.14：cognition→lab 桥接自动接线（AD-13，G6——W-4 解除）。

refute → world_model.suspended → plan.invalidated 一体化链路 + 测试
（W-4 解除条件字面）。
"""

from __future__ import annotations

import pytest

from vasta_cognition.cognition import Claim, CognitionService
from vasta_storage import SqliteStorage
from vastacore.bridge_wiring import refute_with_propagation


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


async def seed(store) -> CognitionService:
    cog = CognitionService(store)
    await cog.propose(Claim(claim_id="base", memory_type="hypothesis",
                            statement="风机制可用", scope={"env": "A"}))
    await cog.propose(Claim(claim_id="child", memory_type="guide",
                            statement="依赖风的走法", scope={},
                            depends_on=["base"]))
    await cog.propose(Claim(claim_id="unrelated", memory_type="working",
                            statement="无关", scope={"env": "B"}))
    return cog


def models_of(claim_id: str) -> list[str]:
    return {"base": ["wind-model"], "child": ["grid-walker"]}.get(
        claim_id, [])


def plans_of(model: str) -> list[str]:
    return {"wind-model": ["plan-wind-1", "plan-wind-2"],
            "grid-walker": ["plan-grid"]}.get(model, [])


class TestRefutePropagation:
    async def test_full_chain_three_hops(self, store) -> None:
        """AC/W-4：refute → world_model.suspended → plan.invalidated
        链路（含级联下游的模型与计划）。"""
        cog = await seed(store)
        report = await refute_with_propagation(
            store, cog, "base", counterevidence=["replay shows wind off"],
            model_names_of=models_of, plans_of_model=plans_of)
        # 第一跳：refute + 级联
        assert report.cascaded == ["child"]
        assert cog.get("base").status == "refuted"
        assert cog.get("child").status == "refuted"
        # 第二跳：两个模型挂起
        assert set(report.suspended_models) == {"wind-model", "grid-walker"}
        suspended = [e for e in store.iter_run_events("cognition")
                     if e.type == "world_model.suspended"]
        assert {e.payload["name"] for e in suspended} == \
            {"wind-model", "grid-walker"}
        # 第三跳：三个计划失效
        assert set(report.invalidated_plans) == \
            {"plan-wind-1", "plan-wind-2", "plan-grid"}
        invalidated = [e for e in store.iter_run_events("cognition")
                       if e.type == "plan.invalidated"]
        assert len(invalidated) == 3
        by_claim = {e.payload["invalidated_by_claim"] for e in invalidated}
        assert by_claim == {"base", "child"}  # 来源主张可溯

    async def test_no_models_no_propagation(self, store) -> None:
        """主张无依赖模型 → refute 照常，桥接零事件。"""
        cog = await seed(store)
        report = await refute_with_propagation(
            store, cog, "unrelated", counterevidence=["x"],
            model_names_of=models_of, plans_of_model=plans_of)
        assert report.suspended_models == []
        assert report.invalidated_plans == []
        assert cog.get("unrelated").status == "refuted"

    async def test_without_plans_provider_still_suspends(self, store) -> None:
        """plans_of_model 可选——缺省时只做模型挂起（plan 标记由
        调用方编排面接管）。"""
        cog = await seed(store)
        report = await refute_with_propagation(
            store, cog, "base", counterevidence=["x"],
            model_names_of=models_of)
        # 级联 child 的模型照常挂起（缺省只省略 plan 标记）
        assert set(report.suspended_models) == {"wind-model", "grid-walker"}
        assert report.invalidated_plans == []

    async def test_unrelated_claim_untouched(self, store) -> None:
        """传播不越界：无关主张/其模型与计划不受影响。"""
        cog = await seed(store)
        await refute_with_propagation(
            store, cog, "base", counterevidence=["x"],
            model_names_of=models_of, plans_of_model=plans_of)
        assert cog.get("unrelated").status == "proposed"
        suspended = [e for e in store.iter_run_events("cognition")
                     if e.type == "world_model.suspended"]
        assert all(e.payload["name"] != "other-model"
                   for e in suspended)
