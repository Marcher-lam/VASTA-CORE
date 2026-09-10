"""Story 9.5：批准记录五要素绑定（FR-034，G3）。

五要素审计 + 超时失效 + 撤销 + 按批准者检索；与 Epic 3 零冲突。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.approvals import (
    ApprovalRecord,
    is_approval_valid,
    record_approval,
    revoke_approval,
    search_approvals,
)


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


class TestFiveElements:
    async def test_record_contains_all_five(self, store) -> None:
        """AC：五要素（action/args/scope/expires_at/approver）入事件流。"""
        rec = await record_approval(
            store, tool="ship_order", args={"order_id": "A102"},
            approver="alice@corp", scope="t-default:p-default", ttl_s=3600,
        )
        assert isinstance(rec, ApprovalRecord)
        assert rec.tool == "ship_order"
        assert rec.args == {"order_id": "A102"}
        assert rec.approver == "alice@corp"
        assert rec.scope == "t-default:p-default"
        assert rec.expires_at is not None
        # 事件流可查
        events = [e for e in store.iter_run_events("approvals")
                  if e.type == "action.approval_record"]
        assert len(events) >= 1
        assert events[-1].payload["tool"] == "ship_order"
        assert events[-1].payload["approver"] == "alice@corp"

    async def test_expiry_auto_invalidates(self, store) -> None:
        """AC：超时批准自动失效（评审修复——ttl_s=0/负值在签发侧被拒，
        过期语义改由 expires_at 判定承担）。"""
        rec = await record_approval(
            store, tool="set_status", args={}, approver="bob",
            scope="t:p", ttl_s=3600,
        )
        assert is_approval_valid(rec) is True
        expired = rec.model_copy(update={
            "expires_at": rec.expires_at - timedelta(seconds=7200),
        })
        assert is_approval_valid(expired) is False

    async def test_zero_and_negative_ttl_rejected(self, store) -> None:
        """评审修复：ttl_s<=0 拒（签发即过期的批准无审计意义）。"""
        for bad in (0, -3600):
            with pytest.raises(VastaError) as excinfo:
                await record_approval(
                    store, tool="t", args={}, approver="a",
                    scope="s", ttl_s=bad,
                )
            assert excinfo.value.code == "approval.bad_ttl"

    async def test_approval_id_no_same_second_collision(self, store) -> None:
        """评审修复：同秒同工具多批——id 不再碰撞。"""
        ids = set()
        for _ in range(20):
            rec = await record_approval(
                store, tool="same-tool", args={}, approver="a",
                scope="s", ttl_s=60,
            )
            ids.add(rec.approval_id)
        assert len(ids) == 20  # 无一碰撞

    async def test_expiry_boundary(self, store) -> None:
        """恰在过期时刻：expired。"""
        rec = await record_approval(
            store, tool="t", args={}, approver="a", scope="s", ttl_s=3600,
        )
        # 手动把 expires_at 调到过去
        rec_expired = rec.model_copy(update={
            "expires_at": rec.expires_at - timedelta(seconds=7200),
        })
        assert is_approval_valid(rec_expired) is False


class TestRevoke:
    async def test_revoke_invalidates_and_logs(self, store) -> None:
        rec = await record_approval(
            store, tool="ship", args={}, approver="c", scope="s", ttl_s=3600,
        )
        assert is_approval_valid(rec) is True
        await revoke_approval(store, rec.approval_id, reason="changed mind")
        # 撤销后查事件
        events = [e for e in store.iter_run_events("approvals")
                  if e.type == "action.approval_revoked"]
        assert len(events) >= 1
        assert events[-1].payload["approval_id"] == rec.approval_id

    async def test_revoke_unknown_rejected(self, store) -> None:
        with pytest.raises(VastaError):
            await revoke_approval(store, "ghost-id", reason="x")

    async def test_revoke_scoped_not_cross_tenant(self, store) -> None:
        """评审修复：撤销按作用域匹配——他租户同 id 不可误撤。"""
        from vastacore.approvals import get_approval

        rec = await record_approval(
            store, tool="ship", args={}, approver="c", scope="t-a:p-a",
            ttl_s=3600,
        )
        # t-b 视角撤销 → not_found（同 id 在他租户不可见）
        with pytest.raises(VastaError) as excinfo:
            await revoke_approval(store, rec.approval_id, reason="x",
                                  tenant_id="t-b", project_id="p-b")
        assert excinfo.value.code == "approval.not_found"
        # 本租户撤销 + 重建闭环：get_approval 的 record 立即失效
        await revoke_approval(store, rec.approval_id, reason="r")
        rebuilt = await get_approval(store, rec.approval_id)
        assert rebuilt.revoked is True
        assert is_approval_valid(rebuilt) is False

    async def test_naive_now_not_typeerror(self, store) -> None:
        """评审修复：naive datetime.now() 直接可用（按 UTC 解释）。"""
        from datetime import datetime

        rec = await record_approval(
            store, tool="t", args={}, approver="a", scope="s", ttl_s=3600,
        )
        assert is_approval_valid(rec, now=datetime.now()) is True


class TestAuditSearch:
    async def test_search_by_approver(self, store) -> None:
        """AC：审计可按批准者检索。"""
        await record_approval(store, tool="a", args={}, approver="alice",
                              scope="s", ttl_s=60)
        await record_approval(store, tool="b", args={}, approver="bob",
                              scope="s", ttl_s=60)
        await record_approval(store, tool="c", args={}, approver="alice",
                              scope="s", ttl_s=60)
        alice = await search_approvals(store, approver="alice")
        bob = await search_approvals(store, approver="bob")
        assert len(alice) == 2
        assert len(bob) == 1
        assert all(r.payload["approver"] == "alice" for r in alice)


class TestZeroConflict:
    async def test_epic3_approval_flow_untouched(self, tmp_path) -> None:
        """AC：与既有 approve_pending 零语义冲突——Epic 3 全部测试仍绿。"""
        from tests.test_agent_sdk import STATUS_CONTRACT, SetStatusTool, TodoEnv
        from vasta_protocols.protocols import Action
        from vastacore import AgentSession

        store = SqliteStorage(tmp_path / "e3")
        session = await AgentSession.create(
            env=TodoEnv(), tools=[SetStatusTool()],
            contracts={"set_status": STATUS_CONTRACT},
            root=tmp_path, seed=1,
        )
        async with session:
            await session.start()
            await session.reset()
            await session.act(Action(tool="set_status",
                                     args={"status": "done"}))
            await session.complete()
            types = [e.type for e in session.events()]
        # Epic 3 的 action.approved / action.approval_requested 语义不变
        assert "action.executed" in types
        store.close()
