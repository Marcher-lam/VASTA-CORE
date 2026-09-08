import re

p = "packages/vasta-runtime/src/vasta_runtime/contracted.py"
s = open(p, encoding="utf-8").read()

# 1) execute_contracted 签名加 plan_step_id
old = """    async def execute_contracted(
        self,
        contract: ActionContract,
        *,
        policy_check: PolicyCheck | None = None,
        verifiers: Mapping[str, Verifier] | None = None,
    ) -> list[Observation]:"""
new = """    async def execute_contracted(
        self,
        contract: ActionContract,
        *,
        policy_check: PolicyCheck | None = None,
        verifiers: Mapping[str, Verifier] | None = None,
        plan_step_id: str = "default",
    ) -> list[Observation]:"""
assert old in s
s = s.replace(old, new)

# 2) 守卫段之前插入网关注册检查；执行段替换为网关/env 双路径
old = """        # ── 守卫与预算（与 step 同语义）──
        try:
            self.collector.ensure_actable()  # noqa: SLF001
        except TerminalObservationError as exc:
            raise VastaError(code="run.terminal", message=str(exc)) from exc
        escalation = self.supervisor.check_loop(self._last_signature, action)  # noqa: SLF001
        if escalation is not None:
            await self._escalate(escalation)  # noqa: SLF001
        try:
            self.tracker.check()  # noqa: SLF001
        except BudgetExceededError as exc:
            await self._safe_stop(reason=exc.kind.value, safe_stop=True)  # noqa: SLF001
            raise

        # ── 执行段 ──
        try:
            observations = await self.env.execute(action)  # noqa: SLF001
        except Exception as exc:
            await self._emit(  # noqa: SLF001
                "action.failed",
                {"tool": contract.tool, "phase": "execution",
                 "error": f"{type(exc).__name__}: {exc}"},
            )
            await self.fail(f"env_error:{type(exc).__name__}")  # noqa: SLF001
            raise
        self.tracker.record_action()  # noqa: SLF001
        self._last_action = action  # noqa: SLF001
        await self._emit(  # noqa: SLF001
            "action.executed",
            {"tool": contract.tool, "ok": True},
        )"""
new = """        # ── 工具注册检查（FR-032：未声明清单的工具不得被写动作调用）──
        risk_effective: str | None = None
        read_only: bool | None = None
        if self.tool_gateway is not None:  # noqa: SLF001
            try:
                read_only, risk_effective = self.tool_gateway.classify(contract.tool)
            except ToolNotRegisteredError as exc:
                await self._emit(  # noqa: SLF001
                    "action.policy_denied",
                    {"phase": "tool", "tool": contract.tool,
                     "basis": "工具未在网关注册（清单缺失）"},
                )
                raise VastaError(
                    code="tool.not_registered",
                    message=f"工具 {contract.tool!r} 未注册，写动作不执行",
                ) from exc

        # ── 守卫与预算（与 step 同语义）──
        try:
            self.collector.ensure_actable()  # noqa: SLF001
        except TerminalObservationError as exc:
            raise VastaError(code="run.terminal", message=str(exc)) from exc
        escalation = self.supervisor.check_loop(self._last_signature, action)  # noqa: SLF001
        if escalation is not None:
            await self._escalate(escalation)  # noqa: SLF001
        try:
            self.tracker.check()  # noqa: SLF001
        except BudgetExceededError as exc:
            await self._safe_stop(reason=exc.kind.value, safe_stop=True)  # noqa: SLF001
            raise

        # ── 执行段（网关路径 / env 直连路径）──
        if self.tool_gateway is not None:  # noqa: SLF001
            observations = await self._execute_via_gateway(
                contract, action, plan_step_id=plan_step_id,
                risk_effective=risk_effective, read_only=read_only,
            )
            return observations
        try:
            observations = await self.env.execute(action)  # noqa: SLF001
        except Exception as exc:
            await self._emit(  # noqa: SLF001
                "action.failed",
                {"tool": contract.tool, "phase": "execution",
                 "error": f"{type(exc).__name__}: {exc}"},
            )
            await self.fail(f"env_error:{type(exc).__name__}")  # noqa: SLF001
            raise
        self.tracker.record_action()  # noqa: SLF001
        self._last_action = action  # noqa: SLF001
        await self._emit(  # noqa: SLF001
            "action.executed",
            {"tool": contract.tool, "ok": True},
        )"""
assert old in s
s = s.replace(old, new)

open(p, "w", encoding="utf-8", newline="\n").write(s)
print("contracted patched phase 1")
