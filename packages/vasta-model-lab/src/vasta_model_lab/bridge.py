"""WorldModel 失效桥接（Story 6.6，AD-13）——claim.refuted → suspended。"""

from __future__ import annotations

from typing import Any


class WorldModelBridge:
    """claim.refuted → world_model.suspended（唯一 owner）。

    AD-13：桥接只能由 vastacore-cognition 侧发起——本类作为其调用的
    桥接实现挂在 model-lab（事件落 claim.run_id 对应存储）。
    """

    def __init__(self, store: Any) -> None:  # SqliteStorage
        self.store = store

    async def on_claim_refuted(
        self, claim_id: str, *, model_names: list[str]
    ) -> list[str]:
        """认知侧反例到达 → 相关模型挂起（world_model.suspended 事件）。"""
        from ._bookkeeping_stub import emit_world_model_event  # 延迟防环

        suspended: list[str] = []
        for name in model_names:
            await emit_world_model_event(
                self.store,
                "world_model.suspended",
                {"name": name, "reason": f"依赖主张 {claim_id} 被推翻",
                 "bridge": "cognition", "propagated_from_claim": claim_id},
            )
            suspended.append(name)
        return suspended


