"""资产发布灰度与回滚（Story 9.6，FR-065，G3）。

状态机 candidate→testing→shadow→canary→active（+rolled_back）：
- `promote_release` 逐级推进（非法跳级拒），转换落 `release.transition`
  事件（registry 系统流——与 8.8 版本化同一条流）；
- `rollback_release` 恢复前一 active 版本 + 落 `release.rolled_back`；
- `compare_shadow` 新旧 bundle 并行对比差异报告；
- `set_canary_percent` 灰度比例可配（1-100）；
- 资产级状态（kind+name）：同一资产多版本并存，只有一个 active。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.sequencer import EventSequencer

_REGISTRY_RUN = "registry"


class ReleaseStatus(StrEnum):
    CANDIDATE = "candidate"
    TESTING = "testing"
    SHADOW = "shadow"
    CANARY = "canary"
    ACTIVE = "active"
    ROLLED_BACK = "rolled_back"
    SUSPENDED = "suspended"  # 挂起（漂移/事故——可恢复，Story 10.3）
    RETIRED = "retired"      # 退役（终态——新版本接替后下线）
    REVOKED = "revoked"      # 吊销（终态·不可逆——严重缺陷/安全问题）


#: 合法状态推进（多出边——灰度链线性不可跳级；运行期分支
#: active↔suspended / →retired；任何活跃态可 →revoked）。
_VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "candidate": frozenset({"testing", "revoked"}),
    "testing": frozenset({"shadow", "revoked"}),
    "shadow": frozenset({"canary", "revoked"}),
    "canary": frozenset({"active", "revoked"}),
    "active": frozenset({"suspended", "retired", "revoked"}),
    "suspended": frozenset({"active", "retired", "revoked"}),
    # 终态（rolled_back/retired/revoked）无出边——重放语义与状态机一致
}

#: 无出边终态（重放时活跃历史弹出条件）。
_TERMINAL = frozenset({"rolled_back", "retired", "revoked"})


class ReleaseResult(BaseModel):
    """发布操作结果。"""

    model_config = ConfigDict(extra="forbid")

    kind: str
    name: str
    version: str
    status: str


class RollbackResult(BaseModel):
    """回滚结果。"""

    model_config = ConfigDict(extra="forbid")

    kind: str
    name: str
    rolled_back_from: str
    rolled_back_to: str


def _replay(
    store: Any, kind: str, name: str,
) -> tuple[dict[str, str], list[str]]:
    """事件全量重放 → (按版本最新状态表, 去重活跃序)。

    评审修复 F4/M1/M3：放弃栈式 active_history（suspend→resume 同版本
    重复压栈、多次终态只弹一次——_active 可指向 revoked 版本且 rollback
    自回滚）。活跃序：版本进入 active 即入列（去重），离开 active
    （挂起/终态/回滚）即从任意位置移除。"""
    state: dict[str, str] = {}
    active_order: list[str] = []
    for event in store.iter_run_events(_REGISTRY_RUN):
        p = event.payload
        if event.type == "release.transition" and p.get("kind") == kind \
                and p.get("name") == name:
            version, to = p["version"], p["to"]
            state[version] = to
            if to == "active" and version not in active_order:
                active_order.append(version)
            elif to != "active" and version in active_order:
                active_order.remove(version)
        elif event.type == "release.rolled_back" and p.get("kind") == kind \
                and p.get("name") == name:
            rolled_from = p.get("rolled_back_from", "")
            if rolled_from in active_order:
                active_order.remove(rolled_from)
            state[rolled_from] = "rolled_back"
    return state, active_order


def _get_state_sync(store: Any, kind: str, name: str) -> dict[str, str]:
    """同步版状态重建（MVP 规模全量重放；``_active`` = 活跃序末位）。"""
    state, active_order = _replay(store, kind, name)
    if active_order:
        state["_active"] = active_order[-1]
    return state


async def get_release_status(store: Any, kind: str, name: str) -> str:
    """当前发布状态（active 版本的 status；无 active 则最新版本的 status）。"""
    state = _get_state_sync(store, kind, name)
    active = state.get("_active")
    if active:
        return state.get(active, "active")
    # 无 active——取最新版本的状态（或 candidate）
    versions = {k: v for k, v in state.items() if not k.startswith("_")}
    if versions:
        return list(versions.values())[-1]
    return "candidate"


async def _record_review(
    store: Any, *, action: str, detail: dict[str, Any], approver: str,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> str:
    """FR-055 人工复核门（9.5 批准流复用）：复核动作落 approvals 流，
    返回 approval_id。"""
    from .approvals import record_approval

    approval = await record_approval(
        store, tool=action, args=dict(detail), approver=approver,
        scope=f"{tenant_id}:{project_id}", ttl_s=3600,
        tenant_id=tenant_id, project_id=project_id,
    )
    return approval.approval_id


async def promote_release(
    store: Any, kind: str, name: str, version: str, *,
    to: str,
    approver: str | None = None,
) -> ReleaseResult:
    """推进发布状态（逐级——跳级拒）。

    FR-055 复核门（Story 10.3）：``to="active"``（上线）**强制
    approver**——先落批准（9.5 五要素）再迁移；其余推进免复核。"""
    ReleaseStatus(to)  # 非法值即 ValueError（字面量校验）
    # 版本必须已发布（registry 中存在**该版本**——幻影版本号拒）
    from .versioning import version_as_of

    try:
        await version_as_of(store, kind, name, version=version)
    except VastaError:
        raise VastaError(
            code="release.version_not_published",
            message=(f"{kind} {name!r} v{version} 尚未发布"
                     "（先 publish——幻影版本不可入状态机）"),
        ) from None

    state = _get_state_sync(store, kind, name)
    current = state.get(version, "candidate")
    if current == "active":
        raise VastaError(
            code="release.already_active",
            message=f"{kind} {name!r} v{version} 已是 active",
        )
    # 评审修复 F2：promote 只承载灰度链——suspended/retired/revoked
    # 是**专用函数**语义（挂起/退役/吊销各有 reason/approver/级联面），
    # 经 promote 传入即绕过复核门与级联（to="revoked" 曾零复核可吊销）
    if to in ("suspended", "retired", "revoked"):
        dedicated = {
            "suspended": "suspend_release", "retired": "retire_release",
            "revoked": "revoke_release"}[to]
        raise VastaError(
            code="release.invalid_transition",
            message=(f"{to} 是专用生命周期动作——请走 {dedicated}"
                     "（复核/级联语义在彼处）"),
        )
    allowed = _VALID_TRANSITIONS.get(current, frozenset())
    if to not in allowed:
        raise VastaError(
            code="release.invalid_transition",
            message=(
                f"非法推进：{current} → {to}"
                f"（合法下一级：{sorted(allowed) or '无'}——不可跳级）"
            ),
        )
    payload: dict[str, Any] = {
        "kind": kind, "name": name, "version": version,
        "from": current, "to": to,
    }
    if to == "active":
        if not approver:
            raise VastaError(
                code="release.review_required",
                message=(f"{kind} {name!r} v{version} 上线（canary→active）"
                         "须人工复核——approver 必填（FR-055）"),
            )
        payload["approval_id"] = await _record_review(
            store, action="release.promote_active",
            detail={"kind": kind, "name": name, "version": version},
            approver=approver)
    sequencer = EventSequencer(store, _REGISTRY_RUN)
    await sequencer.emit("release.transition", payload)
    return ReleaseResult(kind=kind, name=name, version=version, status=to)


class RevocationResult(BaseModel):
    """吊销结果（不可逆 + 级联失效清单）。"""

    model_config = ConfigDict(extra="forbid")

    kind: str
    name: str
    version: str
    approval_id: str
    invalidated_plans: list[str] = Field(default_factory=list)


async def suspend_release(
    store: Any, kind: str, name: str, version: str, *, reason: str,
) -> ReleaseResult:
    """挂起（active→suspended——漂移/事故临时下线；可 resume）。"""
    return await _lifecycle_step(store, kind, name, version,
                                 to="suspended", reason=reason)


async def _lifecycle_step(
    store: Any, kind: str, name: str, version: str, *,
    to: str, reason: str,
) -> ReleaseResult:
    """suspend/resume/retire 共用迁移步（复核免——非上线/吊销门）。

    评审修复 M1：resume（to=active）时若活跃序已有**其他**服务版本 →
    拒（双 current；promote 的灰度替换是设计内让位，resume 撞已服务
    版本是冲突——先挂起/退役当前再恢复）。"""
    from .versioning import version_as_of

    try:
        await version_as_of(store, kind, name, version=version)
    except VastaError:
        raise VastaError(
            code="release.version_not_published",
            message=f"{kind} {name!r} v{version} 尚未发布",
        ) from None
    state, active_order = _replay(store, kind, name)
    current = state.get(version, "candidate")
    allowed = _VALID_TRANSITIONS.get(current, frozenset())
    if to not in allowed:
        raise VastaError(
            code="release.invalid_transition",
            message=(f"非法迁移：{current} → {to}"
                     f"（合法：{sorted(allowed) or '无'}）"),
        )
    if to == "active" and any(v != version for v in active_order):
        raise VastaError(
            code="release.active_conflict",
            message=(f"{kind} {name!r} 活跃序已有服务版本 "
                     f"{[v for v in active_order if v != version]}"
                     "——先挂起/退役当前再 resume（防双 current）"),
        )
    sequencer = EventSequencer(store, _REGISTRY_RUN)
    await sequencer.emit("release.transition", {
        "kind": kind, "name": name, "version": version,
        "from": current, "to": to, "reason": reason,
    })
    return ReleaseResult(kind=kind, name=name, version=version, status=to)


async def retire_release(
    store: Any, kind: str, name: str, version: str, *, reason: str,
) -> ReleaseResult:
    """退役（active/suspended→retired——终态；新版本接替后下线）。"""
    return await _lifecycle_step(store, kind, name, version,
                                 to="retired", reason=reason)


async def resume_release(
    store: Any, kind: str, name: str, version: str, *, reason: str,
) -> ReleaseResult:
    """恢复（suspended→active——免复核：上线复核门已在首次
    canary→active 时通过，恢复不是新上线）。"""
    return await _lifecycle_step(store, kind, name, version,
                                 to="active", reason=reason)


async def revoke_release(
    store: Any, kind: str, name: str, version: str, *,
    reason: str, approver: str | None = None,
    plans_of_model: Any = None,
) -> RevocationResult:
    """吊销（任何活跃态→revoked——**终态不可逆**）。

    FR-055：吊销须人工复核（approver 必填——9.5 批准流先落）；
    级联失效（10.3 AC）：依赖该版本的活跃计划 → ``plan.invalidated``
    （``invalidated_by_release`` 可溯；plans_of_model 注入映射——
    与 9.14 refute 传播同构）。"""
    from .versioning import version_as_of

    try:
        await version_as_of(store, kind, name, version=version)
    except VastaError:
        raise VastaError(
            code="release.version_not_published",
            message=f"{kind} {name!r} v{version} 尚未发布",
        ) from None
    state = _get_state_sync(store, kind, name)
    current = state.get(version, "candidate")
    allowed = _VALID_TRANSITIONS.get(current, frozenset())
    if "revoked" not in allowed:
        raise VastaError(
            code="release.invalid_transition",
            message=(f"非法吊销：{current}（终态不可逆"
                     f"——合法吊销前态：{sorted(
                         s for s, outs in _VALID_TRANSITIONS.items()
                         if 'revoked' in outs)}）"),
        )
    if not approver:
        raise VastaError(
            code="release.review_required",
            message=(f"吊销 {kind} {name!r} v{version} 须人工复核"
                     "——approver 必填（FR-055，终态不可逆动作）"),
        )
    approval_id = await _record_review(
        store, action="release.revoke",
        detail={"kind": kind, "name": name, "version": version,
                "reason": reason},
        approver=approver)
    sequencer = EventSequencer(store, _REGISTRY_RUN)
    await sequencer.emit("release.transition", {
        "kind": kind, "name": name, "version": version,
        "from": current, "to": "revoked", "reason": reason,
        "approval_id": approval_id,
    })
    invalidated: list[str] = []
    if plans_of_model is not None:
        bridge_seq = EventSequencer(store, "cognition")
        for plan_id in plans_of_model(version):
            await bridge_seq.emit("plan.invalidated", {
                "plan_id": plan_id,
                "invalidated_by_release": f"{kind}:{name}:{version}",
                "bridge": "release", "reason": reason,
            })
            invalidated.append(plan_id)
    return RevocationResult(kind=kind, name=name, version=version,
                            approval_id=approval_id,
                            invalidated_plans=invalidated)


async def rollback_release(
    store: Any, kind: str, name: str,
) -> RollbackResult:
    """回滚到前一 active 版本。

    评审修复 F4/M2/M3：重放复用 _replay 的去重活跃序（原自带重放把
    resume 重复压栈——rollback 可自回滚到自身/以 revoked 为锚点抹掉
    吊销终态）；回滚目标须为**可服务**版本——终态（revoked/retired/
    rolled_back）与 suspended 版本拒。"""
    state, active_order = _replay(store, kind, name)
    current_active = active_order[-1] if active_order else None
    if not current_active:
        raise VastaError(
            code="release.no_active_to_rollback",
            message=f"{kind} {name!r} 无 active 版本可回滚",
        )
    previous = active_order[-2] if len(active_order) >= 2 else None
    if previous is None:
        raise VastaError(
            code="release.no_previous_active",
            message=f"{kind} {name!r} 无前一 active 版本（首次 active 不可回滚）",
        )
    if state.get(previous) in ("suspended", *_TERMINAL):
        raise VastaError(
            code="release.no_serviceable_target",
            message=(f"回滚目标 v{previous} 现为 {state.get(previous)}"
                     "（不可服务——挂起/终态版本不能承接流量）"),
        )
    sequencer = EventSequencer(store, _REGISTRY_RUN)
    await sequencer.emit("release.rolled_back", {
        "kind": kind, "name": name,
        "rolled_back_from": current_active,
        "rolled_back_to": previous,
    })
    return RollbackResult(kind=kind, name=name,
                          rolled_back_from=current_active,
                          rolled_back_to=previous)


async def compare_shadow(
    store: Any, kind: str, name: str, *,
    new_version: str, old_version: str,
) -> dict[str, Any]:
    """影子期新旧版本并行对比——差异报告（两版本各自取回 bundle）。"""
    from .versioning import version_as_of

    new_rec = await version_as_of(store, kind, name, version=new_version)
    old_rec = await version_as_of(store, kind, name, version=old_version)
    differences: list[dict[str, Any]] = []
    new_bundle = new_rec.bundle
    old_bundle = old_rec.bundle
    all_keys = set(list(new_bundle.keys()) + list(old_bundle.keys()))
    for key in sorted(all_keys):
        nv = new_bundle.get(key)
        ov = old_bundle.get(key)
        if nv != ov:
            differences.append({
                "field": key,
                "old": str(ov)[:100] if ov is not None else None,
                "new": str(nv)[:100] if nv is not None else None,
            })
    return {
        "kind": kind, "name": name,
        "old_version": old_version, "new_version": new_version,
        "differences": differences,
        "total_diffs": len(differences),
    }


async def set_canary_percent(
    store: Any, kind: str, name: str, percent: int,
) -> None:
    """灰度比例（1-100）。"""
    if not 1 <= percent <= 100:
        raise VastaError(
            code="release.bad_canary_percent",
            message=f"灰度比例须在 [1,100]，得到 {percent}",
        )
    # 存储在事件流（查询面走重放——MVP 简化：发一个 config 事件）
    sequencer = EventSequencer(store, _REGISTRY_RUN)
    await sequencer.emit("release.canary_config", {
        "kind": kind, "name": name, "percent": percent,
    })


async def get_canary_percent(store: Any, kind: str, name: str) -> int:
    """读取灰度比例（最新 config 事件；默认 100=全量）。"""
    for event in reversed(list(store.iter_run_events(_REGISTRY_RUN))):
        if event.type == "release.canary_config" \
                and event.payload.get("kind") == kind \
                and event.payload.get("name") == name:
            return int(event.payload["percent"])
    return 100


__all__ = ["ReleaseStatus", "ReleaseResult", "RevocationResult",
           "RollbackResult", "compare_shadow", "get_canary_percent",
           "get_release_status", "promote_release", "resume_release",
           "retire_release", "revoke_release", "rollback_release",
           "set_canary_percent", "suspend_release"]
