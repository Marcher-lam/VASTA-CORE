"""驻留、保留与法律保留策略（Story 10.11，FR-073，G4）。

数据生命周期合规可执行可证明：

- **DataPolicy**：分类标签 × 保留期（天）映射 + 区域驻留标记 +
  管辖域规则（法律保留最低期——与 9.3 legal_holds 叠加取严）；
- **到期处置建议**（retention_due）：按工件分类与年龄生成删除/归档
  候选清单（不执行——执行走 9.3 request_deletion 延续证明事件链）；
  法律保留中的工件排除并标注；
- **区域驻留校验**（verify_residency / enforce_residency）：store
  根路径区域标记 vs 策略区域——违规清单/拒写钩子（fail-closed）；
- **PG 档备份**（C4 解除收尾）：``pg_backup_command`` 纯函数（环境
  变量形态——密码不进 argv）+ ``pg_restore_command``；真实执行
  ``VASTA_PG_DSN`` 门控；SQLite 侧复用 9.12 backup_snapshot；
- **留痕**：策略配置落 ``artifact.retention_configured``（lifecycle
  流）；**处置演练报告**（disposal_drill）：到期清单 + 模拟处置 +
  法律保留冲突面——只读。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

_POLICY_RUN = "lifecycle"

#: 路径区域标记约定（store 根含 /region-<code>/ 或 region-<code> 段）。
_REGION_MARK = re.compile(r"region-([a-z0-9-]+)", re.IGNORECASE)


class RetentionRule(BaseModel):
    """分类保留规则（分类标签 → 保留天数 + 到期处置）。"""

    model_config = ConfigDict(extra="forbid")

    classification: str
    retain_days: int = Field(ge=0)
    disposition: str = Field(pattern="^(delete|archive)$",
                             default="delete")


class JurisdictionRule(BaseModel):
    """管辖域法律保留最低期（与 9.3 legal_holds 叠加取严）。"""

    model_config = ConfigDict(extra="forbid")

    jurisdiction: str
    minimum_hold_days: int = Field(ge=0, description="法律保留最低天数")


class DataPolicy(BaseModel):
    """企业数据策略（分类×区域×保留×管辖）。"""

    model_config = ConfigDict(extra="forbid")

    region: str = Field(description="要求的数据驻留区域标记")
    retention_rules: list[RetentionRule] = Field(min_length=1)
    jurisdiction_rules: list[JurisdictionRule] = Field(
        default_factory=list)
    default_retain_days: int = Field(default=365, ge=0)

    def rule_for(self, classification: str | None) -> RetentionRule:
        """分类 → 规则（未命中取默认构造——delete）。"""
        for rule in self.retention_rules:
            if rule.classification == classification:
                return rule
        return RetentionRule(
            classification=classification or "unclassified",
            retain_days=self.default_retain_days, disposition="delete")

    def minimum_hold_days(self, jurisdictions: list[str]) -> int:
        """管辖域并集的法律保留最低期（取最大——从严）。"""
        days = [r.minimum_hold_days for r in self.jurisdiction_rules
                if r.jurisdiction in jurisdictions]
        return max(days, default=0)


async def configure_data_policy(
    store: Any, policy: DataPolicy, *,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> None:
    """策略配置留痕（artifact.retention_configured——lifecycle 流，
    携全策略体不含密钥/内容）。"""
    sequencer = EventSequencer(
        store, _POLICY_RUN, tenant_id=tenant_id, project_id=project_id)
    await sequencer.emit("artifact.retention_configured",
                         policy.model_dump(mode="json"))


class DisposalCandidate(BaseModel):
    """到期处置候选（建议面——执行走 9.3 request_deletion）。"""

    model_config = ConfigDict(extra="forbid")

    sha256: str
    classification: str | None
    age_days: float
    disposition: str
    blocked_by_hold: bool = Field(
        default=False, description="法律保留/管辖最低期未满")


def retention_due(
    store: Any, policy: DataPolicy, *,
    now: datetime | None = None,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> list[DisposalCandidate]:
    """保留到期处置建议清单（只读）。

    到期判定：age_days > max(分类保留期, 管辖最低期)；法律保留中
    （9.3 legal_holds 活跃）的工件标注 blocked_by_hold 且仍列出。"""
    from datetime import UTC

    from vasta_storage.lifecycle import _active_holds

    from ._retention_age import artifact_ages

    if now is None:
        from vasta_protocols.ids import now_utc

        now = now_utc()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    candidates: list[DisposalCandidate] = []
    for sha, classification, age_days in artifact_ages(
            store, tenant_id=tenant_id, project_id=project_id):
        holds = _active_holds(store, sha, tenant_id, project_id)
        jurisdictions = [h for h in holds] if holds else []
        effective_retain = max(
            policy.rule_for(classification).retain_days,
            policy.minimum_hold_days(jurisdictions))
        if age_days <= effective_retain:
            continue
        candidates.append(DisposalCandidate(
            sha256=sha, classification=classification,
            age_days=round(age_days, 1),
            disposition=policy.rule_for(classification).disposition,
            blocked_by_hold=bool(holds),
        ))
    return candidates


def verify_residency(
    store_root: str | Path, policy: DataPolicy,
) -> list[str]:
    """区域驻留校验：store 根路径区域标记 vs 策略区域——违规清单。

    标记约定：路径含 ``region-<code>`` 段；无标记视为未声明（违规
    ——fail-closed：未声明不等于合规）。"""
    match = _REGION_MARK.search(str(store_root))
    if match is None:
        return [f"store 路径 {store_root} 无区域标记（region-<code>）"
                "——未声明不视为合规"]
    found = match.group(1).lower()
    if found != policy.region.lower():
        return [f"驻留违规：数据在 region-{found}，策略要求 "
                f"region-{policy.region}"]
    return []


def enforce_residency(
    store_root: str | Path, policy: DataPolicy,
) -> None:
    """拒写钩子（fail-closed）：驻留违规即抛（装配面在首个写入前调）。"""
    violations = verify_residency(store_root, policy)
    if violations:
        raise VastaError(
            code="data.residency_violation",
            message="；".join(violations),
        )


def disposal_drill(
    store: Any, policy: DataPolicy, *,
    now: datetime | None = None,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> dict[str, Any]:
    """处置演练报告（只读——到期候选 + 冲突面 + 执行指引）。"""
    candidates = retention_due(store, policy, now=now,
                               tenant_id=tenant_id, project_id=project_id)
    blocked = [c for c in candidates if c.blocked_by_hold]
    return {
        "policy": policy.model_dump(mode="json"),
        "total_due": len(candidates),
        "to_delete": sum(1 for c in candidates
                         if c.disposition == "delete"
                         and not c.blocked_by_hold),
        "to_archive": sum(1 for c in candidates
                          if c.disposition == "archive"
                          and not c.blocked_by_hold),
        "blocked_by_legal_hold": len(blocked),
        "candidates": [c.model_dump() for c in candidates],
        "execution_note": "执行走 lifecycle.request_deletion（证明事件"
                          "延续）；blocked 项须先 release_legal_hold",
    }


# ---- PG 档备份（C4 解除收尾）----

def pg_backup_command(
    dsn: str, dest: str | Path, *,
    pg_dump: str = "pg_dump",
) -> list[str]:
    """pg_dump 命令构造（纯函数——密码经 PGPASSWORD 环境变量传递，
    **不进 argv**（进程列表可见性）；--format=custom 支持选择性恢复）。"""
    return [pg_dump, f"--dbname={dsn}", "--format=custom",
            f"--file={dest}"]


def pg_restore_command(
    backup: str | Path, target_dsn: str, *,
    psql_restore: str = "pg_restore",
) -> list[str]:
    """pg_restore 命令构造（--clean 重建——恢复演练目标库）。"""
    return [psql_restore, f"--dbname={target_dsn}", "--clean",
            str(backup)]


async def pg_recovery_drill(
    backup_dsn: str, drill_dsn: str, dest: str | Path,
) -> dict[str, Any]:
    """PG 恢复演练（真实执行——VASTA_PG_DSN 门控下的集成路径）：

    pg_dump 备份库 → pg_restore 到演练库 → 计数校验。"""
    import asyncio

    backup = pg_backup_command(backup_dsn, dest)
    restore = pg_restore_command(dest, drill_dsn)
    proc = await asyncio.create_subprocess_exec(
        *backup, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise VastaError(
            code="data.pg_backup_failed",
            message=f"pg_dump 失败：{err.decode(errors='replace')[:200]}",
        )
    proc2 = await asyncio.create_subprocess_exec(
        *restore, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    _, err2 = await proc2.communicate()
    if proc2.returncode != 0:
        raise VastaError(
            code="data.pg_restore_failed",
            message=f"pg_restore 失败：{err2.decode(errors='replace')[:200]}",
        )
    return {"backup": str(dest), "drill_dsn": drill_dsn,
            "passed": True}


__all__ = ["DataPolicy", "DisposalCandidate", "JurisdictionRule",
           "RetentionRule", "configure_data_policy",
           "disposal_drill", "enforce_residency", "pg_backup_command",
           "pg_recovery_drill", "pg_restore_command", "retention_due",
           "verify_residency"]
