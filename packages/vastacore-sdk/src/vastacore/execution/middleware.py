"""Middleware 接入形态（Story 8.14，FR-002 第四形态，蓝图 §18.5-2）。

既有 Agent 编排器零改造接入：用户保留自己的决策函数
``async decide(observation: dict) -> action: dict``（纯 dict，零 VastaCore
类型依赖），middleware 包住「观察 → 决策 → 执行」步——每次 decide 产出
的动作自动走 ``AgentSession.act`` 同一六段链（契约→策略→执行→核验→
审计），与 SDK 形态（Story 8.1）证据口径完全一致。

语义边界（与平台一致，不另造一套）：
- 核验偏差不向用户循环抛异常——有界恢复由引擎内管（FR-037），本层只
  把每次核验结论记录到 ``last_verdict`` / ``verdicts`` 供编排器读取；
- fail-closed 语义原样穿透：无契约模板（AD-12）、策略拒绝、审批挂起、
  恢复超限等按协议错误抛给用户循环处理；
- 观察是原始 Observation 的 JSON dict（model_dump），决策返回的 dict
  必须含 ``tool`` 键（可选 ``args``），缺 ``tool`` 在本层即拒（不进链）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action, Observation

from .agent import AgentSession

#: 用户决策函数：观察 dict → 动作 dict（``{"tool": ..., "args": {...}}``）。
Decide = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

_VERIFICATION_TYPES = {
    "verification.passed": "passed",
    "verification.deviated": "deviated",
    "verification.inconclusive": "inconclusive",
    "verification.errored": "errored",
}


class VastaMiddleware:
    """既有 Agent 循环的六段链包装（FR-002 middleware 形态）。

    用法::

        mw = VastaMiddleware(session)
        wrapped = mw.wrap(my_decide)     # my_decide 保持原签名（dict→dict）
        async with session:
            await session.start()
            await session.reset()
            await wrapped(first_observation_dict)

    或整循环托管（编排器不写循环）::

        await mw.run(steps=10)           # 每步：观察→decide→act 六段链
    """

    def __init__(self, session: AgentSession) -> None:
        self.session = session
        #: 最近一次动作的核验结论（"passed"/"deviated"/"inconclusive"/"errored"
        #: / None=无核验——观察路径）。
        self.last_verdict: str | None = None
        #: 全部核验结论按序记录（编排器侧的轻量偏差视图）。
        self.verdicts: list[str] = []

    # ---- 单步包装 ----
    def wrap(self, decide: Decide) -> Decide:
        """包住用户决策函数：观察经 session 采集，动作经六段链执行。"""

        async def wrapped(observation: dict[str, Any]) -> dict[str, Any]:
            action_dict = await decide(observation)
            await self.execute_action(action_dict)
            return action_dict

        return wrapped

    async def observe_dict(self) -> dict[str, Any]:
        """当前观察（JSON dict 形态——喂给用户 decide 的输入口径）。"""
        obs = await self.session.observe()
        return self._obs_to_dict(obs)

    async def execute_action(self, action_dict: dict[str, Any], *,
                             goal: str | None = None) -> list[dict[str, Any]]:
        """动作 dict → Action → 六段链执行（fail-closed 异常原样穿透）。"""
        if not isinstance(action_dict, dict) or "tool" not in action_dict:
            raise VastaError(
                code="middleware.action_shape",
                message="决策函数须返回含 'tool' 键的动作 dict"
                        f"（得到：{type(action_dict).__name__}）",
            )
        action = Action(
            tool=str(action_dict["tool"]),
            args=dict(action_dict.get("args") or {}),
        )
        observations = await self.session.act(action, goal=goal)
        self._record_verdict()
        return [self._obs_to_dict(o) for o in observations]

    # ---- 循环托管 ----
    async def run(self, decide: Decide, *, steps: int = 10) -> list[str]:
        """跑一个有界循环：观察 → decide → act（六段链），返回核验结论序。

        终止条件：steps 用尽、episode 结束、或用户 decide 抛出（原样穿透，
        编排器自主决定中止语义）。fail-closed 异常穿透。
        """
        verdicts: list[str] = []
        for _ in range(steps):
            if self.session.episode_ended:
                break
            obs = await self.observe_dict()
            action_dict = await decide(obs)
            await self.execute_action(action_dict)
            verdicts.append(self.last_verdict or "no_verification")
        return verdicts

    # ---- 内部 ----
    def _record_verdict(self) -> None:
        verdict = None
        for event in self.session.events():
            mapped = _VERIFICATION_TYPES.get(event.type)
            if mapped:
                verdict = mapped  # 取最后一个核验事件（本次动作的结论）
        self.last_verdict = verdict
        if verdict is not None:
            self.verdicts.append(verdict)

    @staticmethod
    def _obs_to_dict(obs: Observation) -> dict[str, Any]:
        try:
            return obs.model_dump(mode="json")
        except AttributeError:  # 非 pydantic 实现的兜底（协议允许）
            return {
                "kind": obs.kind,
                "detail": obs.detail,
                "available_actions": list(obs.available_actions or []),
            }


__all__ = ["VastaMiddleware", "Decide"]
