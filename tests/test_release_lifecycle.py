"""Story 10.3：模型全生命周期状态机（FR-045 + FR-055，G1）。

六态+revoked：candidate→testing→shadow→canary→active（复核门）→
suspended↔active→retired/revoked（终态不可逆）；吊销级联计划失效。
"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.governance.release import (
    get_release_status,
    promote_release,
    resume_release,
    retire_release,
    revoke_release,
    suspend_release,
)
from vastacore.governance.versioning import publish_model_version

RULESET = {"rules": {}, "goal_check": "done"}
MANIFEST = {"name": "grid", "version": "1.0", "scope": "grid",
            "unknowns": ["u"], "coverage": ["right"]}


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


async def seeded(store, versions=("1.0.0", "2.0.0")) -> None:
    for v in versions:
        await publish_model_version(store, "grid", v, ruleset=RULESET,
                                    manifest=MANIFEST)


async def to_active(store, version: str = "2.0.0") -> None:
    for to, approver in (("testing", None), ("shadow", None),
                         ("canary", None), ("active", "reviewer@corp")):
        await promote_release(store, "model", "grid", version, to=to,
                              approver=approver)


class TestLifecyclePath:
    async def test_full_lifecycle_with_suspend_retire(self, store) -> None:
        """AC：六态全生命周期——active→suspended→resume→retired。"""
        await seeded(store)
        await to_active(store)
        r1 = await suspend_release(store, "model", "grid", "2.0.0",
                                   reason="drift detected")
        assert r1.status == "suspended"
        assert await get_release_status(store, "model", "grid") == "suspended"
        r2 = await resume_release(store, "model", "grid", "2.0.0",
                                  reason="drift resolved")
        assert r2.status == "active"
        r3 = await retire_release(store, "model", "grid", "2.0.0",
                                  reason="superseded by 3.0.0")
        assert r3.status == "retired"
        # 退役终态：无出边
        with pytest.raises(VastaError) as excinfo:
            await resume_release(store, "model", "grid", "2.0.0",
                                 reason="x")
        assert excinfo.value.code == "release.invalid_transition"

    async def test_suspend_from_candidate_rejected(self, store) -> None:
        """挂起只对 active/suspended 有意义——candidate 挂起拒。"""
        await seeded(store)
        with pytest.raises(VastaError):
            await suspend_release(store, "model", "grid", "1.0.0",
                                  reason="x")


class TestRevocation:
    async def test_revoke_irreversible(self, store) -> None:
        """AC：吊销不可逆——任何后续迁移全拒。"""
        await seeded(store)
        await to_active(store)
        r = await revoke_release(store, "model", "grid", "2.0.0",
                                 reason="safety incident",
                                 approver="sec@corp")
        assert r.approval_id.startswith("apr-release.revoke-")
        assert await get_release_status(store, "model", "grid") == "revoked"
        for op in (
            lambda: promote_release(store, "model", "grid", "2.0.0",
                                    to="suspended"),
            lambda: resume_release(store, "model", "grid", "2.0.0",
                                   reason="x"),
            lambda: retire_release(store, "model", "grid", "2.0.0",
                                   reason="x"),
            lambda: revoke_release(store, "model", "grid", "2.0.0",
                                   reason="again", approver="a"),
        ):
            with pytest.raises(VastaError) as excinfo:
                await op()
            assert excinfo.value.code == "release.invalid_transition"

    async def test_revoke_requires_approver(self, store) -> None:
        """FR-055：吊销须人工复核——approver 缺省拒（运行时门，
        与上线门对称）。"""
        await seeded(store)
        with pytest.raises(VastaError) as excinfo:
            await revoke_release(store, "model", "grid", "1.0.0", reason="x")
        assert excinfo.value.code == "release.review_required"
        # 拒绝时不落吊销事件（流干净）
        assert not [e for e in store.iter_run_events("registry")
                    if e.payload.get("to") == "revoked"]

    async def test_revoke_from_early_stage(self, store) -> None:
        """candidate 阶段可吊销（早期发现缺陷——任何活跃态）。"""
        await seeded(store)
        r = await revoke_release(store, "model", "grid", "1.0.0",
                                 reason="flawed candidate",
                                 approver="dev@corp")
        assert r.invalidated_plans == []

    async def test_revoke_cascades_plan_invalidation(self, store) -> None:
        """AC：吊销级联——依赖计划失效（plan.invalidated，来源可溯）。"""
        await seeded(store)
        await to_active(store)
        r = await revoke_release(
            store, "model", "grid", "2.0.0", reason="bad world model",
            approver="sec@corp",
            plans_of_model=lambda v: ["plan-alpha", "plan-beta"])
        assert r.invalidated_plans == ["plan-alpha", "plan-beta"]
        invalidated = [e for e in store.iter_run_events("cognition")
                       if e.type == "plan.invalidated"]
        assert {e.payload["plan_id"] for e in invalidated} == \
            {"plan-alpha", "plan-beta"}
        assert invalidated[0].payload["invalidated_by_release"] == \
            "model:grid:2.0.0"

    async def test_rolled_back_not_revocable(self, store) -> None:
        """终态（rolled_back）不可吊销——历史版本非活跃。"""
        await seeded(store)
        await to_active(store, "1.0.0")
        await to_active(store, "2.0.0")
        from vastacore.governance.release import rollback_release

        await rollback_release(store, "model", "grid")  # 2.0.0 → rolled_back
        with pytest.raises(VastaError) as excinfo:
            await revoke_release(store, "model", "grid", "2.0.0",
                                 reason="late discovery", approver="a")
        assert excinfo.value.code == "release.invalid_transition"


class TestReviewGate:
    async def test_active_promotion_requires_approver(self, store) -> None:
        """FR-055 复核门：canary→active 无 approver 拒（fail-closed）。"""
        await seeded(store)
        for to in ("testing", "shadow", "canary"):
            await promote_release(store, "model", "grid", "2.0.0", to=to)
        with pytest.raises(VastaError) as excinfo:
            await promote_release(store, "model", "grid", "2.0.0",
                                  to="active")
        assert excinfo.value.code == "release.review_required"

    async def test_review_leaves_approval_trace(self, store) -> None:
        """复核经 9.5 批准流——approvals 流五要素留痕 + 事件带
        approval_id 引用。"""
        await seeded(store)
        await to_active(store)
        approvals = [e for e in store.iter_run_events("approvals")
                     if e.type == "action.approval_record"]
        assert approvals[-1].payload["tool"] == "release.promote_active"
        assert approvals[-1].payload["approver"] == "reviewer@corp"
        transitions = [e for e in store.iter_run_events("registry")
                       if e.type == "release.transition"
                       and e.payload.get("to") == "active"]
        assert transitions[-1].payload["approval_id"] == \
            approvals[-1].payload["approval_id"]

    async def test_suspend_resume_without_review(self, store) -> None:
        """挂起/恢复免复核（恢复不是新上线——门已在首次上线过）。"""
        await seeded(store)
        await to_active(store)
        await suspend_release(store, "model", "grid", "2.0.0", reason="x")
        await resume_release(store, "model", "grid", "2.0.0", reason="y")
        # 只有上线一次批准记录（suspend/resume 不产生）
        approvals = [e for e in store.iter_run_events("approvals")
                     if e.type == "action.approval_record"]
        assert len(approvals) == 1


class TestStateReplay:
    async def test_revoked_active_not_served(self, store) -> None:
        """吊销的 active 版本不被 _active 引用——状态查询面正确。"""
        await seeded(store)
        await to_active(store)
        await revoke_release(store, "model", "grid", "2.0.0",
                             reason="x", approver="a")
        state = get_release_status
        assert await state(store, "model", "grid") == "revoked"
        # 另一版本仍可正常推进（吊销不毒化资产其他版本）
        for to, approver in (("testing", None), ("shadow", None)):
            await promote_release(store, "model", "grid", "1.0.0", to=to,
                                  approver=approver)

    async def test_transition_events_carry_reason(self, store) -> None:
        """生命周期事件留痕（release 族）——reason/approval_id 入流。"""
        await seeded(store)
        await to_active(store)
        await suspend_release(store, "model", "grid", "2.0.0",
                              reason="incident-42")
        suspended = [e for e in store.iter_run_events("registry")
                     if e.type == "release.transition"
                     and e.payload.get("to") == "suspended"]
        assert suspended[-1].payload["reason"] == "incident-42"
        assert suspended[-1].payload["from"] == "active"
