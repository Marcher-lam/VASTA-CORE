"""Story 11.12：跨模型/环境排行榜（FR-069，G5）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.agents.leaderboard import (
    LeaderboardSpec,
    check_leaderboard_access,
    generate_leaderboard,
)
from vastacore.governance.rbac import Principal, Role


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


def spec(visibility="public", tenant_id="t",
         project_id="p") -> LeaderboardSpec:
    return LeaderboardSpec(
        leaderboard_id="lb-1", metric="success_rate",
        visibility=visibility,
        window_start=datetime(2026, 9, 1, tzinfo=UTC),
        window_end=datetime(2026, 9, 30, tzinfo=UTC),
        tenant_id=tenant_id, project_id=project_id)


RESULTS = [
    ("model-a", 0.85, "run-1", 5),
    ("model-b", 0.92, "run-2", 3),
    ("model-c", 0.78, "run-3", 7),
]


class TestGenerate:
    async def test_sorted_with_evidence_refs(self, store) -> None:
        """AC：条目含证据引用（Run 可溯）；按指标降序。"""
        board = await generate_leaderboard(store, spec(), results=RESULTS)
        assert [e.candidate for e in board.entries] == \
            ["model-b", "model-a", "model-c"]
        top = board.entries[0]
        assert top.evidence_run == "run-2"
        assert top.evidence_event_seq == 3

    async def test_generated_traced(self, store) -> None:
        await generate_leaderboard(store, spec(), results=RESULTS)
        events = [e for e in store.iter_run_events("evaluation")
                  if e.type == "evaluation.leaderboard_generated"]
        assert events[-1].payload["entries"][0]["candidate"] == "model-b"

    async def test_empty_rejected(self, store) -> None:
        with pytest.raises(VastaError) as e:
            await generate_leaderboard(store, spec(), results=[])
        assert e.value.code == "leaderboard.no_entries"


class TestVisibility:
    async def test_public_open(self, store) -> None:
        board = await generate_leaderboard(store, spec("public"),
                                           results=RESULTS)
        check_leaderboard_access(board, tenant_id="x", project_id="y")

    async def test_private_with_authorized_principal(
            self, store) -> None:
        board = await generate_leaderboard(store, spec("private"),
                                           results=RESULTS)
        principal = Principal(user="alice", role=Role.AUDITOR,
                              tenant_id="t", project_id="p")
        check_leaderboard_access(board, tenant_id="t", project_id="p",
                                 principal=principal)

    async def test_private_unauthorized_rejected(self, store) -> None:
        board = await generate_leaderboard(store, spec("private"),
                                           results=RESULTS)
        principal = Principal(user="mallory", role=Role.VIEWER,
                              tenant_id="t", project_id="p")
        # VIEWER 有 cognition:read——同作用域通过
        check_leaderboard_access(board, tenant_id="t", project_id="p",
                                 principal=principal)
        # 异作用域拒
        with pytest.raises(VastaError) as e:
            check_leaderboard_access(board, tenant_id="t2",
                                     project_id="p2",
                                     principal=principal)
        assert e.value.code == "access.denied"

    async def test_private_no_principal_rejected(self, store) -> None:
        board = await generate_leaderboard(store, spec("private"),
                                           results=RESULTS)
        with pytest.raises(VastaError):
            check_leaderboard_access(board, tenant_id="t",
                                     project_id="p")


class TestLeaderboardReviewRegressions:
    """Epic 11 评审修复回归（盲审 H2、边界 L-1）。"""

    async def test_cross_tenant_private_board_denied(self, store) -> None:
        """H2：private 榜无作用域绑定——任意租户 auditor 传自己作用域
        即可读（原绕过路径）。现：榜归属 ≠ 请求作用域即拒。"""
        board = await generate_leaderboard(store, spec("private"),
                                           results=RESULTS)
        attacker = Principal(user="auditor-b", role=Role.AUDITOR,
                             tenant_id="t-attacker",
                             project_id="p-attacker")
        with pytest.raises(VastaError) as e:
            check_leaderboard_access(
                board, tenant_id="t-attacker",
                project_id="p-attacker", principal=attacker)
        assert e.value.code == "access.denied"

    async def test_board_scope_stamped(self, store) -> None:
        """H2：榜生成即固化作用域（tenant/project 随 spec）。"""
        board = await generate_leaderboard(
            store, spec("private", tenant_id="t-x", project_id="p-y"),
            results=RESULTS)
        assert (board.tenant_id, board.project_id) == ("t-x", "p-y")

    async def test_nan_score_rejected(self, store) -> None:
        """L-1：NaN 分值入榜即拒（不同输入序不同榜首）。"""
        import math

        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            await generate_leaderboard(store, spec(), results=[
                ("nan-cand", math.nan, "run-1", 1)])
