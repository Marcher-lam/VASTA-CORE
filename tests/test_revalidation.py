"""Story 9.11：环境升级批量重验证与认知衰减（FR-026，G4）。

影响面（scope 命中 + depends_on 下游闭包）；离线重评估复用（8.10）；
衰减/推翻处置留痕；影响面报告；W-1 CI 计算面。
"""

from __future__ import annotations

import pytest

from vasta_cognition.cognition import Claim, CognitionService
from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action, Observation
from vasta_runtime import Budget, RunContext, RunEngine
from vasta_storage import SqliteStorage
from vastacore.revalidation import (
    DecayPolicy,
    impact_analysis,
    record_env_upgrade,
    revalidate_claims,
    seed_confidence_interval,
)


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


class TinyEnv:
    protocol_version = "0.1.0"

    async def reset(self, seed=None) -> Observation:
        return Observation(kind="decision", available_actions=["noop"])

    async def observe(self) -> Observation:
        return Observation(kind="decision", available_actions=["noop"])

    async def execute(self, action: Action) -> list[Observation]:
        return [Observation(kind="decision", available_actions=["noop"])]

    async def status(self) -> object:
        class _S:
            running = True

        return _S()


async def make_clean_run(store, run_id: str) -> None:
    """无偏差源 Run（重验证 pass 的载体——observation-only）。"""
    engine = await RunEngine.create(
        env=TinyEnv(), store=store, budget=Budget(max_actions=2),
        run_context=RunContext.create(run_id=run_id, seed=1),
    )
    await engine.start()
    await engine.reset(seed=1)
    await engine.complete()


def claim(cid: str, *, confidence: float = 0.5, scope: dict | None = None,
          depends_on: list[str] | None = None,
          run_id: str | None = None) -> Claim:
    return Claim(
        claim_id=cid, memory_type="working", statement=f"stmt {cid}",
        scope=scope or {"region": "prod"}, confidence=confidence,
        depends_on=depends_on or [], run_id=run_id,
    )


class TestEnvUpgrade:
    async def test_upgrade_event_leaves_trace(self, store) -> None:
        await record_env_upgrade(store, env_old="v1.2", env_new="v1.3",
                                 affected_scope={"region": "prod"})
        events = [e for e in store.iter_run_events("environment")
                  if e.type == "evaluation.env_upgraded"]
        assert len(events) == 1
        assert events[0].payload["env_old"] == "v1.2"
        assert events[0].payload["affected_scope"] == {"region": "prod"}

    async def test_empty_scope_rejected(self, store) -> None:
        with pytest.raises(VastaError) as excinfo:
            await record_env_upgrade(store, env_old="a", env_new="b",
                                     affected_scope={})
        assert excinfo.value.code == "revalidation.empty_scope"


class TestImpactAnalysis:
    async def test_scope_hit_and_downstream_closure(self, store) -> None:
        """影响面：scope 命中 + depends_on 下游闭包；无关/终态不参与。"""
        cog = CognitionService(store)
        await cog.propose(claim("hit", run_id=None))
        # 评审修复（验证缺口 M12 假锚定）：下游主张 scope={}——
        # 非 scope 直接命中，闭包传播路径真正承重（原 fixture 给同
        # scope 使删闭包后该测试仍绿）
        await cog.propose(claim("downstream", scope={}, depends_on=["hit"]))
        await cog.propose(claim("unrelated", scope={"region": "dev"}))
        await cog.propose(claim("dead", scope={}, depends_on=["hit"]))
        await cog.retire("dead")  # 退役不参与
        affected = {c.claim_id for c in impact_analysis(
            cog, {"region": "prod"})}
        assert affected == {"hit", "downstream"}

    async def test_cycle_safe(self, store) -> None:
        """依赖环不死循环（visited 防环）。"""
        cog = CognitionService(store)
        await cog.propose(claim("a", scope={}, depends_on=["b"]))
        await cog.propose(claim("b", scope={}, depends_on=["a"]))
        affected = {c.claim_id for c in impact_analysis(
            cog, {"region": "prod"})}
        assert affected == {"a", "b"}


