"""人工控制：暂停/接管/批准/撤销（FR-052，Story 3.6）。"""

from __future__ import annotations

from vasta_protocols.errors import VastaError

from .state import RunState


class TakeoverRequiredError(VastaError):
    def __init__(self, op: str) -> None:
        super().__init__(
            code="control.takeover_required",
            message=f"接管模式下 {op} 需人工确认（confirm=True）",
            retryable=False,
        )
        self.op = op


class RevocationError(VastaError):
    def __init__(self, reason: str) -> None:
        super().__init__(
            code="control.revocation_failed",
            message=f"撤销失败：{reason}",
            retryable=False,
        )


class HumanControlMixin:
    """挂载于 RunEngine（3.6）：接管模式 + 批准/撤销正式 API。

    - takeover()：进入接管模式——后续 step/execute_contracted 需 confirm=True；
    - release_control()：解除接管；
    - approve_pending(contract)：R3 暂停态下的正式批准入口（内部转
      execute_contracted(approved=True) 续行）；
    - revoke(contract)：撤销已批准未执行的动作（批准不可撤销已执行的）。
    """

    async def takeover(self) -> None:
        """进入接管模式（人工逐动作确认）。"""
        if self._state is not RunState.STARTED:  # noqa: SLF001
            raise VastaError(
                code="run.not_started",
                message=f"takeover requires started run, current={self._state.value}",  # noqa: SLF001
            )
        self._takeover_mode = True  # noqa: SLF001
        await self._emit(  # noqa: SLF001
            "run.takeover", {"mode": "human", "note": "后续动作需人工确认"}
        )

    async def release_control(self) -> None:
        """解除接管模式（未接管时拒绝——防事件污染）。"""
        if not self.takeover_mode:
            raise VastaError(
                code="control.not_in_takeover", message="未处于接管模式"
            )
        self._takeover_mode = False  # noqa: SLF001
        await self._emit(  # noqa: SLF001
            "run.control_released", {"mode": "auto"}
        )

    @property
    def takeover_mode(self) -> bool:
        return getattr(self, "_takeover_mode", False)

    async def _takeover_gate(self, op: str, confirmed: bool) -> None:
        if self.takeover_mode and not confirmed:
            await self._emit(  # noqa: SLF001
                "action.takeover_required", {"op": op}
            )
            raise TakeoverRequiredError(op)

    async def approve_pending(
        self, contract, *, execute: bool = True, **kwargs  # noqa: ANN001
    ) -> list:  # noqa: ANN202
        """正式批准入口：从 approval 暂停态批准（可选续行）。

        - 仅接受因 approval_requested 暂停的 Run（评审修复：升级/手动暂停不可
          借此放行）；
        - execute=True（默认）：resume + approved 续行（六段链完整）；
        - execute=False：仅落 action.approved（批准未执行——撤销的目标态，
          评审修复：使 revoke 场景经公共 API 可达）。"""
        from vasta_contracts import ActionContract

        if not isinstance(contract, ActionContract):
            raise VastaError(code="control.bad_contract", message="需 ActionContract")
        if self._state is not RunState.PAUSED:  # noqa: SLF001
            raise VastaError(
                code="run.not_paused",
                message=f"approve_pending requires paused run, current={self._state.value}",  # noqa: SLF001
            )
        # 暂停原因必须是本工具的批准请求
        paused_events = [
            e for e in self.store.iter_run_events(self.config.run_id)  # noqa: SLF001
            if e.type == "run.paused" and "approval" in e.payload
        ]
        if not paused_events or paused_events[-1].payload["approval"].get(
            "tool"
        ) != contract.tool:
            raise VastaError(
                code="run.not_awaiting_approval",
                message=f"暂停原因不是 {contract.tool!r} 的批准请求",
            )
        if not execute:
            await self._emit(  # noqa: SLF001
                "action.approved",
                {"tool": contract.tool, "via": "human-local",
                 "note": "批准未执行（等待续行或撤销）"},
            )
            return []
        await self.resume()  # noqa: SLF001
        return await self.execute_contracted(  # noqa: SLF001
            contract, approved=True, **kwargs
        )

    async def revoke(self, contract) -> None:  # noqa: ANN001
        """撤销已批准未执行的动作批准（评审加固：防重复撤销 + 解除挂起）。"""
        """撤销已批准未执行的动作批准。

        - 已批准且未执行（计划步仍 pending/invalidated）→ 撤销 + 事件；
        - 已执行的不可撤销（撤销=补偿，FR-038 Stage 3）。"""
        from vasta_contracts import ActionContract

        if not isinstance(contract, ActionContract):
            raise VastaError(code="control.bad_contract", message="需 ActionContract")
        # 找最近的 approved 事件
        approved = [
            e
            for e in self.store.iter_run_events(self.config.run_id)  # noqa: SLF001
            if e.type == "action.approved"
        ]
        if not approved or approved[-1].payload.get("tool") != contract.tool:
            raise RevocationError(f"未找到 {contract.tool!r} 的待执行批准记录")
        # 其后若已有 executed → 已执行不可撤销
        events = list(self.store.iter_run_events(self.config.run_id))  # noqa: SLF001
        last_approved_seq = approved[-1].seq
        executed_after = [
            e
            for e in events
            if e.seq > last_approved_seq
            and e.type == "action.executed"
            and e.payload.get("tool") == contract.tool
        ]
        if executed_after:
            raise RevocationError(
                f"{contract.tool!r} 已执行——撤销已执行动作属补偿（FR-038，Stage 3）"
            )
        # 评审修复：防重复撤销
        already = [
            e for e in events
            if e.type == "action.approval_revoked"
            and e.payload.get("original_approval_seq") == last_approved_seq
        ]
        if already:
            raise RevocationError("该批准已被撤销")
        await self._emit(  # noqa: SLF001
            "action.approval_revoked",
            {"tool": contract.tool, "revoked_by": "human-local",
             "original_approval_seq": last_approved_seq},
        )
        # 评审修复：若 Run 因该批准挂起 → 解除（落 policy_denied 终结链）
        if self._state is RunState.PAUSED:  # noqa: SLF001
            await self._emit(  # noqa: SLF001
                "action.policy_denied",
                {"phase": "approval_revoked", "tool": contract.tool,
                 "basis": "批准被人工撤销"},
            )
            await self.cancel()  # noqa: SLF001


__all__ = ["HumanControlMixin", "RevocationError", "TakeoverRequiredError"]
