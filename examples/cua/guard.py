"""guardrails 动作闸：角色边界 + 委派白名单 + 自治 + 审批矩阵 +
组织风险预算（五积木官方组装缝 make_action_guard，Story 12.2）。

接线语义：guard 在 execute_contracted **之前**逐动作调用——任一层
拒绝即抛 VastaError（动作不进入任何执行路径，拒绝留痕落事件流）。
本模块提供 loop/eval 的默认闸配置与三层拒绝的负例演示。
"""

from __future__ import annotations

from typing import Any, Callable

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action
from vastacore.agents.autonomy import AutonomyLevel, AutonomyState
from vastacore.agents.delegation import DelegationContract
from vastacore.agents.guardrails import (
    GuardRailConfig,
    GuardState,
    make_action_guard,
)
from vastacore.agents.risk_budget import ExposureRecord, RiskBudget
from vastacore.agents.roles import AgentRole, AgentRoleConfig

AGENT_ID = "cua-loop"

#: 工具 → 角色类别映射（缺映射 = fail-closed 拒——make_action_guard
#: 内建 KeyError 防线）
TOOL_CATEGORIES: dict[str, str] = {
    "click_mark": "action",
    "type_text": "action",
    "save_doc": "action",
    "click_batch": "action",
    "screenshot": "observation",
    "read_display": "query",
}


def build_guard(store: Any, cfg: Any, *,
                permissions: tuple[str, ...] = ("click_mark",),
                risk_units: float = 8.0,
                high_risk_ops: int = 4,
                level: AutonomyLevel = AutonomyLevel.L2_ASSIST,
                ) -> tuple[Callable, GuardRailConfig, GuardState]:
    """组装 demo 动作闸。返回 (guard, config, state)。"""
    config = GuardRailConfig(
        agent_id=AGENT_ID,
        role_config=AgentRoleConfig(
            agent_id=AGENT_ID, role=AgentRole.ACTOR,
            tenant_id=cfg.tenant_id, project_id=cfg.project_id),
        risk_budget=RiskBudget(
            scope=f"agent:{AGENT_ID}", risk_units=risk_units,
            high_risk_ops=high_risk_ops,
            autonomy_ceiling=AutonomyLevel.L3_AUTONOMOUS,
            tenant_id=cfg.tenant_id, project_id=cfg.project_id),
        contract=DelegationContract(
            delegation_id="dlg-cua-demo",
            parent_agent="human-operator", child_agent=AGENT_ID,
            input_scope={"app": "Calculator"},
            permissions=list(permissions),
            budget={"max_actions": 30.0, "max_model_calls": 60.0,
                    "max_wall_seconds": 900.0},
            output_contract={
                "goal": "在沙盒应用内完成任务并全核验",
                "success_criteria": ["最终 AX 显示屏等于任务答案"],
                "failure_criteria": ["任何白名单外动作"],
            }),
        risk_weight=1.0,
        tenant_id=cfg.tenant_id, project_id=cfg.project_id,
    )
    state = GuardState(
        autonomy=AutonomyState(agent_id=AGENT_ID, level=level),
        exposure=ExposureRecord(scope=f"agent:{AGENT_ID}",
                                risk_units_used=0.0,
                                high_risk_ops_used=0),
    )

    def tool_category_of(tool: str) -> str:
        if tool not in TOOL_CATEGORIES:
            raise KeyError(tool)  # fail-closed（未知工具无类别）
        return TOOL_CATEGORIES[tool]

    def operation_risk_of(tool: str) -> float:
        return {"click_mark": 0.2, "type_text": 0.3, "save_doc": 0.9,
                "click_batch": 0.6}.get(tool, 0.1)

    guard = make_action_guard(
        store, config, state,
        tool_category_of=tool_category_of,
        operation_risk_of=operation_risk_of)
    return guard, config, state


async def demo_denials(store: Any, cfg: Any) -> list[str]:
    """三层拒绝负例（零 VLM/零点击——闸门面自证）。

    ① 角色：未知类别工具（shell_exec）→ 角色超面拒（fail-closed）；
    ② 委派：白名单外工具（type_text）→ 委派拒；
    ④ 审批矩阵：L2 × 高危 save_doc → 禁批；
    ⑤ 风险预算：L3 单次高危放行，二次连点 → 敞口触顶拒。
    """
    guard, _config, _state = build_guard(store, cfg)
    results: list[str] = []

    # ① 角色边界（未知类别 → fail-closed）
    try:
        await guard(Action(tool="shell_exec", args={}))
        results.append("① 角色层：未拒绝（异常！）")
    except VastaError as exc:
        results.append(f"① 角色层拒绝 ✓ {exc.code}")

    # ② 委派白名单（type_text 不在 permissions）
    try:
        await guard(Action(tool="type_text", args={"text": "x"}))
        results.append("② 委派层：未拒绝（异常！）")
    except VastaError as exc:
        results.append(f"② 委派层拒绝 ✓ {exc.code}")

    # ④ 审批矩阵（L2 × 高危 0.9 → 禁批——先于预算层触发）
    guard4, _, _ = build_guard(store, cfg,
                               permissions=("click_mark", "save_doc"))
    try:
        await guard4(Action(tool="save_doc", args={"filename": "x"}))
        results.append("④ 审批矩阵：未拒绝（异常！）")
    except VastaError as exc:
        results.append(f"④ 审批矩阵禁批 ✓ {exc.code}")

    # ⑤ 风险预算（L3 + 中危 0.6 click_batch：矩阵不拦（最多 required），
    #    敞口逐次累积 → 第二次触顶拒——预算层独立生效的证明）
    guard5, _, _ = build_guard(
        store, cfg, permissions=("click_mark", "save_doc", "click_batch"),
        risk_units=1.5, high_risk_ops=3, level=AutonomyLevel.L3_AUTONOMOUS)
    msgs = []
    for i in (1, 2):
        try:
            await guard5(Action(tool="click_batch", args={"marks": [1, 2]}))
            msgs.append(f"第{i}次放行")
        except VastaError as exc:
            msgs.append(f"第{i}次拒({exc.code})")
    results.append("⑤ 风险预算层：" + "，".join(msgs)
                   + ("✓" if msgs[-1].startswith("第2次拒") else
                      "（未触顶——配置异常）"))
    return results


__all__ = ["AGENT_ID", "TOOL_CATEGORIES", "build_guard", "demo_denials"]
