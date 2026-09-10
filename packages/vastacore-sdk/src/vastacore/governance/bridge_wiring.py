"""cognition→lab 桥接自动接线（Story 9.14，AD-13，G6——W-4 解除）。

refute 后自动传播（既有手动桥接的自动化收口）：

1. ``cognition.refute``（含既有级联失效——下游主张随依赖图推翻）；
2. 每条被推翻主张 → 依赖它的世界模型挂起（``world_model.suspended``
   ——经 model-lab WorldModelBridge，AD-13「桥接由 cognition 侧发起」
   的 sdk 组合驱动形态）；
3. 挂起模型关联的活跃计划 → ``plan.invalidated``（治理桥接流留痕，
   payload 携 claim/模型来源——W-4 解除条件「refute→plan.invalidated
   链路 + 测试」）。

模型/计划映射经 provider 注入（调用方从其模型注册表/计划编排提供
——映射是业务数据，桥接只负责链路语义）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.sequencer import EventSequencer

#: claim_id → 依赖该主张的模型名清单
ModelNamesOf = Callable[[str], list[str]]
#: 模型名 → 关联的活跃计划 ID 清单
PlansOfModel = Callable[[str], list[str]]


class PropagationReport(BaseModel):
    """refute 自动传播报告（三跳全留痕）。"""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    cascaded: list[str] = Field(default_factory=list,
                                description="级联推翻的下游主张")
    suspended_models: list[str] = Field(default_factory=list)
    invalidated_plans: list[str] = Field(default_factory=list)


async def refute_with_propagation(
    store: Any, cognition: Any, claim_id: str, *,
    counterevidence: list[str],
    model_names_of: ModelNamesOf,
    plans_of_model: PlansOfModel | None = None,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> PropagationReport:
    """refute → world_model.suspended → plan.invalidated 一体化链路。

    桥接落 "cognition" 流（与 world_model 桥接事件同流——AD-13 并发
    安全由 Sequencer 系统流模式承担）。"""
    from vasta_model_lab.bridge import WorldModelBridge

    cascaded = await cognition.refute(claim_id, counterevidence)
    bridge = WorldModelBridge(store)
    sequencer = EventSequencer(
        store, "cognition", tenant_id=tenant_id, project_id=project_id)
    suspended: list[str] = []
    invalidated: list[str] = []
    seen_models: set[str] = set()  # 评审修复 F18：共享模型只挂起一次
    for cid in [claim_id, *cascaded]:
        models = [m for m in model_names_of(cid) if m not in seen_models]
        if not models:
            continue
        seen_models.update(models)
        suspended.extend(
            await bridge.on_claim_refuted(cid, model_names=models))
        if plans_of_model is None:
            continue
        for model in models:
            for plan_id in plans_of_model(model):
                await sequencer.emit("plan.invalidated", {
                    "plan_id": plan_id,
                    "suspended_model": model,
                    "invalidated_by_claim": cid,
                    "bridge": "cognition",
                })
                invalidated.append(plan_id)
    return PropagationReport(
        claim_id=claim_id, cascaded=cascaded,
        suspended_models=suspended, invalidated_plans=invalidated)


__all__ = ["PropagationReport", "refute_with_propagation"]
