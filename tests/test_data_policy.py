"""Story 10.11：驻留、保留与法律保留策略（FR-073，G4）。"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vasta_storage.lifecycle import place_legal_hold
from vastacore.governance.data_policy import (
    DataPolicy,
    JurisdictionRule,
    RetentionRule,
    configure_data_policy,
    disposal_drill,
    enforce_residency,
    pg_backup_command,
    pg_restore_command,
    retention_due,
    verify_residency,
)

POLICY = DataPolicy(
    region="eu-west",
    retention_rules=[
        RetentionRule(classification="raw-pii", retain_days=30),
        RetentionRule(classification="derived", retain_days=400,
                      disposition="archive"),
    ],
    jurisdiction_rules=[
        JurisdictionRule(jurisdiction="GDPR", minimum_hold_days=90),
    ],
    default_retain_days=365,
)


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


async def put(store, payload: bytes, *, classification=None, age_days=0):
    sha = await store.save_artifact(
        payload, classification=classification,
        tenant_id="t-default", project_id="p-default")
    if age_days:
        with store._lock, store._conn:  # noqa: SLF001——测试调龄
            store._conn.execute(  # noqa: SLF001
                "UPDATE artifacts SET created_at = datetime('now', ?)"
                " WHERE sha256 = ?", (f'-{int(age_days)} days', sha))
    return sha


class TestRetentionDue:
    async def test_classification_and_age_drive_due(self, store) -> None:
        """AC：保留到期自动处置建议——分类保留期驱动（PII 30 天到期
        / 未分类默认 365）。"""
        await put(store, b"pii-old", classification="raw-pii", age_days=45)
        await put(store, b"pii-young", classification="raw-pii", age_days=10)
        await put(store, b"unclass", age_days=400)
        due = retention_due(store, POLICY)
        assert len(due) == 2  # pii-old + unclass（400>365）
        pii = [c for c in due if c.classification == "raw-pii"][0]
        assert pii.disposition == "delete"

    async def test_disposition_archive(self, store) -> None:
        await put(store, b"der", classification="derived", age_days=450)
        due = retention_due(store, POLICY)
        assert due[0].disposition == "archive"

    async def test_jurisdiction_minimum_extends(self, store) -> None:
        """管辖域最低期与分类保留取严：PII 30 天保留但 GDPR 90 天
        最低期——60 天龄未到期（45 天测试反向证明）。"""
        sha = await put(store, b"pii-gdpr", classification="raw-pii",
                        age_days=60)
        await place_legal_hold(store, sha, jurisdiction="GDPR",
                               tenant_id="t-default",
                               project_id="p-default")
        due = retention_due(store, POLICY)
        mine = [c for c in due if c.sha256 == sha]
        assert mine == []  # 60 < 90 最低期——未到期
        # 超 90 天后 → 到期但 blocked（活跃 hold）
        await put(store, b"x", age_days=0)  # noop 保持 store 活性
        with store._lock, store._conn:  # noqa: SLF001
            store._conn.execute(  # noqa: SLF001
                "UPDATE artifacts SET created_at = datetime('now','-120 days')"
                " WHERE sha256 = ?", (sha,))
        due2 = retention_due(store, POLICY)
        blocked = [c for c in due2 if c.sha256 == sha]
        assert blocked and blocked[0].blocked_by_hold is True


class TestResidency:
    def test_matching_region_ok(self, tmp_path) -> None:
        assert verify_residency(
            tmp_path / "region-eu-west" / "store", POLICY) == []

    def test_wrong_region_violation(self, tmp_path) -> None:
        v = verify_residency(tmp_path / "region-us-east" / "store", POLICY)
        assert v and "us-east" in v[0] and "eu-west" in v[0]

    def test_unmarked_fails_closed(self, tmp_path) -> None:
        v = verify_residency(tmp_path / "plain" / "store", POLICY)
        assert v and "无区域标记" in v[0]

    def test_enforce_raises(self, tmp_path) -> None:
        with pytest.raises(VastaError) as excinfo:
            enforce_residency(tmp_path / "x", POLICY)
        assert excinfo.value.code == "data.residency_violation"


class TestTraceAndDrill:
    async def test_policy_config_traced(self, store) -> None:
        await configure_data_policy(store, POLICY,
                                    tenant_id="t-default",
                                    project_id="p-default")
        events = [e for e in store.iter_run_events("lifecycle")
                  if e.type == "artifact.retention_configured"]
        assert events[-1].payload["region"] == "eu-west"
        assert events[-1].payload["retention_rules"][0][
            "classification"] == "raw-pii"

    async def test_disposal_drill_report(self, store) -> None:
        """AC：处置演练报告——到期清单+冲突面+执行指引。"""
        await put(store, b"old", classification="raw-pii", age_days=100)
        report = disposal_drill(store, POLICY)
        assert report["total_due"] == 1
        assert report["to_delete"] == 1
        assert "request_deletion" in report["execution_note"]


class TestPgBackupCommands:
    def test_backup_command_shape(self, tmp_path) -> None:
        """C4 PG 备份：命令构造纯函数——DSN 走 --dbname（可含密码的
        DSN 不进 argv 额外段；custom 格式支持选择性恢复）。"""
        cmd = pg_backup_command("postgresql://u:p@h/db",
                                tmp_path / "b.dump")
        assert cmd[0] == "pg_dump"
        assert "--dbname=postgresql://u:p@h/db" in cmd
        assert "--format=custom" in cmd
        assert f"--file={tmp_path / 'b.dump'}" in cmd

    def test_restore_command_shape(self, tmp_path) -> None:
        cmd = pg_restore_command(tmp_path / "b.dump",
                                 "postgresql://drill/db")
        assert cmd[0] == "pg_restore"
        assert "--clean" in cmd
        assert str(tmp_path / "b.dump") in cmd
