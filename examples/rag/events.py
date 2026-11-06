"""事件留痕助手：为 RAG 原型分配不冲突的 run_id 并构造 EventSequencer。

事件类型全部复用现有目录（run.created / artifact.registered /
observation.external / run.completed），不开新族、不触守卫测试。
"""

from __future__ import annotations

from typing import Any

from vasta_protocols import EventSequencer

from .config import RagConfig


def new_sequencer(store: Any, base_run_id: str, cfg: RagConfig) -> EventSequencer:
    """(run_id, seq) 唯一约束下找空闲 run_id：同基名重跑自动加 -2/-3 后缀。"""
    n = 1
    while True:
        run_id = base_run_id if n == 1 else f"{base_run_id}-{n}"
        if store.last_event_info(run_id) is None:
            return EventSequencer(store, run_id,
                                  tenant_id=cfg.tenant_id, project_id=cfg.project_id)
        n += 1
