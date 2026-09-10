"""Tool Proxy：既有工具零重写接入六段链（Story 8.11，蓝图 §31 Stage 2，G1）。

把团队已有的工具函数（Playwright 浏览器调用为动机场景——不引入浏览器依赖）
包装为 ToolAdapter：清单强制分类（FR-032）、适配器级幂等缓存（AD-11）、
单次调用超时（wait_for）、异常按协议路径落 adapter_error；经
AgentSession.act() / 网关执行即六段链——原始响应入 CAS（FR-010）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from vasta_protocols.protocols import (
    Action,
    DryRunResult,
    Observation,
    ToolManifest,
    ToolResult,
)


class ProxyToolAdapter:
    """既有 async 函数的代理适配器（签名正确 + 幂等缓存 + 超时）。"""

    protocol_version = "0.1.0"

    def __init__(
        self,
        name: str,
        fn: Callable[..., Awaitable[Any]],
        *,
        risk: str,
        read_only: bool,
        idempotent: bool,
        timeout_ms: int = 5000,
        version: str = "1.0",
    ) -> None:
        self.manifest = ToolManifest(
            name=name, version=version, risk=risk,  # type: ignore[arg-type]
            read_only=read_only, idempotent=idempotent,
        )
        self._fn = fn
        self._timeout_s = timeout_ms / 1000
        self._results: dict[str, ToolResult] = {}  # 幂等缓存（协议要求）
        self.calls = 0  # 底层函数执行计数（测试/审计用）

    async def execute(self, action: Action, idempotency_key=None) -> ToolResult:
        if idempotency_key in self._results:
            return self._results[idempotency_key].model_copy(
                update={"replayed": True}
            )
        detail = await asyncio.wait_for(
            self._fn(**action.args), timeout=self._timeout_s
        )
        self.calls += 1
        result = ToolResult(
            ok=True,
            detail=dict(detail) if isinstance(detail, dict)
            else {"value": detail},
        )
        self._results[idempotency_key] = result
        return result

    async def dry_run(self, action: Action) -> DryRunResult:
        return DryRunResult(allowed=True)  # 参数形状由网关/契约层把关

    async def read_back(self, action: Action, result: ToolResult) -> Observation:
        return Observation(kind="decision", detail=dict(result.detail))

    async def compensate(self, action: Action, result: ToolResult) -> ToolResult:
        return ToolResult(ok=True, detail={"compensated": True,
                                           "note": "proxy 工具占位补偿"})


def proxy_tool(
    name: str,
    fn: Callable[..., Awaitable[Any]],
    *,
    risk: str,
    read_only: bool,
    idempotent: bool,
    timeout_ms: int = 5000,
    version: str = "1.0",
) -> ProxyToolAdapter:
    """通用既有工具代理（Playwright 接入示例：
    ``proxy_tool("browser_click", page.click, risk="R2", ...)``）。"""
    return ProxyToolAdapter(
        name, fn, risk=risk, read_only=read_only, idempotent=idempotent,
        timeout_ms=timeout_ms, version=version,
    )


def browser_action_proxy(
    action_name: str,
    fn: Callable[..., Awaitable[Any]],
    *,
    timeout_ms: int = 5000,
) -> ProxyToolAdapter:
    """浏览器写操作预设：R2 / 非只读 / **非幂等**（双击有副作用）。"""
    return ProxyToolAdapter(
        f"browser_{action_name}", fn,
        risk="R2", read_only=False, idempotent=False,
        timeout_ms=timeout_ms,
    )


def browser_read_proxy(
    read_name: str,
    fn: Callable[..., Awaitable[Any]],
    *,
    timeout_ms: int = 5000,
) -> ProxyToolAdapter:
    """浏览器读操作预设：R1 / 只读 / 幂等（get_text、screenshot 等）。"""
    return ProxyToolAdapter(
        f"browser_{read_name}", fn,
        risk="R1", read_only=True, idempotent=True,
        timeout_ms=timeout_ms,
    )


__all__ = ["ProxyToolAdapter", "browser_action_proxy", "browser_read_proxy",
           "proxy_tool"]
