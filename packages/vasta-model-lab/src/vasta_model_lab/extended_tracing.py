"""扩展模型事件留痕（Story 12.3，11.9 拆分裁决接线腿，G0）。

四类扩展模型（概率/因果/约束/组合——进程内纯计算）的模型类型与
生命周期经既有 ``emit_world_model_event`` 面入事件留痕：

- ``register_extended_model`` → ``world_model.registered``（模型类型
  + 名称入册）；
- ``validate_extended_model`` → ``world_model.validated``（各类模型
  的自然校验：约束可行域/因果依赖闭包/概率归一/组合规则形态——
  passed + 细节）；
- ``trace_extended_model_use`` → ``world_model.used``（使用相位留痕
  ——调用方声明 phase）。

11.9 的沙箱执行接线与静态检查扩展仍为后续接线（Stage 6 启动裁决
改口——见 docs/epics.md Story 11.9 AC）。事件经 cognition 系统流
落盘（与 model-lab 既有 world_model.* 事件同流——因果链续接）。
"""

from __future__ import annotations

from typing import Any

from vasta_protocols.errors import VastaError

from .extended_models import (
    CausalModel,
    CompositeModel,
    ConstraintModel,
    ProbabilisticWorldModel,
)

_KIND_BY_TYPE: dict[type, str] = {
    ProbabilisticWorldModel: "probabilistic",
    CausalModel: "causal",
    ConstraintModel: "constraint",
    CompositeModel: "composite",
}


def model_kind_of(model: Any) -> str:
    """模型实例 → 类型名（四类扩展模型）。"""
    for cls, kind in _KIND_BY_TYPE.items():
        if isinstance(model, cls):
            return kind
    raise VastaError(
        code="model_lab.unknown_model_kind",
        message=(f"未知扩展模型类型 {type(model).__name__!r}"
                 f"（支持：{sorted(set(_KIND_BY_TYPE.values()))}）"),
    )


async def register_extended_model(
    store: Any, model: Any, *, name: str,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> None:
    """模型入册留痕（world_model.registered——模型类型可溯）。"""
    from ._bookkeeping_stub import emit_world_model_event

    await emit_world_model_event(store, "world_model.registered", {
        "kind": model_kind_of(model), "name": name,
    }, tenant_id=tenant_id, project_id=project_id)


def _validate_model(model: Any) -> tuple[bool, dict[str, Any]]:
    """各类模型的自然校验 → (passed, 细节)。"""
    if isinstance(model, ConstraintModel):
        return True, {"constraints": len(model.constraints)}
    if isinstance(model, CausalModel):
        # 依赖闭包：环检出（拓扑不可解即环）
        resolved: set[str] = set()
        pending = set(model.dependencies) | set(model.mechanisms)
        while pending:
            progressed = False
            for var in sorted(pending):
                parents = model.dependencies.get(var, [])
                if all(p in resolved or p not in model.dependencies
                       for p in parents):
                    resolved.add(var)
                    pending.discard(var)
                    progressed = True
            if not progressed:
                break
        cycles = sorted(pending)
        return not cycles, {"unresolved": cycles}
    if isinstance(model, ProbabilisticWorldModel):
        for state, dist in model.transitions.items():
            for target, prob in dist.items():
                if not 0.0 <= prob <= 1.0:
                    return False, {"state": state, "target": target,
                                   "prob": prob}
            total = sum(dist.values())
            if abs(total - 1.0) > 0.01:
                return False, {"state": state, "total": total}
        return True, {"states": len(model.transitions)}
    # CompositeModel：组件规则形态（set/add 均为 dict）
    for i, rules in enumerate(model.component_rules):
        for key in ("set", "add"):
            if not isinstance(rules.get(key, {}), dict):
                return False, {"component": i, "bad": key}
    return True, {"components": len(model.component_rules)}


async def validate_extended_model(
    store: Any, model: Any, *, name: str,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> bool:
    """模型校验留痕（world_model.validated——passed + 细节）。"""
    from ._bookkeeping_stub import emit_world_model_event

    passed, detail = _validate_model(model)
    await emit_world_model_event(store, "world_model.validated", {
        "kind": model_kind_of(model), "name": name,
        "passed": passed, "detail": detail,
    }, tenant_id=tenant_id, project_id=project_id)
    return passed


async def trace_extended_model_use(
    store: Any, model: Any, *, name: str, phase: str,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> None:
    """模型使用相位留痕（world_model.used——phase 由调用方声明：
    sampled/intervened/checked/composed 等）。"""
    from ._bookkeeping_stub import emit_world_model_event

    if not phase:
        raise VastaError(
            code="model_lab.bad_phase",
            message="使用相位 phase 不可为空（sampled/intervened/…）",
        )
    await emit_world_model_event(store, "world_model.used", {
        "kind": model_kind_of(model), "name": name, "phase": phase,
    }, tenant_id=tenant_id, project_id=project_id)


__all__ = ["model_kind_of", "register_extended_model",
           "trace_extended_model_use", "validate_extended_model"]
