"""历史轨迹离线评估（Story 8.10，FR-066，G4）——不重跑生产预判切换影响。

只读重放：对导入轨迹（8.2）或引擎 Run 的每个动作重建核验证据
（after_observation + result(CAS) + expected_changes），跑**新**核验器，
与**旧**判定（原流 verification.* 事件；导入轨迹=none-recorded 如实标注）
对照——偏差清单含事件定位；全程零副作用（不写事件/工件/不执行动作）。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Verifier

#: 期望变化供给器：(tool, args) -> ["field=value", ...]（缺省无预期）。
ExpectedChangesProvider = Callable[[str, dict[str, Any]], list[str]]


class ActionComparison(BaseModel):
    """单动作新旧对照。"""

    model_config = ConfigDict(extra="forbid")

    seq: int = Field(description="action.executed 事件 seq（定位）")
    tool: str
    old_outcome: str = Field(description="passed/deviated/inconclusive/errored/"
                                "none-recorded")
    new_outcomes: dict[str, str] = Field(default_factory=dict)
    changed: bool = Field(description="新旧判定冲突（切换影响信号）")
    detail: str = Field(default="", description="证据摘要")


class OfflineEvalReport(BaseModel):
    """离线评估对比报告。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    actions_evaluated: int = Field(ge=0)
    results: list[ActionComparison] = Field(default_factory=list)
    changed: list[ActionComparison] = Field(
        default_factory=list, description="偏差清单（含事件定位）"
    )
    unchanged: int = Field(ge=0, description="新旧一致或新判定通过（无切换影响）")


#: 事件后缀 → 核验结果词表（VerificationOutcome）。
_EVENT_TO_OUTCOME = {
    "passed": "pass", "deviated": "deviation",
    "inconclusive": "inconclusive", "errored": "system_error",
}


def _old_outcome_of(events: list[Any], executed_index: int) -> str:
    """旧判定：该动作之后、下一动作之前的 verification.* 事件（取最后）。"""
    outcome = "none-recorded"
    for event in events[executed_index + 1:]:
        if event.type.startswith("action."):
            break
        if event.type.startswith("verification."):
            suffix = event.type.split(".", 1)[1]  # passed/deviated/…
            outcome = _EVENT_TO_OUTCOME.get(suffix, suffix)
    return outcome


def _conflict(old: str, new_outcomes: dict[str, str]) -> bool:
    """冲突判定：旧有记录且与新判定不一致；或新判 deviation 而旧非 deviation。

    none-recorded（导入轨迹无核验历史）+ 新 pass → 不算冲突（切换无影响）；
    none-recorded + 新 deviation → 冲突（新核验器会拦下这批历史动作）。"""
    has_new_deviation = any(v == "deviation" for v in new_outcomes.values())
    if old == "none-recorded":
        return has_new_deviation
    new_worst = ("deviation" if has_new_deviation
                 else next(iter(new_outcomes.values()), "pass"))
    return old != new_worst


async def offline_evaluate(
    store: Any,
    run_id: str,
    *,
    verifiers: Mapping[str, Verifier],
    expected_changes_provider: ExpectedChangesProvider | None = None,
    tenant_id: str = "t-default",
    project_id: str = "p-default",
) -> OfflineEvalReport:
    """只读重放评估（零副作用）。"""
    events = list(store.iter_run_events(
        run_id, tenant_id=tenant_id, project_id=project_id
    ))
    if not events:
        raise VastaError(
            code="offline_eval.run_not_found",
            message=f"未找到 Run {run_id!r}（无可评估事件）",
        )
    results: list[ActionComparison] = []
    changed: list[ActionComparison] = []

    for index, event in enumerate(events):
        if event.type != "action.executed":
            continue
        tool = str(event.payload.get("tool", ""))
        # 前置 contracted 取 args
        args: dict[str, Any] = {}
        for prior in reversed(events[:index]):
            if prior.type == "action.contracted" and \
                    prior.payload.get("tool") == tool:
                args = dict(prior.payload.get("args", {}))
                break
        # 证据：后续第一条观察 + CAS 结果
        after_detail: dict[str, Any] | None = None
        for following in events[index + 1:]:
            if following.type.startswith("observation."):
                after_detail = dict(following.payload.get("detail", {}))
                break
            if following.type.startswith("action."):
                break
        result_dict: dict[str, Any] | None = None
        result_ref = event.payload.get("result_ref")
        if result_ref:
            blob = await store.get_artifact(
                str(result_ref), tenant_id=tenant_id, project_id=project_id
            )
            result_dict = json.loads(blob.decode("utf-8"))

        expected = (
            expected_changes_provider(tool, args)
            if expected_changes_provider else []
        )
        evidence: dict[str, Any] = {
            "after_observation": ({"detail": after_detail}
                                  if after_detail is not None else None),
            "result": ({"detail": result_dict} if result_dict is not None
                       else None),
            "expected_changes": expected,
        }
        new_outcomes: dict[str, str] = {}
        deviation_notes: list[str] = []
        for name, verifier in verifiers.items():
            verification = await verifier.verify(str(result_ref or tool),
                                                 evidence)
            new_outcomes[name] = str(verification.outcome)
            if str(verification.outcome) == "deviation":
                deviation_notes.append(f"{name}: {verification.detail}")

        old_outcome = _old_outcome_of(events, index)
        is_changed = _conflict(old_outcome, new_outcomes)
        entry = ActionComparison(
            seq=event.seq, tool=tool, old_outcome=old_outcome,
            new_outcomes=new_outcomes, changed=is_changed,
            detail=(f"after={after_detail} result={str(result_dict)[:60]} "
                    f"expected={expected} "
                    f"deviations={deviation_notes}"),
        )
        results.append(entry)
        if is_changed:
            changed.append(entry)

    return OfflineEvalReport(
        run_id=run_id,
        actions_evaluated=len(results),
        results=results,
        changed=changed,
        unchanged=sum(1 for r in results if not r.changed),
    )


__all__ = ["ActionComparison", "OfflineEvalReport", "offline_evaluate"]
