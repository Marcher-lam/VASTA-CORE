"""历史轨迹离线评估（Story 8.10，FR-066，G4）——不重跑生产预判切换影响。

只读重放：对导入轨迹（8.2）或引擎 Run 的每个动作重建核验证据
（after_observation + result(CAS) + expected_changes），跑**新**核验器，
与**旧**判定（原流 verification.* 事件；导入轨迹=none-recorded 如实标注）
对照——偏差清单含事件定位；全程零副作用（不写事件/工件/不执行动作）。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
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
    seed_ci: dict[str, float] | None = Field(
        default=None,
        description="多种子置信区间（Story 12.10——W-1：CI 并入报告"
                    "结构（seed_confidence_interval 契约字段），"
                    "真实适配器评测路径产出；None 即未跑多种子面)",
    )


def attach_seed_ci(report: OfflineEvalReport, ci: dict[str, float],
                   ) -> OfflineEvalReport:
    """把多种子 CI 并入报告（W-1——报告结构一等公民）。

    ci 须为 seed_confidence_interval 契约形（n/mean/half_width/low/
    high/level 键齐——不齐即拒，报告不携带半吊子区间）。"""
    required = {"n", "mean", "half_width", "low", "high", "level"}
    missing = required - set(ci)
    if missing:
        raise VastaError(
            code="eval.bad_seed_ci",
            message=f"CI 缺契约字段 {sorted(missing)}（不齐不入报告）",
        )
    extra = set(ci) - required
    if extra:
        raise VastaError(
            code="eval.bad_seed_ci",
            message=f"CI 含契约外字段 {sorted(extra)}（不携带多余键）",
        )
    import math

    for key in ("n", "mean", "half_width", "low", "high", "level"):
        value = ci[key]
        if isinstance(value, bool) \
                or not isinstance(value, (int, float)) \
                or not math.isfinite(value):
            raise VastaError(
                code="eval.bad_seed_ci",
                message=f"CI 字段 {key}={value!r} 须为有限数"
                        "（model_copy 绕过校验——显式值校验）",
            )
    return OfflineEvalReport.model_validate(
        report.model_copy(update={"seed_ci": dict(ci)}))


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
    none-recorded + 新 deviation → 冲突（新核验器会拦下这批历史动作）。
    评审修复：最坏判定按严重度排序取（deviation > system_error >
    inconclusive > pass），不再取 dict 首值——多核验器时 system_error
    不再被 pass 掩盖。"""
    worst_rank = {"deviation": 3, "system_error": 2, "inconclusive": 1,
                  "pass": 0}
    new_worst = max(
        (worst_rank.get(v, 1) for v in new_outcomes.values()), default=0
    )
    if old == "none-recorded":
        return new_worst >= 3  # 仅新 deviation 构成冲突
    return worst_rank.get(old, 1) != new_worst


def _pair_args(events: list[Any]) -> dict[int, dict[str, Any]]:
    """executed 事件 seq → 其 contracted args（评审修复：FIFO 配对）。

    原实现「向前找最近的同工具 contracted」在并行同工具调用（c1/c2 相邻
    声明、相邻执行）时把两个 executed 都配到最后一个声明——args 错配使
    expected_changes 证据不可信。改为按事件序 FIFO：每工具维护待配对
    队列，contracted 入队、executed 出队；有 call_id 时优先精确匹配。"""
    pending: dict[str, list[tuple[str | None, dict[str, Any], int]]] = {}
    pairing: dict[int, dict[str, Any]] = {}
    for event in events:
        p = event.payload
        if event.type == "action.contracted":
            tool = str(p.get("tool", ""))
            pending.setdefault(tool, []).append(
                (p.get("call_id"), dict(p.get("args", {})), event.seq)
            )
        elif event.type == "action.executed":
            tool = str(p.get("tool", ""))
            call_id = p.get("call_id")
            queue = pending.get(tool)
            if not queue:
                continue
            # call_id 精确匹配优先；否则 FIFO 队首
            match_index = next(
                (i for i, (cid, _a, _s) in enumerate(queue) if cid == call_id
                 and call_id is not None),
                0,
            )
            _cid, args, _seq = queue.pop(match_index)
            pairing[event.seq] = args
    return pairing


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
    return await _evaluate_events(
        events,
        artifact_fetch=lambda sha: store.get_artifact(
            sha, tenant_id=tenant_id, project_id=project_id
        ),
        verifiers=verifiers,
        expected_changes_provider=expected_changes_provider,
        run_id=run_id,
    )


