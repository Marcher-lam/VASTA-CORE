"""契约预留段激活——事务批次（Story 9.7，FR-038，G3）。

- `TransactionBatch`：步骤列表 + batch_id；
- `execute_batch(session, batch)`：顺序执行，任一步失败**逆序**补偿已
  成功步（各步 compensate 留痕）；整体落 `transaction.settled` /
  `transaction.aborted`；
- dry-run 整体门：全部步骤先过 dry_run，任一拒则整批不执行；
- 幂等键 `batch_id:step_N:<args_hash>` 前缀稳定（AD-11）；
- 底座：Epic 3 网关的 dry_run 门 + 幂等缓存 + ToolAdapter.compensate——
  本模块组合为事务层，不修改网关/引擎本体。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.idempotency import canonical_args_hash
from vasta_protocols.protocols import ToolResult


class BatchStep(BaseModel):
    """单步（tool + args）。"""

    model_config = ConfigDict(extra="forbid")

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class TransactionBatch(BaseModel):
    """事务批次（步骤列表 + batch_id）。"""

    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=1)
    steps: list[BatchStep] = Field(default_factory=list)


class BatchResult(BaseModel):
    """事务批次结果。"""

    model_config = ConfigDict(extra="forbid")

    batch_id: str
    status: str  # settled | aborted | dry_run_rejected
    executed: list[str] = Field(default_factory=list)
    compensated: list[str] = Field(default_factory=list)
    compensation_failed: list[str] = Field(default_factory=list)
    failed_step: str | None = None


def _step_idempotency_key(batch: TransactionBatch, index: int) -> str:
    """批次步幂等键（batch_id:step_N:args_hash——AD-11 稳定派生）。"""
    step = batch.steps[index]
    args_hash = canonical_args_hash(step.args)
    return f"{batch.batch_id}:step_{index}:{args_hash}"


async def execute_batch(session: Any, batch: TransactionBatch) -> BatchResult:
    """执行事务批次：顺序 → 失败逆序补偿 → 整体事件。"""
    if not batch.steps:
        raise VastaError(
            code="transaction.empty_batch",
            message="事务批次至少需要一个步骤",
        )

    from vasta_protocols.protocols import Action

    # ---- dry-run 整体门（fail-closed——评审修复）----
    for step in batch.steps:
        gateway = session._gateway  # noqa: SLF001
        adapter = gateway._tools.get(step.tool)  # noqa: SLF001
        if adapter is None:
            # 未注册工具无 dry-run 面 → 拒整批（fail-closed：
            # 无法预检的动作不得混入事务批次——曾为静默跳过）
            return BatchResult(
                batch_id=batch.batch_id, status="dry_run_rejected",
                failed_step=step.tool,
            )
        if adapter.manifest.supports_dry_run:
            try:
                dry = await adapter.dry_run(
                    Action(tool=step.tool, args=step.args))
            except Exception:  # noqa: BLE001——dry_run 异常 = 拒（不裸逃）
                return BatchResult(
                    batch_id=batch.batch_id, status="dry_run_rejected",
                    failed_step=step.tool,
                )
            if not dry.allowed:
                return BatchResult(
                    batch_id=batch.batch_id, status="dry_run_rejected",
                    failed_step=step.tool,
                )

    # ---- 顺序执行 + 逆序补偿 ----
    executed: list[str] = []
    compensated: list[str] = []
    failed_step: str | None = None
    sequencer = session._engine._sequencer  # noqa: SLF001

    for i, step in enumerate(batch.steps):
        action = Action(tool=step.tool, args=step.args)
        key = _step_idempotency_key(batch, i)
        events_before = len(session.events())
        try:
            # 经 session.act（网关路径六段链 + 契约模板）
            await session.act(action)
        except Exception:  # noqa: BLE001——act 本身异常也触发补偿
            failed_step = step.tool
            await sequencer.emit("action.batch_step_failed", {
                "batch_id": batch.batch_id, "step_index": i,
                "tool": step.tool, "idempotency_key": key,
            })
            break
        # 步骤成败判定：act 不抛异常≠步骤成功——恢复可能掩盖偏差。
        # 事务语义：verification.deviated 或引擎离开 started 均为失败
        new_events = session.events()[events_before:]
        has_deviation = any(e.type in (
            "verification.deviated", "action.failed"
        ) for e in new_events)
        engine_failed = session._engine.state.value != "started"  # noqa: SLF001
        if has_deviation or engine_failed:
            failed_step = step.tool
            await sequencer.emit("action.batch_step_failed", {
                "batch_id": batch.batch_id, "step_index": i,
                "tool": step.tool, "idempotency_key": key,
                "deviation": has_deviation,
                "engine_state": session._engine.state.value,  # noqa: SLF001
            })
            break
        step_id = str(step.args.get("id", step.tool))
        executed.append(step_id)
        await sequencer.emit("action.batch_step_executed", {
            "batch_id": batch.batch_id, "step_index": i,
            "tool": step.tool, "step_id": step_id,
            "idempotency_key": key,
        })

    if failed_step is not None:
        # 逆序补偿已成功步
        gateway = session._gateway  # noqa: SLF001
        compensation_failed: list[str] = []
        for j in range(len(executed) - 1, -1, -1):
            step = batch.steps[j]
            step_id = executed[j]
            adapter = gateway._tools.get(step.tool)  # noqa: SLF001
            if adapter is not None:
                try:
                    await adapter.compensate(
                        Action(tool=step.tool, args=step.args),
                        ToolResult(ok=True, detail={}),
                    )
                    compensated.append(step_id)
                    await sequencer.emit("action.batch_step_compensated", {
                        "batch_id": batch.batch_id, "step_index": j,
                        "tool": step.tool, "step_id": step_id,
                    })
                except Exception as exc:  # noqa: BLE001——补偿失败不中断其余补偿
                    # 留痕（评审修复：补偿失败不再静默吞——事件面可审计
                    # 哪步悬空未回滚）
                    compensation_failed.append(step_id)
                    await sequencer.emit(
                        "action.batch_step_compensation_failed", {
                            "batch_id": batch.batch_id, "step_index": j,
                            "tool": step.tool, "step_id": step_id,
                            "error": f"{type(exc).__name__}: {exc}"[:200],
                        })
        await sequencer.emit("action.batch_aborted", {
            "batch_id": batch.batch_id,
            "executed": executed, "compensated": compensated,
            "compensation_failed": compensation_failed,
            "failed_step": failed_step,
        })
        return BatchResult(
            batch_id=batch.batch_id, status="aborted",
            executed=executed, compensated=compensated,
            compensation_failed=compensation_failed,
            failed_step=failed_step,
        )

    await sequencer.emit("action.batch_settled", {
        "batch_id": batch.batch_id, "executed": executed,
    })
    return BatchResult(
        batch_id=batch.batch_id, status="settled",
        executed=executed, compensated=compensated,
    )


__all__ = ["BatchResult", "BatchStep", "TransactionBatch",
           "execute_batch"]
