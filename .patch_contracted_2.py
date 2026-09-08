import re

p = "packages/vasta-runtime/src/vasta_runtime/contracted.py"
s = open(p, encoding="utf-8").read()

# 3) 在 ContractedMixin 尾部（__all__ 之前）加 _execute_via_gateway
old = "__all__ = [\"ContractedMixin\", \"PolicyDeniedError\", \"PolicyOutcome\"]"
new = '''    async def _execute_via_gateway(  # noqa: SLF001（同包 mixin 访问引擎设施）
        self,
        contract: ActionContract,
        action: Action,
        *,
        plan_step_id: str,
        risk_effective: str | None,
        read_only: bool | None,
    ) -> list[Observation]:
        """网关执行路径（AD-4/11，Story 3.2）。

        - ToolResult 原始响应先落 CAS（FR-010）再入事件；
        - replay 命中不计预算（重复请求非新动作）；
        - after 段为合成 observation.external（引用 result_sha，带 last_action）。
        """
        try:
            result = await self.tool_gateway.execute(
                run_id=self.config.run_id,
                plan_step_id=plan_step_id,
                action=action,
            )
        except Exception as exc:
            await self._emit(
                "action.failed",
                {"tool": contract.tool, "phase": "execution",
                 "error": f"{type(exc).__name__}: {exc}"},
            )
            await self.fail(f"tool_error:{type(exc).__name__}")
            raise
        result_sha = await self.store.save_artifact(
            result.model_dump_json().encode("utf-8"),
            mime="application/json",
            source="tool.response",
            tenant_id=self.config.tenant_id,
            project_id=self.config.project_id,
        )
        if not result.replayed:  # 首次执行才计预算（AD-11）
            self.tracker.record_action()
        self._last_action = action
        await self._emit(
            "action.executed",
            {
                "tool": contract.tool,
                "ok": result.ok,
                "replayed": result.replayed,
                "risk_declared": contract.risk,
                "risk_effective": risk_effective,  # AD-4：清单强制
                "read_only": read_only,
                "result_ref": result_sha,
            },
        )
        after_obs = Observation(
            kind="external",
            artifact_refs=[result_sha],
            detail={
                "source": "tool",
                "tool": contract.tool,
                "ok": result.ok,
                "replayed": result.replayed,
            },
        )
        await self._record_observation(after_obs, action=action)
        return [after_obs]


__all__ = ["ContractedMixin", "PolicyDeniedError", "PolicyOutcome"]'''
assert old in s
s = s.replace(old, new)

# 4) 导入 ToolNotRegisteredError
old = "from .supervisor import SupervisorEscalationError"
new = "from .gateway import ToolNotRegisteredError\nfrom .supervisor import SupervisorEscalationError"
assert old in s
s = s.replace(old, new)

open(p, "w", encoding="utf-8", newline="\n").write(s)
print("contracted patched phase 2")
