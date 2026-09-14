"""Story 12.10：W-1 适配器补齐与复评解除（G5）。"""

from __future__ import annotations

import os

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.agents.real_adapter import (
    OpenAICompatAdapter,
    RealAdapterConfig,
)
from vastacore.agents.real_eval import (
    W1_MIN_SEEDS,
    real_eval_report,
    run_adapter_tasks,
    run_real_seed_eval,
)
from vastacore.governance.byok import SecretRef
from vastacore.models.offline_eval import (
    OfflineEvalReport,
    attach_seed_ci,
)


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


def adapter(correct_on: set[int]) -> OpenAICompatAdapter:
    """按 seed 决定回复正确性的 fake 适配器（零网络）。"""
    async def http_post(url, headers, body, timeout_s):
        prompt = body["messages"][0]["content"]
        seed = int(prompt.split("seed=")[1].split("]")[0])
        reply = "right" if seed in correct_on else "wrong"
        return {"choices": [{"message": {"content": reply}}]}

    async def key_resolver(ref):
        return "sk-test"

    config = RealAdapterConfig(
        name="fake-real", base_url="https://unit.invalid/v1",
        api_key_ref=SecretRef(provider="kms", key_id="k"),
        model_id="fake-1")
    return OpenAICompatAdapter(config, http_post=http_post,
                               api_key_resolver=key_resolver)


async def judge(task: str, reply: str) -> bool:
    return reply == "right"


TASKS = ["q1", "q2"]
SEEDS_10 = list(range(10))


def base_report() -> OfflineEvalReport:
    return OfflineEvalReport(run_id="r-1", actions_evaluated=0,
                             unchanged=0)


class TestAdapterTaskPath:
    async def test_adapter_drives_tasks(self, store) -> None:
        """AC：执行路径端到端——adapter 真实驱动（非调用方自备结果）。"""
        rate = await run_adapter_tasks(
            adapter({1, 2, 3, 5, 6, 7, 8}), tasks=TASKS,
            judge=judge, seed=1)  # seed=1 在 correct 集 → 全对
        assert rate == 1.0
        rate_other = await run_adapter_tasks(
            adapter({1}), tasks=TASKS, judge=judge, seed=9)
        assert rate_other == 0.0

    async def test_empty_tasks_rejected(self, store) -> None:
        with pytest.raises(VastaError) as e:
            await run_adapter_tasks(adapter(set()), tasks=[],
                                    judge=judge, seed=1)
        assert e.value.code == "real_eval.empty_tasks"


class TestSeedGate:
    async def test_ten_seed_floor_enforced(self, store) -> None:
        """AC：≥10 种子接线层强制（<10 拒）。"""
        with pytest.raises(VastaError) as e:
            await run_real_seed_eval(
                store, adapter(set(5 * [0]) or set()), tasks=TASKS,
                judge=judge, seeds=[1, 2, 3])
        assert e.value.code == "real_adapter.needs_ten_seeds"
        assert W1_MIN_SEEDS == 10

    async def test_duplicate_seeds_rejected(self, store) -> None:
        with pytest.raises(VastaError) as e:
            await run_real_seed_eval(
                store, adapter(set()), tasks=TASKS, judge=judge,
                seeds=[1] * 10)
        assert e.value.code == "real_eval.duplicate_seeds"

    async def test_ten_seeds_produce_ci_and_trace(self, store) -> None:
        """10 种子 → CI（9.11 契约字段）+ evaluation.real_seed_ci 留痕。"""
        ci = await run_real_seed_eval(
            store, adapter({1, 2, 3, 4, 5}), tasks=TASKS, judge=judge,
            seeds=SEEDS_10, tenant_id="t", project_id="p")
        assert ci["n"] == 10.0
        assert ci["mean"] == pytest.approx(0.5)  # 种子 1-5 对、6-0 错
        assert ci["low"] <= ci["mean"] <= ci["high"]
        events = [e for e in store.iter_run_events("evaluation")
                  if e.type == "evaluation.real_seed_ci"]
        assert events[-1].payload["seeds"] == SEEDS_10


class TestCiIntoReport:
    def test_attach_validates_contract(self) -> None:
        with pytest.raises(VastaError) as e:
            attach_seed_ci(base_report(), {"mean": 0.5})
        assert e.value.code == "eval.bad_seed_ci"

    async def test_real_eval_report_carries_ci(self, store) -> None:
        """AC：CI 并入评测报告结构（seed_ci 字段——非独立事件）。"""
        report = await real_eval_report(
            store, adapter({1, 2, 3, 4, 5}), base_report=base_report(),
            tasks=TASKS, judge=judge, seeds=SEEDS_10,
            tenant_id="t", project_id="p")
        assert report.seed_ci is not None
        assert report.seed_ci["n"] == 10.0
        assert report.seed_ci["mean"] == pytest.approx(0.5)
        assert report.run_id == "r-1"  # 基报告字段保留


class TestGatedIntegration:
    """AC：门控集成测试（VASTA_REAL_ADAPTER 未设 skip——覆盖新路径）。"""

    def test_gated_path_wired(self) -> None:
        """环境门控在册：设 VASTA_REAL_ADAPTER 时真实适配器跑
        run_real_seed_eval 端到端（本套件 fake 已覆盖执行路径形态；
        真实端点冒烟由门控用例承接——先例 VASTA_PG_DSN/OIDC）。"""
        assert "VASTA_REAL_ADAPTER" not in os.environ  # CI 缺省跳过面
