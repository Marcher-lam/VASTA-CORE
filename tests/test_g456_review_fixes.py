"""Epic 9 G4-G6 评审修复锚定（四层评审 patch 项）。

盲审 H1-H4/边界 F1-F21/验证缺口 G2-G3 的修复行为集中锚定；
散布修复的锚定随各自测试文件（adoption/scheduling/quotas/studio/
ops/sandbox_pool/revalidation/bridge_wiring）。
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vasta_cognition.cognition import Claim, CognitionService
from vasta_eval import VastaLabTask
from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer
from vasta_storage import SqliteStorage
from vastacore.governance.quotas import CostLedger, QuotaEnforcer, QuotaSpec
from vastacore.governance.revalidation import (
    DecayPolicy,
    revalidate_claims,
    seed_confidence_interval,
)
from vastacore.ops.ops import backup_snapshot, restore_snapshot
from vastacore.ops.scheduling import CronSpec, Scheduler, ScheduleSpec


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


class TestSequencerConcurrency:
    async def test_system_stream_parallel_writers_no_spurious_failure(
            self, store) -> None:
        """F3：并发系统流写（各自新建 sequencer）不再随机裸抛
        duplicate_seq——撞号 resync 重试吸收。"""
        async def record_one(i: int) -> None:
            await CostLedger.record(store, f"run-{i}", tenant_id="t",
                                    project_id="p", model="m",
                                    calls=1, estimated_cost=0.1,
                                    basis="usage")

        await asyncio.gather(*(record_one(i) for i in range(8)))
        events = [e for e in store.iter_run_events("billing")
                  if e.type == "run.cost_recorded"]
        assert len(events) == 8  # 全部落账、seq 连续无洞
        assert [e.seq for e in events] == list(range(8))


class TestSchedulingFixes:
    async def test_default_clock_tick_not_crash(self, store) -> None:
        """F2：默认钟（无注入）tick 不抛 naive/aware TypeError。"""
        scheduler = Scheduler(store, executor=None)  # 无 cron → tick 空转
        assert await scheduler.tick() == []
        # 注册远期 cron 再 tick（默认钟路径真跑一次比较）
        async def exec_noop(tasks, root):
            class R:
                runs, success_rate = 0, 0.0
            return R()

        scheduler2 = Scheduler(store, executor=exec_noop)
        await scheduler2.add(ScheduleSpec(schedule_id="d",
                                          cron="0 3 1 1 *",
                                          tasks=[VastaLabTask(task_id="t")]))
        await scheduler2.tick()  # 不抛即过

    async def test_duplicate_schedule_id_rejected(self, store) -> None:
        """M2：重复 schedule_id 拒（曾事件源路径追加双触发）。"""
        async def exec_noop(tasks, root):
            class R:
                runs, success_rate = 0, 0.0
            return R()

        scheduler = Scheduler(store, executor=exec_noop)
        await scheduler.add(ScheduleSpec(schedule_id="dup",
                                         event_source="run.completed",
                                         tasks=[VastaLabTask(task_id="t")]))
        with pytest.raises(VastaError) as excinfo:
            await scheduler.add(ScheduleSpec(schedule_id="dup",
                                             event_source="run.completed",
                                             tasks=[VastaLabTask(task_id="t")]))
        assert excinfo.value.code == "schedule.duplicate"

    def test_never_matching_cron_rejected_fast(self) -> None:
        """F7：2 月 30 日构造期即拒（不再 4 年空扫描）。"""
        with pytest.raises(VastaError) as excinfo:
            CronSpec("0 0 30 2 *")
        assert "永不命中" in excinfo.value.message

    def test_leap_day_within_four_years_accepted(self) -> None:
        """F7：2/29 合法（4 年扫描上限覆盖闰年）。"""
        cron = CronSpec("0 0 29 2 *")
        from datetime import UTC, datetime

        nxt = cron.next_after(datetime(2026, 9, 10, tzinfo=UTC))
        assert (nxt.year, nxt.month, nxt.day) == (2028, 2, 29)

    def test_unicode_digits_rejected(self) -> None:
        """F19：Unicode 数字 cron 拒。"""
        with pytest.raises(VastaError):
            CronSpec("٥ * * * *")


class TestQuotaFixes:
    async def test_nan_inf_negative_cost_rejected(self, store) -> None:
        """F4/F13：NaN/inf/负成本拒（不再毒化台账/充值预算）。"""
        for bad in (float("nan"), float("inf"), -0.9):
            with pytest.raises(VastaError) as excinfo:
                await CostLedger.record(store, "r", tenant_id="t",
                                        project_id="p", model="m",
                                        estimated_cost=bad, basis="usage")
            assert excinfo.value.code == "billing.bad_cost"

    async def test_budget_threshold_on_accumulated_total(self, store) -> None:
        """验证缺口 G2：预算按**累计**判定——多笔记录合计触顶（原测试
        全单行，累计求和零锚定）。"""
        enforcer = QuotaEnforcer(store)
        await enforcer.configure("t", "p", QuotaSpec(budget_total=0.5))
        await CostLedger.record(store, "r1", tenant_id="t", project_id="p",
                                model="m", estimated_cost=0.3, basis="usage")
        await enforcer.check_budget("t", "p")  # 0.3 < 0.5 放行
        await CostLedger.record(store, "r2", tenant_id="t", project_id="p",
                                model="m", estimated_cost=0.2, basis="usage")
        with pytest.raises(VastaError) as excinfo:  # 0.3+0.2=0.5 ≥ 0.5 拒
            await enforcer.check_budget("t", "p")
        assert excinfo.value.code == "quota.budget_exceeded"

    async def test_sliding_window_exact_60s(self, store) -> None:
        """验证缺口 M2：60.0s 精确滑出边界（>= 语义——原测试 61s
        无法区分 > 与 >=）。"""
        from tests.test_quotas import FakeClock

        clock = FakeClock()
        enforcer = QuotaEnforcer(store, clock=clock)
        await enforcer.configure("t", "p", QuotaSpec(requests_per_min=1))
        await enforcer.check_rate("t", "p")
        with pytest.raises(VastaError):
            await enforcer.check_rate("t", "p")
        clock.advance(60.0)  # 恰好 60s——>= 语义下滑出
        await enforcer.check_rate("t", "p")  # 放行


class TestOpsBackupFixes:
    async def test_backup_includes_objects_artifacts(self, store,
                                                     tmp_path) -> None:
        """H3/F6：备份含 objects/——恢复库证据可读（含哈希校验）。"""
        await store.save_artifact(b"evidence-bytes", mime="text/plain",
                                  tenant_id="t", project_id="p")
        await EventSequencer(store, "r1", tenant_id="t",
                             project_id="p").emit(
            "run.created", {"artifact_refs": []})
        backup = backup_snapshot(store, tmp_path / "bk")
        assert (backup / "objects").exists()
        restored_root = restore_snapshot(backup, tmp_path / "rs")
        restored = SqliteStorage(restored_root)
        try:
            got = await restored.get_artifact(
                (await store.save_artifact.__wrapped__ if False else
                 None) or (  # noqa: SLF001 ——直接用原 sha
                    await _first_artifact_sha(store)))
            assert got == b"evidence-bytes"
        finally:
            restored.close()

    async def test_zero_byte_and_corrupt_backup_rejected(self, store,
                                                         tmp_path) -> None:
        """F5：0 字节/非 SQLite 头备份拒（不再静默恢复成空库）。"""
        empty = tmp_path / "empty.db"
        empty.write_bytes(b"")
        with pytest.raises(VastaError) as excinfo:
            restore_snapshot(empty, tmp_path / "r1")
        assert excinfo.value.code == "ops.corrupt_backup"
        garbage = tmp_path / "garbage.db"
        garbage.write_bytes(b"not a sqlite file at all....")
        with pytest.raises(VastaError):
            restore_snapshot(garbage, tmp_path / "r2")

    async def test_parent_break_detected(self, store) -> None:
        """验证缺口 M17b：父链断裂注入检出（原零锚定）。"""
        from vastacore.ops.ops import verify_stream_integrity

        await EventSequencer(store, "r1").emit("run.created", {})
        await EventSequencer(store, "r1").emit("run.started", {})
        import json as _json

        with store._lock, store._conn:  # noqa: SLF001 ——注入父链断裂
            # 读取面走 data JSON（信封重建）——注入须改 JSON 而非列
            row = store._conn.execute(  # noqa: SLF001
                "SELECT data FROM events WHERE run_id='r1' AND seq=1"
            ).fetchone()
            payload = _json.loads(row[0])
            payload["parent_event_id"] = "ghost"
            store._conn.execute(  # noqa: SLF001
                "UPDATE events SET data=? WHERE run_id='r1' AND seq=1",
                (_json.dumps(payload, ensure_ascii=False),))
        report = verify_stream_integrity(store)
        assert report.ok is False
        assert "r1" in report.parent_breaks


async def _first_artifact_sha(store) -> str:
    with store._lock:  # noqa: SLF001 ——测试辅助
        row = store._conn.execute(  # noqa: SLF001
            "SELECT sha256 FROM artifacts LIMIT 1").fetchone()
    return row[0]


class TestStudioTenantIsolation:
    def test_claims_scoped_to_tenant(self, tmp_path) -> None:
        """H2：Studio 认知投影按租户过滤——他租户主张不可见。"""
        from vastacore.ops.studio import mount_studio

        store = SqliteStorage(tmp_path / "iso")

        async def seed() -> None:
            cog_a = CognitionService(store, tenant_id="t-a",
                                     project_id="p-a")
            await cog_a.propose(Claim(claim_id="a1", memory_type="guide",
                                      statement="A 租户主张",
                                      scope={"x": "1"}))
            cog_b = CognitionService(store, tenant_id="t-b",
                                     project_id="p-b")
            await cog_b.propose(Claim(claim_id="b1", memory_type="guide",
                                      statement="B 租户主张",
                                      scope={"x": "1"}))

        asyncio.run(seed())
        app = FastAPI()
        mount_studio(app, store=store, token="tk",
                     tenant_id="t-a", project_id="p-a")
        with TestClient(app) as client:
            rows = client.get("/studio/api/claims",
                              headers={"Authorization": "Bearer tk"}).json()
            ids = {r["claim_id"] for r in rows}
            assert ids == {"a1"}  # b1 不可见（租户隔离）

    def test_projection_refresh_sees_late_writes(self, tmp_path) -> None:
        """F8：mount 后其他实例写入的主张可见（投影刷新）。"""
        from vastacore.ops.studio import mount_studio

        store = SqliteStorage(tmp_path / "late")

        async def seed_and_late() -> None:
            cog = CognitionService(store)
            await cog.propose(Claim(claim_id="early", memory_type="guide",
                                    statement="早", scope={"r": "p"}))

        asyncio.run(seed_and_late())
        app = FastAPI()
        mount_studio(app, store=store, token="tk")
        with TestClient(app) as client:
            asyncio.run(
                CognitionService(store).propose(Claim(
                    claim_id="late", memory_type="guide",
                    statement="晚", scope={"r": "p"})))
            rows = client.get("/studio/api/claims",
                              headers={"Authorization": "Bearer tk"}).json()
            assert {r["claim_id"] for r in rows} == {"early", "late"}


class TestMiscGuards:
    async def test_decay_factor_guard(self, store) -> None:
        """F15：decay_confidence factor 出 (0,1] 拒。"""
        cog = CognitionService(store)
        await cog.propose(Claim(claim_id="c", memory_type="working",
                                statement="s"))
        for bad in (0.0, -1.0, 1.5):
            with pytest.raises(VastaError) as excinfo:
                await cog.decay_confidence("c", factor=bad, reason="x")
            assert excinfo.value.code == "claim.bad_decay_factor"
        assert cog.get("c").confidence == 0.5  # 未被污染

    def test_ci_non_finite_rejected(self) -> None:
        """F16：CI 样本含 NaN 拒（不再静默全 NaN）。"""
        with pytest.raises(VastaError) as excinfo:
            seed_confidence_interval([0.8, float("nan"), 0.9])
        assert excinfo.value.code == "revalidation.ci_non_finite"

    async def test_refute_below_equality_keeps_decayed(self, store) -> None:
        """验证缺口 M14：衰减后恰等于推翻线 → 不推翻（< 严格语义）。"""
        cog = CognitionService(store)
        await cog.propose(Claim(claim_id="edge", memory_type="working",
                                statement="s", confidence=0.4,
                                scope={"r": "p"}))
        report = await revalidate_claims(
            store, cog, env_old="v1", env_new="v2",
            affected_scope={"r": "p"}, verifiers={},
            policy=DecayPolicy(decay_factor=0.5, refute_below=0.2))
        # 0.4 × 0.5 = 0.2 == refute_below → 严格小于不成立 → decayed
        assert report.items[0].action == "decayed"
        assert cog.get("edge").status != "refuted"
