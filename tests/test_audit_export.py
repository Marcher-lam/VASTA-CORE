"""Story 10.6：企业审计导出（FR-068，G2）。

JSON 只读导出（窗/作用域/引用清单化不含内容）；五节 HTML 报告；
导出留痕。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from vasta_cognition.cognition import Claim, CognitionService
from vasta_protocols.ids import now_utc
from vasta_protocols.sequencer import EventSequencer
from vasta_storage import SqliteStorage
from vastacore.governance.approvals import record_approval
from vastacore.governance.audit_export import (
    AuditExportQuery,
    export_audit_json,
    export_audit_json_traced,
    render_audit_html,
)
from vastacore.governance.quotas import CostLedger, QuotaEnforcer, QuotaSpec
from vastacore.ops.ops import declare_incident


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


async def seed(store) -> None:
    """种五节各至少一条 + 一条恶意内容（XSS 转义验证用）。"""
    await record_approval(store, tool="ship", args={}, approver="alice",
                          scope="t-default:p-default", ttl_s=600)
    await CostLedger.record(store, "run-1", tenant_id="t-default",
                            project_id="p-default", model="grid",
                            calls=2, estimated_cost=0.10, basis="usage")
    await CostLedger.record(store, "run-1", tenant_id="t-default",
                            project_id="p-default", model="grid",
                            calls=1, estimated_cost=0.05, basis="usage")
    await declare_incident(store, "演示事故", related_runs=["run-1"],
                           severity="sev2")
    enforcer = QuotaEnforcer(store)
    await enforcer.configure("t-default", "p-default",
                             QuotaSpec(requests_per_min=1))
    await enforcer.check_rate("t-default", "p-default")
    from vastacore.governance.quotas import QuotaExceededError

    with pytest.raises(QuotaExceededError):
        await enforcer.check_rate("t-default", "p-default")  # throttled
    cog = CognitionService(store)
    await cog.propose(Claim(
        claim_id="x1", memory_type="working",
        statement='<img src=x onerror=alert(1)>', scope={}))
    # 带 artifact_refs 的事件（引用清单化验证）
    await EventSequencer(store, "lifecycle", tenant_id="t-default",
                         project_id="p-default").emit(
        "artifact.deletion_proved",
        {"sha256": "a" * 64, "artifact_refs": ["b" * 64],
         "contract_ref": "c" * 64})


def query(**kw) -> AuditExportQuery:
    """窗在**调用时**动态取（种子事件落真实时钟——静态常量会因
    模块导入与执行的时间差把事件留在窗外）。"""
    now = now_utc()
    defaults = dict(start_ts=now - timedelta(hours=1),
                    end_ts=now + timedelta(hours=1),
                    tenant_id="t-default", project_id="p-default")
    defaults.update(kw)
    return AuditExportQuery(**defaults)


class TestJsonExport:
    async def test_window_and_scope_filters(self, store) -> None:
        await seed(store)
        export = export_audit_json(store, query())
        assert export.total_events >= 7
        # 作用域隔离：他租户视角为空
        other = export_audit_json(store, query(tenant_id="t-other",
                                               project_id="p-other"))
        assert other.total_events == 0
        # 窗过滤：未来窗为空（种子事件都在过去/现在）
        now = now_utc()
        future = export_audit_json(
            store, query(start_ts=now + timedelta(days=1),
                         end_ts=now + timedelta(days=2)))
        assert future.total_events == 0

    async def test_artifact_refs_listed_without_content(self, store) -> None:
        """AC：工件引用清单化——sha 清单在，blob 内容绝不在。"""
        await seed(store)
        export = export_audit_json(store, query())
        assert "b" * 64 in export.artifact_refs
        assert "c" * 64 in export.artifact_refs
        dump = export.model_dump_json()
        assert "payload" in dump  # 事件 payload 在（信封字段）
        # 不含 blob 内容（种子里没有任何 base64 工件内容——结构性：
        # 导出体只含信封 + sha 清单，无内容字段）
        assert "content" not in export.model_fields
        assert "blob" not in export.model_fields

    async def test_run_streams_not_included_by_default(self, store) -> None:
        """run 业务流默认不在审计面（治理流面）。"""
        await EventSequencer(store, "run-biz").emit("run.created", {})
        export = export_audit_json(store, query())
        assert "run-biz" not in export.streams

    async def test_empty_window_valid_export(self, store) -> None:
        export = export_audit_json(store, query())
        assert export.total_events == 0
        assert export.streams == {}
        assert "（本窗无记录）" in render_audit_html(export)


class TestHtmlReport:
    async def test_five_sections_rendered(self, store) -> None:
        """AC：五节——时间线/批准/访问拒绝/事故/成本。"""
        await seed(store)
        export = export_audit_json(store, query())
        html_text = render_audit_html(export)
        for section in ("时间线", "批准", "访问拒绝", "事故", "成本"):
            assert section in html_text
        assert "alice" in html_text          # 批准节
        assert "run.throttled" in html_text  # 访问拒绝节（限流）
        assert "演示事故" in html_text        # 事故节
        assert "0.150000" in html_text       # 成本节（0.10+0.05）

    async def test_html_escapes_untrusted_content(self, store) -> None:
        """XSS 防护：恶意 statement 转义（9.13 F10 教训）。"""
        await seed(store)
        export = export_audit_json(store, query())
        html_text = render_audit_html(export)
        assert "<img src=x" not in html_text
        assert "&lt;img src=x" in html_text  # 转义后出现


class TestExportTrace:
    async def test_export_leaves_audit_trace(self, store) -> None:
        """AC：导出留痕（evaluation.audit_exported——窗/计数/导出人）。"""
        await seed(store)
        export = await export_audit_json_traced(
            store, query(exported_by="auditor@corp"))
        traces = [e for e in store.iter_run_events("evaluation")
                  if e.type == "evaluation.audit_exported"]
        assert len(traces) == 1
        p = traces[0].payload
        assert p["exported_by"] == "auditor@corp"
        assert p["total_events"] == export.total_events
        assert p["artifact_refs_count"] == len(export.artifact_refs)
