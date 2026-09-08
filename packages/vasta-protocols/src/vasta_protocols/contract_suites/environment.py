"""EnvironmentAdapter 契约：五类观察、决策帧可行动性、状态查询。"""

from __future__ import annotations

from ..protocols import Action, EnvironmentAdapter


class EnvironmentAdapterContract:
    """实现方实现 make_adapter() 返回被测适配器；若环境不接受默认的
    "noop" 动作，覆写 valid_action_tool 为该环境合法的任一动作名。"""

    valid_action_tool: str = "noop"

    def make_adapter(self) -> EnvironmentAdapter:
        raise NotImplementedError("adapter package must provide make_adapter()")

    async def test_protocol_version_carried(self) -> None:
        adapter = self.make_adapter()
        assert isinstance(adapter.protocol_version, str) and adapter.protocol_version

    async def test_reset_returns_decision_observation(self) -> None:
        adapter = self.make_adapter()
        obs = await adapter.reset(seed=0)
        assert obs.kind == "decision"  # 重置后的首观察是可行动状态
        assert obs.actionable

    async def test_observe_returns_observation(self) -> None:
        adapter = self.make_adapter()
        await adapter.reset(seed=0)
        obs = await adapter.observe()
        assert obs.kind in {"decision", "transition", "terminal", "reset", "external"}

    async def test_execute_returns_observation_sequence(self) -> None:
        adapter = self.make_adapter()
        await adapter.reset(seed=0)
        obs_list = await adapter.execute(Action(tool=self.valid_action_tool, args={}))
        assert isinstance(obs_list, list) and len(obs_list) >= 1
        for obs in obs_list:
            assert obs.kind in {"decision", "transition", "terminal", "reset", "external"}

    async def test_status_reports_running(self) -> None:
        adapter = self.make_adapter()
        await adapter.reset(seed=0)
        status = await adapter.status()
        assert isinstance(status.running, bool)
