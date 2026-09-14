"""分布式追踪上下文（NFR-010——OTel 兼容的最小工程内接线）。

架构脊柱约定「OTel trace_id 贯穿 Event 与日志」——本模块提供无
opentelemetry 依赖的最小实现（contextvar 传播 + 事件自动注入）：

- ``trace_span(trace_id)``：上下文管理器——作用域内 EventSequencer
  发射的事件自动携带 ``envelope.trace_id``；
- ``current_trace_id()``：当前上下文 trace_id（无 span → None）；
- ``bind_trace_id(getter)``：绑定外部 provider（如 OTel span 上下文
  的 ``get_current_span().get_span_context().trace_id``——生产接
  OTel 时替换默认 contextvar 源，接口不变）。
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

_trace_id: contextvars.ContextVar[str | None] = \
    contextvars.ContextVar("vasta_trace_id", default=None)

#: 外部 provider 绑定点（缺省读 contextvar；OTel 接入时替换）。
_trace_provider = None


@contextmanager
def trace_span(trace_id: str) -> Iterator[None]:
    """作用域内事件自动携带 trace_id（嵌套时内层覆盖、退出恢复）。"""
    token = _trace_id.set(trace_id)
    try:
        yield
    finally:
        _trace_id.reset(token)


def bind_trace_id(getter) -> None:
    """绑定外部 trace provider（无参 callable → str|None）。"""
    global _trace_provider
    _trace_provider = getter


def current_trace_id() -> str | None:
    if _trace_provider is not None:
        return _trace_provider()
    return _trace_id.get()


__all__ = ["bind_trace_id", "current_trace_id", "trace_span"]
