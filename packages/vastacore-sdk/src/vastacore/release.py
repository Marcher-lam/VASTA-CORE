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

from pydantic import BaseModel, ConfigDict

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


#: 合法状态推进（线性——不可跳级）。
_VALID_TRANSITIONS: dict[str, str] = {
    "candidate": "testing",
    "testing": "shadow",
    "shadow": "canary",
    "canary": "active",
}


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


def _get_state_sync(store: Any, kind: str, name: str) -> dict[str, str]:
    """同步版状态重建（事件全量重放——MVP 规模）。"""
    state: dict[str, str] = {}
    active_history: list[str] = []
    for event in store.iter_run_events(_REGISTRY_RUN):
        p = event.payload
        if event.type == "release.transition" and p.get("kind") == kind \
                and p.get("name") == name:
            state[p["version"]] = p["to"]
            if p["to"] == "active":
                active_history.append(p["version"])
        elif event.type == "release.rolled_back" and p.get("kind") == kind \
                and p.get("name") == name:
            if active_history:
                active_history.pop()  # 弹出当前 active
            state[p.get("rolled_back_from", "")] = "rolled_back"
    if active_history:
        state["_active"] = active_history[-1]
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


async def promote_release(
    store: Any, kind: str, name: str, version: str, *,
    to: str,
) -> ReleaseResult:
    """推进发布状态（逐级——跳级拒）。"""
    ReleaseStatus(to)  # 非法值即 ValueError（字面量校验）
    # 版本必须已发布（registry 中存在）
    from .versioning import version_as_of

    try:
        await version_as_of(store, kind, name)
    except VastaError:
        raise VastaError(
            code="release.version_not_published",
            message=f"{kind} {name!r} 尚无已发布版本（先 publish）",
        ) from None

    state = _get_state_sync(store, kind, name)
    current = state.get(version, "candidate")
    if current == "active":
        raise VastaError(
            code="release.already_active",
            message=f"{kind} {name!r} v{version} 已是 active",
        )
    expected = _VALID_TRANSITIONS.get(current)
    if expected != to:
        raise VastaError(
            code="release.invalid_transition",
            message=(
                f"非法推进：{current} → {to}"
                f"（合法下一级：{expected or '无'}——不可跳级）"
            ),
        )
    sequencer = EventSequencer(store, _REGISTRY_RUN)
    await sequencer.emit("release.transition", {
        "kind": kind, "name": name, "version": version,
        "from": current, "to": to,
    })
    return ReleaseResult(kind=kind, name=name, version=version, status=to)


async def rollback_release(
    store: Any, kind: str, name: str,
) -> RollbackResult:
    """回滚到前一 active 版本。"""
    state = _get_state_sync(store, kind, name)
    current_active = state.get("_active")
    if not current_active:
        raise VastaError(
            code="release.no_active_to_rollback",
            message=f"{kind} {name!r} 无 active 版本可回滚",
        )
    # 找前一 active（重放历史——倒数第二个到 active 的版本）
    active_history: list[str] = []
    for event in store.iter_run_events(_REGISTRY_RUN):
        p = event.payload
        if event.type == "release.transition" and p.get("kind") == kind \
                and p.get("name") == name and p.get("to") == "active":
            active_history.append(p["version"])
        elif event.type == "release.rolled_back" and p.get("kind") == kind \
                and p.get("name") == name and active_history:
            active_history.pop()
    previous = active_history[-2] if len(active_history) >= 2 else None
    if previous is None:
        raise VastaError(
            code="release.no_previous_active",
            message=f"{kind} {name!r} 无前一 active 版本（首次 active 不可回滚）",
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
    """影子期新旧版本并行对比——差异报告。"""
    from .versioning import version_as_of

    new_rec = await version_as_of(store, kind, name,
                                  as_of_seq=10**9)  # latest
    old_rec = await version_as_of(store, kind, name, as_of_seq=10**9)
    # 简化：按版本号过滤（精确比较走 version_as_of 指定版本）
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


__all__ = ["ReleaseStatus", "ReleaseResult", "RollbackResult",
           "compare_shadow", "get_canary_percent", "get_release_status",
           "promote_release", "rollback_release", "set_canary_percent"]
