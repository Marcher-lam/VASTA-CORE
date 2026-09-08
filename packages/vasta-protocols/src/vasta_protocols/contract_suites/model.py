"""ModelAdapter 契约：能力声明与生成调用。"""

from __future__ import annotations

from ..protocols import ModelAdapter, ModelRequest


class ModelAdapterContract:
    def make_adapter(self) -> ModelAdapter:
        raise NotImplementedError("adapter package must provide make_adapter()")

    async def test_protocol_version_carried(self) -> None:
        adapter = self.make_adapter()
        assert isinstance(adapter.protocol_version, str) and adapter.protocol_version

    async def test_capabilities_declared(self) -> None:
        adapter = self.make_adapter()
        caps = adapter.capabilities
        assert isinstance(caps.vision, bool)
        assert caps.context_window >= 0

    async def test_generate_returns_response(self) -> None:
        adapter = self.make_adapter()
        response = await adapter.generate(ModelRequest(prompt="ping"))
        assert isinstance(response.content, str)
