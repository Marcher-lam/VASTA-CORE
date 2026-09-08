"""ToolAdapter 契约：清单完整性、幂等行为、dry-run。"""

from __future__ import annotations

from ..protocols import Action, ToolAdapter


class ToolAdapterContract:
    def make_adapter(self) -> ToolAdapter:
        raise NotImplementedError("adapter package must provide make_adapter()")

    async def test_manifest_complete(self) -> None:
        manifest = self.make_adapter().manifest
        assert manifest.name and manifest.version
        assert manifest.risk in {"R0", "R1", "R2", "R3", "R4"}
        assert isinstance(manifest.read_only, bool)
        assert isinstance(manifest.idempotent, bool)

    async def test_idempotent_replay_returns_original(self) -> None:
        """AD-11：同幂等键重复请求只返回原结果 + replayed 标记，绝不静默重执行。"""
        adapter = self.make_adapter()
        action = Action(tool=adapter.manifest.name, args={})
        first = await adapter.execute(action, idempotency_key="k-1")
        second = await adapter.execute(action, idempotency_key="k-1")
        assert first.ok == second.ok
        assert second.replayed is True
        assert second.detail == first.detail

    async def test_dry_run_shape(self) -> None:
        adapter = self.make_adapter()
        result = await adapter.dry_run(Action(tool=adapter.manifest.name, args={}))
        assert isinstance(result.allowed, bool)

    async def test_read_back_returns_observation(self) -> None:
        adapter = self.make_adapter()
        obs = await adapter.read_back(Action(tool=adapter.manifest.name, args={}))
        assert obs.kind in {"decision", "transition", "terminal", "reset", "external"}

    async def test_compensate_returns_compensation_result(self) -> None:
        from ..protocols import CompensationResult

        result = await self.make_adapter().compensate({})
        assert isinstance(result, CompensationResult)
