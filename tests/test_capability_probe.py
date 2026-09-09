"""Story 8.5：模型五维能力探测（FR-003，G3）。

行为探测不信任自声明；fail-closed；报告入 CAS 留痕。
四类替身：全能力 / 盲模型 / 爆炸模型 / 声明不一致模型。
"""

from __future__ import annotations

import json

from vasta_protocols.protocols import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
)
from vasta_storage import SqliteStorage
from vastacore.probe import (
    CapabilityReport,
    probe_capabilities,
    save_capability_report,
)

#: 探测密标（图像标记回显用）。
MARKER = "VASTA-VISION-7Q4"


class BaseFake:
    protocol_version = "0.1.0"
    capabilities = ModelCapabilities()

    async def generate(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError


class CapableModel(BaseFake):
    """全能力：按探测协议正确应答。"""

    capabilities = ModelCapabilities(
        vision=True, structured_output=True, tool_calling=True,
        streaming=True, context_window=8192,
    )

    async def generate(self, request: ModelRequest) -> ModelResponse:
        ctx = request.context
        if ctx.get("probe") == "vision":
            # 真实视觉模型从图像里读出密标；替身从 context 回显
            return ModelResponse(content=f"marker={ctx['image_b64'][-20:]}")
        if ctx.get("probe") == "structured":
            return ModelResponse(content=json.dumps({"ok": True, "n": 7}))
        if ctx.get("probe") == "tool_call":
            return ModelResponse(content=json.dumps(
                {"tool": "probe_tool", "args": {"x": 1}}
            ))
        if ctx.get("probe") == "context":
            return ModelResponse(content=f"needle={ctx['needle']}")
        return ModelResponse(content="ok")

    async def generate_stream(self, request: ModelRequest):
        for chunk in ("a", "b", "c"):
            yield ModelResponse(content=chunk)


class BlindModel(BaseFake):
    """盲模型：一律答不知道（应答了但答错 → not_detected）。"""

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(content="I cannot do that")


class ExplodingModel(BaseFake):
    """爆炸模型：调用即抛（→ probe_failed，fail-closed）。"""

    capabilities = ModelCapabilities(vision=True)

    async def generate(self, request: ModelRequest) -> ModelResponse:
        raise RuntimeError("provider 500")


class LyingModel(BaseFake):
    """声明不一致：自声明全能力但行为全错。"""

    capabilities = ModelCapabilities(
        vision=True, structured_output=True, tool_calling=True,
        streaming=True, context_window=1_000_000,
    )

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(content="totally not a valid answer")


class TestProbe:
    async def test_capable_model_all_detected(self) -> None:
        report = await probe_capabilities(CapableModel())
        assert isinstance(report, CapabilityReport)
        for name in ("vision", "structured_output", "tool_calling",
                     "streaming", "context"):
            outcome = report.probes[name]
            assert outcome.status == "detected", (name, outcome)
            assert outcome.supported is True
            assert outcome.method, name  # 含探测方法
            assert outcome.confidence >= 0.7, name  # 声明+行为一致 → 0.9
        assert report.discrepancies == []

    async def test_blind_model_not_detected_with_evidence(self) -> None:
        report = await probe_capabilities(BlindModel())
        for name in ("vision", "structured_output", "tool_calling"):
            outcome = report.probes[name]
            assert outcome.status == "not_detected"
            assert outcome.supported is False
            assert outcome.evidence  # 证据摘要留痕

    async def test_exploding_model_fails_closed(self) -> None:
        """AC：探测失败 fail-closed（按无能力处理，不猜测）。"""
        report = await probe_capabilities(ExplodingModel())
        for name, outcome in report.probes.items():
            assert outcome.supported is False, name
            if name == "streaming":
                continue  # 无 generate_stream → not_detected
            assert outcome.status == "probe_failed", name
            assert outcome.confidence == 0.0
            assert "RuntimeError" in outcome.evidence

    async def test_lying_model_behavior_wins(self) -> None:
        """声明与行为不一致 → 行为胜出 + 差异入报告。"""
        report = await probe_capabilities(LyingModel())
        for name in ("vision", "structured_output", "tool_calling"):
            assert report.probes[name].supported is False
        assert report.discrepancies, "差异必须被记录"
        assert any("vision" in d for d in report.discrepancies)
        # 有效能力视图以行为为准
        view = report.effective_capabilities()
        assert view.vision is False  # 自声明 True 被行为推翻

    async def test_declared_context_window_recorded(self) -> None:
        report = await probe_capabilities(CapableModel())
        assert report.declared.context_window == 8192
        view = report.effective_capabilities()
        assert isinstance(view.context_window, int)


class TestPersistence:
    async def test_report_saved_to_cas_and_verifiable(self, tmp_path) -> None:
        """AC：能力清单作为 Artifact 落盘留痕（AD-3，哈希可校验）。"""
        import hashlib

        store = SqliteStorage(tmp_path / "store")
        report = await probe_capabilities(CapableModel())
        sha = await save_capability_report(store, report)
        blob = await store.get_artifact(sha)
        assert hashlib.sha256(blob).hexdigest() == sha
        payload = json.loads(blob)
        assert payload["probes"]["vision"]["method"]
        assert payload["probes"]["vision"]["confidence"] > 0
        store.close()

    async def test_report_roundtrip_schema(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "store")
        report = await probe_capabilities(BlindModel())
        sha = await save_capability_report(store, report)
        payload = json.loads(await store.get_artifact(sha))
        restored = CapabilityReport.model_validate(payload)
        assert restored.probes["vision"].status == "not_detected"
        store.close()
