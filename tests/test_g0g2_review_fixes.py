"""Epic 10 G0-G2 评审修复锚定（四层评审 patch 项集中）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from vasta_protocols.errors import VastaError
from vasta_protocols.ids import now_utc
from vasta_protocols.schema_registry import (
    CURRENT_VERSION,
    MIGRATIONS,
    envelope_json_schema,
    event_catalog,
)
from vasta_storage import SqliteStorage
from vastacore.governance.audit_export import (
    AuditExportQuery,
    export_audit_json,
)
from vastacore.governance.drift import DriftMetrics, run_drift_check
from vastacore.governance.quotas import CostLedger
from vastacore.governance.release import (
    _get_state_sync,
    promote_release,
    resume_release,
    revoke_release,
    rollback_release,
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


async def seed_versions(store, *versions: str) -> None:
    for v in versions:
        await publish_model_version(store, "grid", v, ruleset=RULESET,
                                    manifest=MANIFEST)


async def to_active(store, version: str, approver: str = "r") -> None:
    for to in ("testing", "shadow", "canary"):
        await promote_release(store, "model", "grid", version, to=to)
    await promote_release(store, "model", "grid", version, to="active",
                          approver=approver)


class TestSchemaPatternFix:
    def test_all_catalog_events_match_pattern(self) -> None:
        """F1 锚定：目录全部事件类型逐一匹配；倒置形态拒。"""
        import re

        pat = re.compile(
            envelope_json_schema()["properties"]["type"]["pattern"])
        all_types = [f"{fam}.{ev}" for fam, evs in event_catalog().items()
                     for ev in evs]
        assert len(all_types) >= 70
        for t in all_types:
            assert pat.match(t), t
        for illegal in ("foo.run.bar", "x.run", "run", "schedule.created"):
            assert not pat.match(illegal), illegal

    def test_register_requires_dotted(self) -> None:
        """L3：无点分形态拒（非裸 IndexError）。"""
        from vasta_protocols.schema_registry import register_event_type

        with pytest.raises(ValueError, match="点分"):
            register_event_type("claim")

    def test_breaking_changes_boolean_schema_no_crash(self) -> None:
        """L4：布尔 schema（JSON Schema 合法形态）不崩。"""
        from vasta_protocols.schema_registry import detect_breaking_changes

        old = {"properties": {"x": True, "y": {"type": "string"}}}
        new = {"properties": {"y": {"type": "integer"}}}
        changes = detect_breaking_changes(old, new)
        assert "field-removed:x" in changes
        assert "type-changed:y:string->integer" in changes

    def test_migrate_none_version_rejected_cleanly(self) -> None:
        """L6：schema_version=None 拒（不再把 'None' 当版本）。"""
        from vasta_protocols.schema_registry import migrate_envelope

        with pytest.raises(ValueError, match="schema_version"):
            migrate_envelope({"run_id": "r", "schema_version": None})

    def test_migration_chain_cycle_terminated(self) -> None:
        """G3(c)：注册环迁移链不死循环（BFS seen 防环）。"""
        from vasta_protocols.schema_registry import migrate_envelope

        MIGRATIONS[("0.0.1", "0.0.2")] = lambda e: e
        MIGRATIONS[("0.0.2", "0.0.1")] = lambda e: e  # 环
        try:
            with pytest.raises(ValueError, match="无迁移链"):
                migrate_envelope(
                    {"schema_version": "0.0.1"}, to_version=CURRENT_VERSION)
        finally:
            MIGRATIONS.pop(("0.0.1", "0.0.2"), None)
            MIGRATIONS.pop(("0.0.2", "0.0.1"), None)


class TestReleaseHardening:
    async def test_promote_to_revoked_rejected(self, store) -> None:
        """F2 锚定：promote(to=revoked) 拒——吊销只走 revoke_release
        （复核门+级联）。suspended/retired 同理。"""
        await seed_versions(store, "1.0.0")
        for to in ("revoked", "suspended", "retired"):
            with pytest.raises(VastaError) as excinfo:
                await promote_release(store, "model", "grid", "1.0.0", to=to)
            assert excinfo.value.code == "release.invalid_transition"
            assert "revoke_release" in excinfo.value.message \
                or "suspend_release" in excinfo.value.message \
                or "retire_release" in excinfo.value.message
        # 无任何 approvals 流事件（门未绕过）
        assert not list(store.iter_run_events("approvals"))

    async def test_suspend_resume_revoke_active_not_referenced(
            self, store) -> None:
        """F4/G1(c) 锚定：suspend→resume→revoke 后 _active 不指向吊销
        版本（重放去重活跃序）。"""
        await seed_versions(store, "1.0.0")
        await to_active(store, "1.0.0")
        await suspend_release(store, "model", "grid", "1.0.0", reason="d")
        await resume_release(store, "model", "grid", "1.0.0", reason="r")
        await revoke_release(store, "model", "grid", "1.0.0",
                             reason="bad", approver="sec")
        state = _get_state_sync(store, "model", "grid")
        assert state["1.0.0"] == "revoked"
        assert "_active" not in state  # 不再引用吊销版本

    async def test_rollback_after_revoke_refused(self, store) -> None:
        """F4 锚定：吊销终态不可被 rollback 抹掉。"""
        await seed_versions(store, "1.0.0", "2.0.0")
        await to_active(store, "1.0.0")
        await to_active(store, "2.0.0")
        await revoke_release(store, "model", "grid", "2.0.0",
                             reason="bad", approver="sec")
        # 活跃序只剩 1.0.0（revoked 已移除）→ 无第二活跃 → rollback 拒
        with pytest.raises(VastaError):
            await rollback_release(store, "model", "grid")
        assert _get_state_sync(store, "model", "grid")["2.0.0"] == "revoked"

    async def test_resume_conflict_with_other_active(self, store) -> None:
        """M1 锚定：他版本服务中 resume → active_conflict 拒（防双
        current；promote 灰度替换是设计内让位）。"""
        await seed_versions(store, "1.0.0", "2.0.0")
        await to_active(store, "1.0.0")
        await suspend_release(store, "model", "grid", "1.0.0", reason="d")
        await to_active(store, "2.0.0")
        with pytest.raises(VastaError) as excinfo:
            await resume_release(store, "model", "grid", "1.0.0", reason="r")
        assert excinfo.value.code == "release.active_conflict"

    async def test_rollback_target_suspended_not_candidate(
            self, store) -> None:
        """M2 锚定：挂起版本不再作为回滚目标——去重活跃序下挂起即
        出序，rollback 找不到可服务的前一版本（比旧栈式实现的
        no_serviceable_target 更早拦住——语义：挂起版本不承接流量）。"""
        await seed_versions(store, "1.0.0", "2.0.0")
        await to_active(store, "1.0.0")
        await suspend_release(store, "model", "grid", "1.0.0", reason="d")
        await to_active(store, "2.0.0")
        with pytest.raises(VastaError) as excinfo:
            await rollback_release(store, "model", "grid")
        assert excinfo.value.code == "release.no_previous_active"
        # 且 1.0.0 保持 suspended（未被回滚改写）
        assert _get_state_sync(store, "model", "grid")["1.0.0"] ==             "suspended"

    async def test_suspend_resume_rollback_no_self_rollback(
            self, store) -> None:
        """M3 锚定：suspend→resume→rollback 不再自回滚（resume 不重复
        入活跃序）。"""
        await seed_versions(store, "1.0.0")
        await to_active(store, "1.0.0")
        await suspend_release(store, "model", "grid", "1.0.0", reason="d")
        await resume_release(store, "model", "grid", "1.0.0", reason="r")
        with pytest.raises(VastaError) as excinfo:  # 首次 active 不可回滚
            await rollback_release(store, "model", "grid")
        assert excinfo.value.code == "release.no_previous_active"


class TestDriftHardening:
    async def test_phantom_version_rejected(self, store) -> None:
        """M5：幻影版本跑漂移检测拒（不留治理事件）。"""
        with pytest.raises(VastaError) as excinfo:
            await run_drift_check(store, "model", "ghost", "9.9.9",
                                  DriftMetrics(success_rate=0.1))
        assert excinfo.value.code == "release.version_not_published"
        assert not list(store.iter_run_events("evaluation"))

    async def test_evaluator_exception_degrades_not_aborts(
            self, store) -> None:
        """M6：evaluator 异常按重验证失败继续链路（incident 照发）。"""

        async def exploding(kind, name, version, bundle):
            raise RuntimeError("lab backend down")

        await seed_versions(store, "1.0.0")
        report = await run_drift_check(
            store, "model", "grid", "1.0.0", DriftMetrics(success_rate=0.5),
            evaluator=exploding)
        assert report.revalidation_passed is False
        assert report.incident_id is not None  # 链路完整
        assert report.recommended_action == "suspend"

    async def test_alerts_persisted_in_measured_event(self, store) -> None:
        """F10/G2(d)：告警结果并入 measured 事件（可观测——原死算）。"""
        await seed_versions(store, "1.0.0")
        await run_drift_check(store, "model", "grid", "1.0.0",
                              DriftMetrics(success_rate=0.5))
        measured = [e for e in store.iter_run_events("evaluation")
                    if e.type == "evaluation.model_drift_measured"][-1]
        assert measured.payload["alerts_fired"], "告警必须可观测"
        assert measured.payload["alerts_fired"][0]["name"] == \
            "model_drift_detected"

    async def test_billing_match_is_exact_not_prefix(self, store) -> None:
        """G2(c)：billing 反查精确匹配（前缀同名的无关模型不混入）。"""
        await seed_versions(store, "1.0.0")
        await CostLedger.record(store, "run-grid", tenant_id="t-default",
                                project_id="p-default", model="grid",
                                estimated_cost=0.1, basis="usage")
        await CostLedger.record(store, "run-gridx", tenant_id="t-default",
                                project_id="p-default", model="gridx",
                                estimated_cost=0.1, basis="usage")
        report = await run_drift_check(
            store, "model", "grid", "1.0.0", DriftMetrics(success_rate=0.5))
        assert report.affected_runs == ["run-grid"]  # gridx 不混入

    async def test_incident_subject_not_fake_run(self, store) -> None:
        """F10：无消费 run 时 incident 携 subject（不伪装 run id）。"""
        await seed_versions(store, "1.0.0")
        await run_drift_check(store, "model", "grid", "1.0.0",
                              DriftMetrics(success_rate=0.5))
        declared = [e for e in store.iter_run_events("incidents")
                    if e.type == "incident.declared"][-1]
        assert declared.payload["related_runs"] == []
        assert declared.payload["subject"] == "model/grid:1.0.0"

    async def test_drift_thresholds_exclusive(self) -> None:
        """G3(a)：三通道恰在阈值上不触发（严格 < / >）。"""
        from vastacore.governance.drift import evaluate_drift

        drifted, _ = evaluate_drift(
            DriftMetrics(success_rate=0.90, revalidation_fail_rate=0.10,
                         distribution_shift=0.20),
            __import__("vastacore.governance.drift",
                       fromlist=["DriftPolicy"]).DriftPolicy())
        assert drifted is False


class TestAuditWindowAndRuns:
    async def test_naive_window_interpreted_as_utc(self, store) -> None:
        """F5 锚定：naive 查询窗按 UTC 解释（不再裸 TypeError）。"""
        await seed_versions(store, "1.0.0")  # registry 事件
        now = now_utc()
        export = export_audit_json(store, AuditExportQuery(
            start_ts=now.replace(tzinfo=None) - timedelta(hours=1),
            end_ts=now.replace(tzinfo=None) + timedelta(hours=1)))
        assert export.total_events >= 1  # naive 窗正常工作

    async def test_window_boundary_inclusive(self, store) -> None:
        """G3：窗等值端点双侧包含（<= 语义）。"""
        from vastacore.governance.approvals import record_approval

        await record_approval(store, tool="t", args={}, approver="a",
                              scope="t-default:p-default", ttl_s=60)
        events = list(store.iter_run_events("approvals"))
        ts = events[0].ts
        export = export_audit_json(store, AuditExportQuery(
            start_ts=ts, end_ts=ts))
        assert export.total_events == 1  # 恰在端点

    async def test_include_runs_actually_includes(self, store) -> None:
        """M4/F6 锚定：include_runs=True 真实生效（原死旗）。"""
        from vasta_protocols.sequencer import EventSequencer

        await EventSequencer(store, "run-biz-1").emit("run.created", {})
        off = export_audit_json(store, AuditExportQuery(
            start_ts=datetime(2026, 1, 1, tzinfo=UTC),
            end_ts=datetime(2027, 1, 1, tzinfo=UTC)))
        assert "run-biz-1" not in off.streams  # 默认不含
        on = export_audit_json(store, AuditExportQuery(
            start_ts=datetime(2026, 1, 1, tzinfo=UTC),
            end_ts=datetime(2027, 1, 1, tzinfo=UTC), include_runs=True))
        assert "run-biz-1" in on.streams  # 打开后含
