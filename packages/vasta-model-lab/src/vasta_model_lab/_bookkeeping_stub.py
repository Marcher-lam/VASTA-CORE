"""模型实验室供给点：安全墙钟（AD-15）与 world_model.* 事件发射。

沙箱子进程环境构造也在此（AD-16 例外：环境读取属基础设施供给，
非行为熵——与安全墙钟同类的供给点）。"""

from __future__ import annotations

import os
import sys
from typing import Any

from vasta_protocols.envelope import EventEnvelope
from vasta_protocols.sequencer import EventSequencer


def default_monotonic() -> float:
    """安全墙钟供给点（规划超时上限属 AD-15 强制机制）。"""
    import time

    return time.monotonic()


def sandbox_subprocess_env() -> dict[str, str]:
    """沙箱子进程最小环境（评审修复：清除父进程凭证可达的变量）。

    Windows 上 CPython 运行时依赖 SYSTEMROOT，仅透传这一项。"""
    env = {"PYTHONIOENCODING": "utf-8", "PYTHONHASHSEED": "0"}
    if sys.platform == "win32":
        systemroot = os.environ.get("SYSTEMROOT")
        if systemroot:
            env["SYSTEMROOT"] = systemroot
    return env


async def emit_world_model_event(
    store: Any, type_: str, payload: dict[str, Any], *,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> EventEnvelope:
    """以 cognition run 落 world_model.* 事件（因果链续接）。

    统一序列器（Story 9.1）：系统流模式——与 CognitionService 并发写
    安全。tenant/project 可透传（评审修复 TRC-1——此前固定默认作用
    域，多租户留痕落错租户流）；缺省保持向后兼容。"""
    sequencer = EventSequencer(store, "cognition", tenant_id=tenant_id,
                               project_id=project_id)
    return await sequencer.emit(type_, payload)
