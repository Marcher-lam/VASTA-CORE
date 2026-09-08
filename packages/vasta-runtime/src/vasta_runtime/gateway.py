"""ToolGateway：写动作唯一通道与幂等键派生（FR-032，AD-4/AD-11，Story 3.2）。

- 注册表是业务工具适配器/凭证的唯一持有处（AD-4）——引擎与模型侧只见到网关；
- 分类强制：read_only/risk 一律取自清单；契约自报仅作 declared 记录；
- 幂等（AD-11）：键 = run_id:plan_step_id:tool:canonical_args_hash；
  命中返回原结果 + replayed=True，适配器零调用、预算零消耗；
- dry_run 门：清单声明 supports_dry_run 时先试运行，不允许则不触执行。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action, ToolAdapter, ToolResult


def canonical_args_hash(args: dict[str, Any]) -> str:
    """键序无关的参数规范化哈希（AD-11 幂等键组成）。"""
    canonical = json.dumps(
        args or {}, sort_keys=True, separators=(",", ":"), default=repr
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def idempotency_key(
    run_id: str, plan_step_id: str, tool: str, args: dict[str, Any]
) -> str:
    """AD-11 唯一确定函数：幂等键派生（禁止各单元自定）。"""
    return f"{run_id}:{plan_step_id}:{tool}:{canonical_args_hash(args)}"


class ToolNotRegisteredError(VastaError):
    def __init__(self, tool: str) -> None:
        super().__init__(
            code="tool.not_registered",
            message=f"工具 {tool!r} 未在网关注册（清单缺失，FR-032）",
            retryable=False,
        )
        self.tool = tool


class DuplicateToolError(VastaError):
    def __init__(self, name: str) -> None:
        super().__init__(
            code="tool.duplicate_registration",
            message=f"工具名 {name!r} 已注册（同名单工具拒绝重复注册）",
            retryable=False,
        )


class ToolGateway:
    """写动作唯一执行通道（AD-4）。

    引擎/模型侧不 import 适配器；一切工具调用经此。MVP 幂等缓存为内存态
    （Stage 3 随 FR-038 持久化）。
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolAdapter] = {}
        self._results: dict[str, ToolResult] = {}

    # ---- 注册 ----
    def register(self, adapter: ToolAdapter) -> None:
        """注册工具适配器；清单经 ToolManifest（pydantic）即已强制完整。"""
        manifest = adapter.manifest  # 缺字段在清单构造期即抛（FR-032）
        if manifest.name in self._tools:
            raise DuplicateToolError(manifest.name)
        self._tools[manifest.name] = adapter

    def registered_tools(self) -> list[str]:
        return sorted(self._tools)

    # ---- 分类（AD-4：清单强制，调用方自声明无效）----
    def classify(self, tool: str) -> tuple[bool, str]:
        """返回 (read_only, risk)，全部取自清单；未注册即拒。"""
        adapter = self._tools.get(tool)
        if adapter is None:
            raise ToolNotRegisteredError(tool)
        return adapter.manifest.read_only, adapter.manifest.risk

    # ---- 幂等（AD-11）----
    def is_replay(self, run_id: str, plan_step_id: str, action: Action) -> bool:
        """该请求是否为幂等命中（预算闸对其放行，AD-11）。"""
        key = idempotency_key(run_id, plan_step_id, action.tool, action.args)
        return key in self._results

    # ---- 执行 ----
    async def execute(
        self,
        *,
        run_id: str,
        plan_step_id: str,
        action: Action,
    ) -> ToolResult:
        """经网关执行工具：幂等短路 → dry_run 门 → 适配器执行 → 缓存。"""
        adapter = self._tools.get(action.tool)
        if adapter is None:
            raise ToolNotRegisteredError(action.tool)
        key = idempotency_key(run_id, plan_step_id, action.tool, action.args)
        cached = self._results.get(key)
        if cached is not None:
            return cached.model_copy(update={"replayed": True})  # 绝不静默重执行
        if adapter.manifest.supports_dry_run:
            dry = await adapter.dry_run(action)
            if not dry.allowed:
                result = ToolResult(
                    ok=False, detail={"phase": "dry_run", "reason": dry.reason}
                )
                self._results[key] = result
                return result
        result = await adapter.execute(action, idempotency_key=key)
        self._results[key] = result
        return result
