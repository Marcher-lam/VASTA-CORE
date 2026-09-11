"""Story 11.10：并行探索与候选竞赛（FR-056，G4）。"""

from __future__ import annotations

import pytest

from vasta_storage import SqliteStorage
from vastacore.agents.tournament import (
    Candidate,
    TournamentSpec,
    run_tournament,
)


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


def spec(**kw) -> TournamentSpec:
    base = dict(
        tournament_id="t1",
        candidates=[Candidate(name="alpha"), Candidate(name="beta"),
                    Candidate(name="gamma")],
        metrics=["success_rate", "cost_efficiency"],
        metric_direction={"cost_efficiency": False},  # 越小越好
    )
    base.update(kw)
    return TournamentSpec(**base)


class TestTournament:
    async def test_parallel_run_ranked_winner(self, store) -> None:
        """AC：并行执行 + 评测对比排序 + 胜出标记。"""

        async def runner(name: str) -> dict[str, float]:
            scores = {"alpha": {"success_rate": 0.9,
                                "cost_efficiency": 0.4},
                      "beta": {"success_rate": 0.8,
                               "cost_efficiency": 0.2},
                      "gamma": {"success_rate": 0.75,
                                "cost_efficiency": 0.1}}
            return scores[name]

        # 综合分 = success - cost_eff：gamma=0.6 最高
        report = await run_tournament(store, spec(), runner,
                                      tenant_id="t", project_id="p")
        assert report.winner == "gamma"
        assert [r.candidate for r in report.results] == \
            ["gamma", "beta", "alpha"]
        settled = [e for e in store.iter_run_events(
            "evaluation", tenant_id="t", project_id="p")
            if e.type == "evaluation.tournament_settled"]
        assert settled[-1].payload["winner"] == "gamma"

    async def test_candidate_failure_isolated(self, store) -> None:
        """AC：候选间预算隔离——一候选失败不毁整赛。"""
        calls: list[str] = []

        async def runner(name: str) -> dict[str, float]:
            calls.append(name)
            if name == "beta":
                raise RuntimeError("budget exhausted for this candidate")
            return {"success_rate": 0.5, "cost_efficiency": 0.3}

        report = await run_tournament(store, spec(), runner,
                                      tenant_id="t", project_id="p")
        assert len(calls) == 3  # 全部候选都跑了
        beta = [r for r in report.results if r.candidate == "beta"][0]
        assert beta.failed is True
        assert "budget exhausted" in beta.error
        # 其余候选照常排名（alpha/gamma 并列胜出取一）
        assert report.winner in ("alpha", "gamma")

    async def test_all_failed_no_winner(self, store) -> None:
        async def runner(name: str) -> dict[str, float]:
            raise RuntimeError("all down")

        report = await run_tournament(store, spec(), runner,
                                      tenant_id="t", project_id="p")
        assert report.winner is None
        assert all(r.failed for r in report.results)

    async def test_started_event_traced(self, store) -> None:
        async def runner(name: str) -> dict[str, float]:
            return {"success_rate": 1.0}

        await run_tournament(store, spec(), runner,
                             tenant_id="t", project_id="p")
        started = [e for e in store.iter_run_events(
            "evaluation", tenant_id="t", project_id="p")
            if e.type == "evaluation.tournament_started"]
        assert started[-1].payload["candidates"] == \
            ["alpha", "beta", "gamma"]

    async def test_min_two_candidates(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            spec(candidates=[Candidate(name="solo")])
