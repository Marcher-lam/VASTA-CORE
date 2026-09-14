"""开放核心事件 Schema 与迁移策略（Story 10.7，FR-085，G2）。

下游消费者与企业集成有稳定契约：

- **JSON Schema 导出**（envelope_json_schema）：EventEnvelope 的
  JSON Schema（pydantic 生成 + event type 的 13 族封闭集 pattern
  注入——族约束对消费者机器可读）；
- **事件类型目录**（EVENT_CATALOG/register_event_type）：按实现源码
  收集的已知事件类型（族 → 事件清单；动态注册供扩展面）；
- **系统流清单**（SYSTEM_STREAMS）：治理/审计面的已知 run 命名；
- **版本迁移器**（migrate_envelope/MIGRATIONS）：事件可读升级——
  注册表按 (from, to) 逐跳链式迁移；同版本 no-op 恒等；未知版本
  fail-closed 拒；
- **破坏性变更检测**（detect_breaking_changes）：两版 Schema 对比
  ——必填新增/字段删除/类型变更为破坏（schema 演进守门）；
- **混版本检测**（validate_stream_versions）：同 run 内信封
  schema_version 混杂清单（事件流一致性——调用方决定升级或拒）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .envelope import ENVELOPE_SCHEMA_VERSION, EVENT_FAMILIES, EventEnvelope

#: 当前信封 Schema 版本（迁移目标默认值）。
CURRENT_VERSION = ENVELOPE_SCHEMA_VERSION

#: 已知系统流（治理/审计面 run 命名）。Story 12.1 起由
#: stream_catalog_gen 从代码发射点生成并对拍（零漂移守卫
#: tests/test_stream_catalog_guard.py）；import/bridge 为 10.7 手
#: 收集的保留声明（无字面量发射面——见 _DECLARED_SUPPLEMENT）。
SYSTEM_STREAMS: tuple[str, ...] = (
    "access", "agent-roles", "approvals", "autonomy", "billing",
    "bridge", "cognition", "delegations", "edge-stream", "environment",
    "evaluation", "import", "incidents", "lifecycle", "memory",
    "quotas", "registry", "risk-budgets", "schedules", "sharing",
)

# ---- 事件类型目录（按实现源码收集；动态注册供扩展） ----

_EVENT_CATALOG: dict[str, set[str]] = {
    "action": {
        "approval_record", "approval_requested", "approval_revoked",
        "approved", "batch_aborted", "batch_settled",
        "batch_step_compensated", "batch_step_compensation_failed",
        "batch_step_executed", "batch_step_failed", "contracted",
        "executed", "failed", "policy_cleared", "policy_denied",
        "recovered", "takeover_required",
    },
    "artifact": {
        "access_denied", "corrupted", "deletion_proved", "locked",
        "not_found", "published", "registered", "retention_configured",
        "shared", "shared_revoked",
    },
    "claim": {
        "accepted", "annotated", "confidence_decayed",
        "conflict_detected", "conflict_resolved", "disputed", "narrowed",
        "published_knowledge", "published_knowledge_revoked",
        "shared", "shared_revoked",
        "promoted", "proposed", "refuted", "retired", "revalidated",
        "revised", "supported",
    },
    "episode": set(),  # 族在封闭集内、当前无事件（保留声明）
    "evaluation": {
        "env_upgraded", "leaderboard_generated",
        "model_drift_measured",
        "real_seed_ci", "model_revalidated",
        "tournament_settled", "tournament_started",
        "audit_exported",
    },
    "incident": {"declared", "opened", "resolved"},
    "memory": {"note"},
    "observation": {"decision", "external", "reset", "stream_frame", "terminal",
                    "transition"},
    "plan": {
        "fired", "fire_failed", "invalidated", "scheduled",
    },
    "release": {
        "canary_config", "rolled_back", "transition",
    },
    "run": {
        "access_denied", "adopted", "bill_generated", "cancelled",
        "completed", "control_released", "cost_recorded", "created",
        "delegation_completed", "delegation_created",
        "deviation_context", "failed", "gap_detected",
        "agent_role_set", "autonomy_adjusted", "identity_asserted",
        "paused",
        "quota_configured", "resumed", "risk_budget_configured",
        "risk_budget_enforced", "risk_exposure_recorded",
        "role_assigned", "role_revoked",
        "role_violation",
        "scim_synced", "secret_ref_configured", "started",
        "takeover", "throttled",
    },
    "verification": {"deviated", "passed"},
    "world_model": {"meta_decision", "published", "registered",
                    "suspended", "updated", "used", "validated"},
}


def register_event_type(event_type: str) -> None:
    """动态注册事件类型（扩展面——13 族校验强制，族外拒）。"""
    if "." not in event_type:
        raise ValueError(
            f"event_type 须为点分形态（族.事件）：{event_type!r}")
    family = event_type.split(".", 1)[0]
    if family not in EVENT_FAMILIES:
        raise ValueError(
            f"event family {family!r} is outside the closed set of 13 "
            "families（目录只收族内事件）")
    _EVENT_CATALOG.setdefault(family, set()).add(
        event_type.split(".", 1)[1])


def event_catalog() -> dict[str, list[str]]:
    """事件类型目录快照（族 → 排序事件清单；全 13 族键恒在）。"""
    return {
        family: sorted(_EVENT_CATALOG.get(family, set()))
        for family in sorted(EVENT_FAMILIES)
    }


def envelope_json_schema() -> dict[str, Any]:
    """EventEnvelope 的 JSON Schema（含 13 族封闭集 pattern——族
    约束对消费者机器可读）。"""
    schema = EventEnvelope.model_json_schema()
    families = "|".join(sorted(EVENT_FAMILIES))
    # 族是**首 token**（对齐 envelope._validate_event_type 的运行时语义
    # ——评审修复 F1：原 pattern 把族锚在中段/末段，72/72 目录合法事件
    # 全部被拒、倒置形态（foo.run.bar）反而被收）
    pattern = rf"^({families})(\.[a-z][a-z0-9_]*)+$"
    props = schema.setdefault("properties", {})
    if "type" in props and isinstance(props["type"], dict):
        props["type"] = {
            **props["type"],
            "description": "past-tense 点分事件类型——族必须在 13 族"
                           "封闭集内（AD-5）",
            "pattern": pattern,
        }
    schema["$id"] = "vasta://schemas/event-envelope"
    schema["title"] = "VastaCore Event Envelope (open schema)"
    return schema


# ---- 版本迁移器 ----

#: 迁移注册表：(from, to) → transformer(dict 事件) → dict。
#: 当前 0.1.0 为首个版本——无历史迁移；机制就绪（注册即生效，
#: 多跳按链逐跳执行）。
MIGRATIONS: dict[tuple[str, str], Callable[[dict[str, Any]],
                                           dict[str, Any]]] = {}


def _version_chain(start: str, target: str) -> list[tuple[str, str]]:
    """BFS 求 from→to 的迁移跳链（无链则 ValueError）。"""
    from collections import deque

    frontier = deque([(start, [])])
    seen = {start}
    while frontier:
        current, path = frontier.popleft()
        if current == target:
            return path
        for (f, t) in MIGRATIONS:
            if f == current and t not in seen:
                seen.add(t)
                frontier.append((t, [*path, (f, t)]))
    raise ValueError(
        f"无迁移链：{start} → {target}"
        f"（已注册跳：{sorted(MIGRATIONS)}）")


def migrate_envelope(
    event: dict[str, Any], *, to_version: str = CURRENT_VERSION,
) -> dict[str, Any]:
    """事件可读升级：旧版事件 dict → 目标版本（逐跳链式；
    同版本 no-op 恒等返回；未知起点/无链 fail-closed 拒）。"""
    raw = event.get("schema_version")
    version = "" if raw is None else str(raw).strip()
    if not version:
        raise ValueError("事件缺 schema_version（不可迁移——元数据不全）")
    if version == to_version:
        return dict(event)  # 恒等（不原地改）
    current = dict(event)
    for _, (f, t) in enumerate(_version_chain(version, to_version)):
        current = MIGRATIONS[(f, t)](current)
        current["schema_version"] = t
    return current


# ---- 破坏性变更检测 ----

def detect_breaking_changes(
    old_schema: dict[str, Any], new_schema: dict[str, Any],
) -> list[str]:
    """两版 JSON Schema 对比——必填新增 / 字段删除 / 类型变更
    （破坏性；新增可选字段与描述变化不报）。"""
    breaking: list[str] = []
    old_props = old_schema.get("properties", {})
    new_props = new_schema.get("properties", {})
    old_required = set(old_schema.get("required", []))
    new_required = set(new_schema.get("required", []))
    for field in sorted(new_required - old_required):
        breaking.append(f"required-added:{field}")
    for field in sorted(set(old_props) - set(new_props)):
        breaking.append(f"field-removed:{field}")
    for field in sorted(set(old_props) & set(new_props)):
        old_field = old_props[field] if isinstance(old_props[field], dict) \
            else {}
        new_field = new_props[field] if isinstance(new_props[field], dict) \
            else {}
        old_type = old_field.get("type")
        new_type = new_field.get("type")
        if old_type and new_type and old_type != new_type:
            breaking.append(f"type-changed:{field}:{old_type}->{new_type}")
    return breaking


def validate_stream_versions(
    events: list[Any],
) -> list[str]:
    """同 run（或任一事件集）内信封 schema_version 混杂检测。

    返回混版本清单（去重排序）；单一版本（含空集）→ 空清单。"""
    versions: set[str] = set()
    for event in events:
        version = getattr(event, "schema_version", None)
        if version:
            versions.add(str(version))
    return sorted(versions) if len(versions) > 1 else []


__all__ = ["CURRENT_VERSION", "EVENT_FAMILIES", "MIGRATIONS",
           "SYSTEM_STREAMS", "detect_breaking_changes", "envelope_json_schema",
           "event_catalog", "migrate_envelope", "register_event_type",
           "validate_stream_versions"]
