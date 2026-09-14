"""Story 11.12：跨模型/环境排行榜（FR-069，G5）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.agents.autonomy import AutonomyPolicy
from vastacore.agents.leaderboard import (
    LeaderboardSpec,
    check_leaderboard_access,
    generate_leaderboard,
    leaderboard_from_tournament,
)
from vastacore.agents.tournament import (
    Candidate,
    TournamentSpec,
    run_tournament,
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


# ==================== Epic 12 评审修复回归 ====================



class TestAutonomyThresholdFinite:
    """AUT-1（盲审 H1）：12.2 重构丢失的阈值有限性检查回归。"""

    def test_inf_threshold_rejected(self) -> None:
        """inf t2 使任何有限 score 的降级到 L0 永不可达（实测满风险
        Agent 曾升出 L0）——构造期拒。"""
        import math

        with pytest.raises(VastaError) as e:
            AutonomyPolicy(thresholds=(0.1, 0.5, math.inf))
        assert e.value.code == "autonomy.bad_threshold"
        with pytest.raises(VastaError):
            AutonomyPolicy(thresholds=(0.1, math.inf, 0.9))

    def test_finite_thresholds_still_accepted(self) -> None:
        assert AutonomyPolicy(thresholds=(0.2, 0.5, 0.8)).thresholds == \
            (0.2, 0.5, 0.8)


class TestSeamMultiTournament:
    """缺口 M36：seam 的 tournament_id 过滤（多竞赛场景）。"""

    async def test_seam_picks_own_tournament(self, store) -> None:
        """同 store 两场竞赛——t-1 的榜单取 t-1 的 settled 事件
        （此前无过滤锚定，删过滤条件测试仍绿）。"""
        from vastacore.agents.tournament import TournamentReport

        async def runner(name: str) -> dict[str, float]:
            return {"success_rate": 0.5}

        for tid in ("t-1", "t-2"):
            await run_tournament(store, TournamentSpec(
                tournament_id=tid,
                candidates=[Candidate(name="alpha"),
                            Candidate(name="beta")],
                metrics=["success_rate"]), runner)
        spec = LeaderboardSpec(
            leaderboard_id="lb-m", metric="success_rate",
            window_start="2026-09-01T00:00:00+00:00",
            window_end="2026-09-30T00:00:00+00:00")
        board = await leaderboard_from_tournament(
            store, TournamentReport(tournament_id="t-1", results=[],
                                    winner="alpha"), spec)
        settled = [ev for ev in store.iter_run_events("evaluation")
                   if ev.type == "evaluation.tournament_settled"
                   and ev.payload["tournament_id"] == "t-1"]
        assert {e.evidence_event_seq for e in board.entries} == \
            {settled[-1].seq}


class TestStrictSeedCi:
    """CI-1（盲审 L3/边界 4-4）：attach_seed_ci 严格值校验。"""

    def _report(self):
        from vastacore.models.offline_eval import OfflineEvalReport

        return OfflineEvalReport(run_id="r", actions_evaluated=0,
                                 unchanged=0)

    def test_string_value_rejected(self) -> None:
        from vastacore.models.offline_eval import attach_seed_ci

        ci = {"n": 10.0, "mean": "zero", "half_width": 0.1,
              "low": 0.4, "high": 0.6, "level": 0.95}
        with pytest.raises(VastaError):
            attach_seed_ci(self._report(), ci)

    def test_nan_value_rejected(self) -> None:
        import math

        from vastacore.models.offline_eval import attach_seed_ci

        ci = {"n": 10.0, "mean": math.nan, "half_width": 0.1,
              "low": 0.4, "high": 0.6, "level": 0.95}
        with pytest.raises(VastaError):
            attach_seed_ci(self._report(), ci)

    def test_extra_keys_rejected(self) -> None:
        from vastacore.models.offline_eval import attach_seed_ci

        ci = {"n": 10.0, "mean": 0.5, "half_width": 0.1,
              "low": 0.4, "high": 0.6, "level": 0.95, "extra": 1}
        with pytest.raises(VastaError):
            attach_seed_ci(self._report(), ci)


class TestGatedRealAdapterIntegration:
    """验收保留项 3：门控集成测试覆盖 ≥10 种子新路径
    （VASTA_REAL_ADAPTER 未设 skip——先例 VASTA_PG_DSN/OIDC）。"""

    def test_real_seed_eval_end_to_end(self) -> None:
        import os

        config_env = os.environ.get("VASTA_REAL_ADAPTER")
        if not config_env:
            pytest.skip("VASTA_REAL_ADAPTER 未设——真实端点门控")
        import json

        cfg = json.loads(config_env)
        from vastacore.agents.real_adapter import (
            OpenAICompatAdapter,
            RealAdapterConfig,
        )
        from vastacore.agents.real_eval import run_real_seed_eval
        from vastacore.governance.byok import SecretRef

        adapter = OpenAICompatAdapter(
            RealAdapterConfig(
                name="real-gated", base_url=cfg["base_url"],
                api_key_ref=SecretRef(provider="kms",
                                      key_id=cfg["api_key_ref"]),
                model_id=cfg.get("model_id", "gpt-4o-mini")),
            http_post=cfg["http_post"],  # 环境注入（生产 httpx 形态）
            api_key_resolver=cfg["api_key_resolver"],
        )

        async def judge(task: str, reply: str) -> bool:
            return len(reply.strip()) > 0  # 冒烟判分

        import asyncio
        import pathlib
        import tempfile

        store = SqliteStorage(pathlib.Path(tempfile.mkdtemp()) / "s")
        try:
            ci = asyncio.run(run_real_seed_eval(
                store, adapter, tasks=["2+2=?"], judge=judge,
                seeds=list(range(10))))
            assert ci["n"] == 10.0
        finally:
            store.close()