class TestRevalidation:
    async def test_pass_kept_with_trace(self, store) -> None:
        """AC：仍通过者保留（claim.revalidated 留痕，状态/置信不变）。"""
        await make_clean_run(store, "run-ok")
        cog = CognitionService(store)
        await cog.propose(claim("good", confidence=0.8, run_id="run-ok"))
        report = await revalidate_claims(
            store, cog, env_old="v1", env_new="v2",
            affected_scope={"region": "prod"}, verifiers={})
        assert report.affected_count == 1
        assert report.kept == 1 and report.refuted == 0
        assert report.items[0].action == "kept"
        assert cog.get("good").confidence == 0.8  # 置信不变
        revalidated = [e for e in store.iter_run_events("cognition")
                       if e.type == "claim.revalidated"]
        assert revalidated[-1].payload["verdict"] == "pass"
        assert revalidated[-1].payload["env_version"] == "v2"

    async def test_fail_decays_confidence(self, store) -> None:
        """AC：失败者按衰减规则降置信（claim.confidence_decayed）。
        0.5 × 0.5 = 0.25 ≥ refute_below(0.2) → decayed 不推翻。"""
        cog = CognitionService(store)
        await cog.propose(claim("stale", confidence=0.5))  # 无源 run→fail
        report = await revalidate_claims(
            store, cog, env_old="v1", env_new="v2",
            affected_scope={"region": "prod"}, verifiers={})
        assert report.decayed == 1
        assert report.items[0].confidence_after == pytest.approx(0.25)
        assert cog.get("stale").confidence == pytest.approx(0.25)
        decayed = [e for e in store.iter_run_events("cognition")
                   if e.type == "claim.confidence_decayed"]
        assert decayed[-1].payload["confidence_after"] == pytest.approx(0.25)

    async def test_fail_below_threshold_refutes_with_propagation(
            self, store) -> None:
        """AC：低于推翻线 → claim.refuted（复用既有级联失效——下游
        随依赖图推翻并计入 propagated）。0.3 × 0.5 = 0.15 < 0.2。"""
        cog = CognitionService(store)
        await cog.propose(claim("bad", confidence=0.3))
        await cog.propose(claim("child", depends_on=["bad"]))
        report = await revalidate_claims(
            store, cog, env_old="v1", env_new="v2",
            affected_scope={"region": "prod"}, verifiers={})
        assert report.refuted == 1
        item = report.items[0]
        assert item.action == "refuted"
        assert "child" in item.propagated  # 级联失效入报告
        assert cog.get("bad").status == "refuted"
        assert cog.get("child").status == "refuted"
        refuted = [e for e in store.iter_run_events("cognition")
                   if e.type == "claim.refuted"]
        assert len(refuted) == 2  # bad + 级联 child

    async def test_custom_policy(self, store) -> None:
        """衰减规则可配：factor=0.9、refute_below=0.4 → 0.5×0.9=0.45
        保留；同值在默认规则（0.25>0.2）也保留——换 refute_below=0.5
        则推翻。"""
        cog = CognitionService(store)
        await cog.propose(claim("p", confidence=0.5))
        report = await revalidate_claims(
            store, cog, env_old="v1", env_new="v2",
            affected_scope={"region": "prod"}, verifiers={},
            policy=DecayPolicy(decay_factor=0.9, refute_below=0.4))
        assert report.decayed == 1
        assert report.items[0].confidence_after == pytest.approx(0.45)

    async def test_report_counts_consistent(self, store) -> None:
        """影响面报告：kept+decayed+refuted == affected_count。"""
        await make_clean_run(store, "run-fine")
        cog = CognitionService(store)
        await cog.propose(claim("keep", confidence=0.9, run_id="run-fine"))
        await cog.propose(claim("decay", confidence=0.5))
        await cog.propose(claim("kill", confidence=0.1))
        report = await revalidate_claims(
            store, cog, env_old="v1", env_new="v2",
            affected_scope={"region": "prod"}, verifiers={})
        assert report.affected_count == 3
        assert report.kept + report.decayed + report.refuted == 3
        assert len(report.items) == 3
        assert {i.action for i in report.items} == {"kept", "decayed",
                                                    "refuted"}


class TestSeedCI:
    """W-1（AC-07 CI）计算面——解除条件挂载（真实适配器接入后并入
    评测报告即解除；当前豁免维持——披露）。"""

    def test_known_values(self) -> None:
        """[1,2,3] @95%：mean=2, σ=1, half=1.96/√3≈1.1316。"""
        ci = seed_confidence_interval([1.0, 2.0, 3.0])
        assert ci["n"] == 3
        assert ci["mean"] == pytest.approx(2.0)
        assert ci["half_width"] == pytest.approx(1.96 / 3**0.5, abs=1e-4)
        assert ci["low"] == pytest.approx(2.0 - 1.96 / 3**0.5, abs=1e-4)
        assert ci["high"] == pytest.approx(2.0 + 1.96 / 3**0.5, abs=1e-4)
        assert ci["level"] == 0.95

    def test_identical_samples_zero_width(self) -> None:
        ci = seed_confidence_interval([0.8] * 10)
        assert ci["half_width"] == 0.0
        assert ci["low"] == ci["high"] == pytest.approx(0.8)

    def test_levels_supported(self) -> None:
        wide = seed_confidence_interval([1.0, 2.0, 3.0], level=0.99)
        narrow = seed_confidence_interval([1.0, 2.0, 3.0], level=0.90)
        assert wide["half_width"] > narrow["half_width"]

    def test_needs_two_seeds(self) -> None:
        with pytest.raises(VastaError) as excinfo:
            seed_confidence_interval([0.5])
        assert excinfo.value.code == "revalidation.ci_needs_seeds"

    def test_bad_level_rejected(self) -> None:
        with pytest.raises(VastaError):
            seed_confidence_interval([1.0, 2.0], level=0.5)
