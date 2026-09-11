"""Story 10.10：审计日志聚合（FR-071 尾，G3）。

四元组归一（主体→动作→资源→结果）；三维过滤；导出接 10.6；
不可篡改声明（链式摘要可重算）。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from vasta_cognition.cognition import Claim, CognitionService
from vasta_protocols.ids import now_utc
from vasta_storage import SqliteStorage
from vastacore.governance.approvals import record_approval
from vastacore.governance.audit_export import (
    AuditExportQuery,
    export_audit_json,
)
from vastacore.governance.audit_log import (
    AuditLogQuery,
    audit_log_integrity_statement,
    query_audit_log,
)
from vastacore.governance.quotas import QuotaEnforcer, QuotaSpec
from vastacore.governance.rbac import Role, assign_role
from vastacore.governance.release import revoke_release
from vastacore.governance.versioning import publish_model_version

RULESET = {"rules": {}, "goal_check": "done"}
MANIFEST = {"name": "grid", "version": "1.0", "scope": "grid",
            "unknowns": ["u"], "coverage": ["right"]}


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


async def seed(store) -> None:
    """种四类主体动作：批准/角色分配/访问拒绝/吊销。"""
    await record_approval(store, tool="ship", args={"x": 1},
                          approver="alice@corp", scope="t:p", ttl_s=600)
    await assign_role(store, "bob@corp", Role.OPERATOR,
                      assigned_by="admin-root",
                      tenant_id="t-default", project_id="p-default")
    enforcer = QuotaEnforcer(store)
    await enforcer.configure("t-default", "p-default",
                             QuotaSpec(requests_per_min=1))
    await enforcer.check_rate("t-default", "p-default")
    from vastacore.governance.quotas import QuotaExceededError

    with pytest.raises(QuotaExceededError):
        await enforcer.check_rate("t-default", "p-default")  # throttled
    cog = CognitionService(store)
    await cog.propose(Claim(claim_id="cx", memory_type="working",
                            statement="s", scope={}))
    await publish_model_version(store, "grid", "1.0.0", ruleset=RULESET,
                                manifest=MANIFEST)
    await revoke_release(store, "model", "grid", "1.0.0",
                         reason="bad", approver="sec@corp")


def query(**kw) -> AuditLogQuery:
    now = now_utc()
    defaults = dict(start_ts=now - timedelta(hours=1),
                    end_ts=now + timedelta(hours=1))
    defaults.update(kw)
    return AuditLogQuery(**defaults)


class TestNormalization:
    async def test_quad_normalized_across_streams(self, store) -> None:
        """四元组归一：各流事件 → 主体/动作/资源/结果。"""
        await seed(store)
        entries = query_audit_log(store, query())
        # 多条 approval_record（ship 批准 + revoke 复核）——按主体取
        approvals_alice = [e for e in entries
                           if e.action == "action.approval_record"
                           and e.principal == "alice@corp"]
        ap = approvals_alice[0]
        assert ap.resource.startswith("apr-ship-")
        assert ap.result == "success"
        # 角色分配：assigned_by 主体
        ra = [e for e in entries
              if e.action == "run.role_assigned"
              and e.principal == "admin-root"][0]
        assert ra.principal == "admin-root"
        assert ra.resource == "bob@corp"  # user 字段作资源
        assert ra.result == "success"
        # 限流：denied
        th = [e for e in entries if e.action == "run.throttled"][0]
        assert th.result == "denied"
        # 吊销：approver + kind/name/version 资源
        rv = [e for e in entries
              if e.action == "release.transition"][0]
        assert rv.principal == "sec@corp"
        assert rv.resource == "model/grid/1.0.0"

    async def test_result_classification(self, store) -> None:
        await seed(store)
        entries = query_audit_log(store, query())
        results = {e.action: e.result for e in entries}
        assert results["run.throttled"] == "denied"
        assert results["action.approval_record"] == "success"

    async def test_entries_sorted_by_ts(self, store) -> None:
        await seed(store)
        entries = query_audit_log(store, query())
        ts_list = [e.ts for e in entries]
        assert ts_list == sorted(ts_list)

    async def test_unknown_falls_to_defaults(self, store) -> None:
        """无主体/资源字段的事件不丢——system/unknown 兜底。"""
        from vasta_protocols.sequencer import EventSequencer

        await EventSequencer(store, "schedules").emit(
            "plan.fired", {"schedule_id": "sch-1"})  # 无主体字段
        entries = query_audit_log(store, query())
        fired = [e for e in entries if e.action == "plan.fired"]
        assert len(fired) == 1
        assert fired[0].principal == "system"
        assert fired[0].resource == "unknown"


class TestFilters:
    async def test_filter_by_principal(self, store) -> None:
        await seed(store)
        entries = query_audit_log(store, query(principal="alice@corp"))
        assert entries
        assert all(e.principal == "alice@corp" for e in entries)

    async def test_filter_by_resource_prefix(self, store) -> None:
        await seed(store)
        entries = query_audit_log(store, query(resource_prefix="model/"))
        assert entries
        assert all(e.resource.startswith("model/") for e in entries)

    async def test_filter_by_action_prefix(self, store) -> None:
        await seed(store)
        entries = query_audit_log(store, query(action_prefix="run."))
        assert all(e.action.startswith("run.") for e in entries)
        assert any(e.action == "run.throttled" for e in entries)

    async def test_window_excludes_old(self, store) -> None:
        await seed(store)
        old = now_utc() - timedelta(days=2)
        entries = query_audit_log(store, query(
            start_ts=old - timedelta(hours=1),
            end_ts=old + timedelta(hours=1)))
        assert entries == []


class TestIntegrityStatement:
    async def test_statement_recomputable(self, store) -> None:
        """链式摘要可重算（同源流两跑一致）；追加事件后变化。"""
        from vasta_protocols.sequencer import EventSequencer

        await EventSequencer(store, "access").emit(
            "run.role_assigned", {"user": "u", "role": "viewer",
                                  "assigned_by": "root"})
        s1 = audit_log_integrity_statement(store)
        s2 = audit_log_integrity_statement(store)  # 只读重算
        assert s1["chain_sha256_tail"] == s2["chain_sha256_tail"]
        assert s1["total_events"] == 1
        await EventSequencer(store, "access").emit(
            "run.role_assigned", {"user": "u2", "role": "admin",
                                  "assigned_by": "root"})
        s3 = audit_log_integrity_statement(store)
        assert s3["chain_sha256_tail"] != s1["chain_sha256_tail"]
        assert s3["total_events"] == 2
        assert "AD-2" in s1["statement"]
        assert "verify_stream_integrity" in s1["statement"]


class TestExportIntegration:
    async def test_export_carries_audit_log(self, store) -> None:
        """导出接 10.6：include_audit_log=True 附四元组条目。"""
        await seed(store)
        now = now_utc()
        q = dict(start_ts=now - timedelta(hours=1),
                 end_ts=now + timedelta(hours=1))
        off = export_audit_json(store, AuditExportQuery(**q))
        assert off.audit_log == []  # 默认不含
        on = export_audit_json(store, AuditExportQuery(
            include_audit_log=True, **q))
        assert len(on.audit_log) == on.total_events  # 全量归一
        quad = on.audit_log[0]
        assert {"ts", "principal", "action", "resource", "result",
                "stream", "seq", "event_id"} <= set(quad)
