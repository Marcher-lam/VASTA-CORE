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
        """解除接管模式。"""
        self._takeover_mode = False  # noqa: SLF001
        await self._emit(  # noqa: SLF001
            "run.control_released", {"mode": "auto"}
        )

    @property
    def takeover_mode(self) -> bool:
        return getattr(self, "_takeover_mode", False)

    def _check_takeover(self, op: str, confirmed: bool) -> None:
        """接管模式下未确认的操作：落事件并抛出（调用方 async 上下文）。"""
        if self.takeover_mode and not confirmed:
            raise TakeoverRequiredError(op)

    async def _takeover_gate(self, op: str, confirmed: bool) -> None:
        if self.takeover_mode and not confirmed:
            await self._emit(  # noqa: SLF001
                "action.takeover_required", {"op": op}
            )
            raise TakeoverRequiredError(op)

    async def approve_pending(self, contract, **kwargs) -> list:  # noqa: ANN001, ANN202
        """正式批准入口：从 R3 暂停态批准并续行该动作。

        要求当前为 paused（approval 暂停）；批准后自动 resume 再以
        approved=True 续行——六段链完整（3.3 语义正式化）。"""
        from vasta_contracts import ActionContract  # 延迟导入避免环

        if not isinstance(contract, ActionContract):
            raise VastaError(code="control.bad_contract", message="需 ActionContract")
        if self._state is not RunState.PAUSED:  # noqa: SLF001
            raise VastaError(
                code="run.not_paused",
                message=f"approve_pending requires paused run, current={self._state.value}",  # noqa: SLF001
            )
        await self.resume()  # noqa: SLF001
        return await self.execute_contracted(  # noqa: SLF001
            contract, approved=True, **kwargs
        )

    async def revoke(self, contract) -> None:  # noqa: ANN001
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
        await self._emit(  # noqa: SLF001
            "action.approval_revoked",
            {"tool": contract.tool, "revoked_by": "human-local",
             "original_approval_seq": last_approved_seq},
        )


__all__ = ["HumanControlMixin", "RevocationError", "TakeoverRequiredError"]