async def replay_bundle_verifiers(
    bundle_event_bytes: bytes,
    artifact_fetch: Callable[[str], Awaitable[bytes]],
    *,
    verifiers: Mapping[str, Verifier],
    expected_changes_provider: ExpectedChangesProvider | None = None,
) -> OfflineEvalReport:
    """复现包驱动的 verifier 离线重放（AC-08 关缺实现）。

    bundle_event_bytes：export_repro_bundle 的 events JSON Lines；
    artifact_fetch：result_ref→blob 取回（随包对象目录；MVP 以同根
    store 模拟——复现包清单携带全部 artifact_refs）。"""
    from vasta_protocols.envelope import EventEnvelope

    events = [
        EventEnvelope.model_validate_json(line)
        for line in bundle_event_bytes.decode("utf-8").splitlines()
        if line.strip()
    ]
    if not events:
        raise VastaError(
            code="offline_eval.empty_bundle",
            message="复现包事件流为空",
        )
    return await _evaluate_events(
        events, artifact_fetch=artifact_fetch, verifiers=verifiers,
        expected_changes_provider=expected_changes_provider,
        run_id=events[0].run_id,
    )


async def _evaluate_events(
    events: list[Any],
    *,
    artifact_fetch: Callable[[str], Awaitable[bytes]],
    verifiers: Mapping[str, Verifier],
    expected_changes_provider: ExpectedChangesProvider | None,
    run_id: str,
) -> OfflineEvalReport:
    args_pairing = _pair_args(events)
    results: list[ActionComparison] = []
    changed: list[ActionComparison] = []

    for index, event in enumerate(events):
        if event.type != "action.executed":
            continue
        tool = str(event.payload.get("tool", ""))
        args: dict[str, Any] = args_pairing.get(event.seq, {})
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
            blob = await artifact_fetch(str(result_ref))
            try:
                result_dict = json.loads(blob.decode("utf-8", errors="replace"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                # 非 JSON 结果（8.2 允许 bytes output 直接入 CAS）——
                # 评审修复：降级为 None 继续，不毁整份报告
                result_dict = None

        expected = (
            expected_changes_provider(tool, args)
            if expected_changes_provider else []
        )
        # 评审修复：与引擎核验证据同构——result 直接传解析后的响应本体
        # （引擎侧 evidence["result"] = json.loads(blob)，无二次包裹）
        evidence: dict[str, Any] = {
            "after_observation": ({"detail": after_detail}
                                  if after_detail is not None else None),
            "result": result_dict,
            "expected_changes": expected,
        }
        new_outcomes: dict[str, str] = {}
        deviation_notes: list[str] = []
        for name, verifier in verifiers.items():
            try:
                verification = await verifier.verify(str(result_ref or tool),
                                                     evidence)
                new_outcomes[name] = str(verification.outcome)
            except Exception as exc:  # noqa: BLE001 ——单核验器异常隔离
                # 评审修复：不毁整份报告，记 errored（与引擎词表一致）
                new_outcomes[name] = "system_error"
                deviation_notes.append(f"{name}: verifier crashed: {exc}")
                continue
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


__all__ = ["ActionComparison", "OfflineEvalReport", "offline_evaluate",
           "replay_bundle_verifiers"]
