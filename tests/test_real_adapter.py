"""Story 11.11：真实模型适配器接入（G5——W-1 挂载）。"""

from __future__ import annotations

import json

import pytest

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import ModelRequest
from vasta_storage import SqliteStorage
from vastacore.agents.real_adapter import (
    OpenAICompatAdapter,
    RealAdapterConfig,
    adapter_airgap_dependency,
    run_real_seed_ci,
)
from vastacore.governance.byok import SecretRef


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


def config() -> RealAdapterConfig:
    return RealAdapterConfig(
        name="real-gpt", base_url="https://api.openai.com/v1",
        api_key_ref=SecretRef(provider="kms", key_id="prod/key-1"),
        model_id="gpt-4o-mini", price_per_1k=0.15)


def adapter(response: dict | None = None) -> OpenAICompatAdapter:
    async def http_post(url, headers, body, timeout_s):
        if response is not None:
            return response
        return {"choices": [{"message": {"content": "真实回复"}}],
                "usage": {"total_tokens": 120}}

    async def key_resolver(ref: SecretRef) -> str:
        return "sk-resolved-at-runtime"

    return OpenAICompatAdapter(config(), http_post=http_post,
                              api_key_resolver=key_resolver)


class TestAdapter:
    async def test_generate_protocol(self) -> None:
        resp = await adapter().generate(ModelRequest(prompt="hi"))
        assert resp.content == "真实回复"
        assert resp.detail["usage"]["total_tokens"] == 120
        assert resp.detail["adapter"] == "real-gpt"

    async def test_key_runtime_resolved_not_stored(self) -> None:
        """BYOK：key 运行期解析——配置脱敏视图无本体。"""
        cfg = config()
        redacted = cfg.redacted()
        assert "sk-resolved" not in str(redacted)
        assert "prod/key-1" not in str(redacted["api_key"])

    async def test_empty_response_rejected(self) -> None:
        with pytest.raises(VastaError) as e:
            await adapter(response={"choices": []}).generate(
                ModelRequest(prompt="x"))
        assert e.value.code == "real_adapter.empty_response"

    async def test_image_b64_wired_to_image_url(self) -> None:
        """多模态接线：context.image_b64 → OpenAI image_url data-URL
        消息（真 VLM 才收得到像素——probe.vision 约定）。"""
        captured: dict = {}

        async def http_post(url, headers, body, timeout_s):
            captured["body"] = body
            return {"choices": [{"message": {"content": "marker=X"}}]}

        async def key_resolver(ref: SecretRef) -> str:
            return "k"

        a = OpenAICompatAdapter(config(), http_post=http_post,
                                api_key_resolver=key_resolver)
        await a.generate(ModelRequest(
            prompt="读出图中标记",
            context={"image_b64": "QUJD", "image_mime": "image/png"}))
        content = captured["body"]["messages"][0]["content"]
        assert isinstance(content, list)  # 多模态数组形态
        assert content[0] == {"type": "text", "text": "读出图中标记"}
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"] == \
            "data:image/png;base64,QUJD"

    async def test_no_image_stays_plain_text(self) -> None:
        """无图保持纯文本 content（后端兼容面最大）。"""
        captured: dict = {}

        async def http_post(url, headers, body, timeout_s):
            captured["body"] = body
            return {"choices": [{"message": {"content": "ok"}}]}

        async def key_resolver(ref: SecretRef) -> str:
            return "k"

        a = OpenAICompatAdapter(config(), http_post=http_post,
                                api_key_resolver=key_resolver)
        await a.generate(ModelRequest(prompt="hi"))
        assert captured["body"]["messages"][0]["content"] == "hi"

    def test_airgap_dependency_flagged(self) -> None:
        """airgap 联动：base_url 外网依赖被识别。"""
        report = adapter_airgap_dependency(config())
        assert report.offline_ready is False
        assert any("api.openai.com" in v for v in report.violations)


class TestSeedCi:
    async def test_ci_wired_into_report(self, store) -> None:
        """W-1 接线：多种子 → CI 并入评测报告事件。"""
        a = adapter()
        ci = await run_real_seed_ci(
            store, a, seeds=[1, 2, 3],
            task_results={1: 0.8, 2: 0.85, 3: 0.9},
            tenant_id="t", project_id="p")
        assert ci["n"] == 3.0
        assert ci["level"] == 0.95
        events = [e for e in store.iter_run_events(
            "evaluation", tenant_id="t", project_id="p")
            if e.type == "evaluation.real_seed_ci"]
        assert events[-1].payload["adapter"] == "real-gpt"
        assert events[-1].payload["ci"]["mean"] == ci["mean"]

    async def test_insufficient_seeds_rejected(self, store) -> None:
        with pytest.raises(VastaError) as e:
            await run_real_seed_ci(
                store, adapter(), seeds=[1], task_results={1: 0.8})
        assert e.value.code == "real_adapter.needs_seeds"


@pytest.mark.skipif(
    not __import__("os").environ.get("VASTA_REAL_ADAPTER"),
    reason="VASTA_REAL_ADAPTER 未设——真实适配器集成测试跳过"
    "（门控——先例 VASTA_PG_DSN/OIDC）",
)
class TestRealAdapterIntegration:
    """真实 API 联邦（VASTA_REAL_ADAPTER=base_url + 
    VASTA_REAL_KEY_REF_KMS_ID + VASTA_REAL_MODEL）。"""

    def test_real_generate(self) -> None:
        import os

        from vastacore.governance.byok import SecretRef

        cfg = RealAdapterConfig(
            name="real", base_url=os.environ["VASTA_REAL_ADAPTER"],
            api_key_ref=SecretRef(
                provider="env", key_id="VASTA_REAL_API_KEY"),
            model_id=os.environ.get("VASTA_REAL_MODEL", "gpt-4o-mini"))

        async def http_post(url, headers, body, timeout_s):
            import urllib.request

            req = urllib.request.Request(  # noqa: S310
                url, data=json.dumps(body).encode(),
                headers={**headers,
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(  # noqa: S310
                    req, timeout=timeout_s) as resp:
                return json.loads(resp.read())

        async def key_env(ref: SecretRef) -> str:
            return os.environ[ref.key_id]

        import asyncio

        a = OpenAICompatAdapter(cfg, http_post=http_post,
                                api_key_resolver=key_env)
        resp = asyncio.run(a.generate(ModelRequest(prompt="ping")))
        assert resp.content

    def test_real_vision_probe_detected(self) -> None:
        """W-1 视觉面：真渲染 PNG 密标经 image_url 接线 → 真 VLM
        从像素读出（探测 detected——VASTA_REAL_MODEL 须为 VLM）。"""
        import asyncio
        import os

        from vastacore.governance.byok import SecretRef
        from vastacore.models.probe import _MARKER, probe_capabilities

        cfg = RealAdapterConfig(
            name="real-vlm", base_url=os.environ["VASTA_REAL_ADAPTER"],
            api_key_ref=SecretRef(
                provider="env", key_id="VASTA_REAL_API_KEY"),
            model_id=os.environ.get("VASTA_REAL_MODEL", "gpt-4o-mini"),
            timeout_s=float(os.environ.get("VASTA_REAL_TIMEOUT_S", "120")))

        async def http_post(url, headers, body, timeout_s):
            import urllib.request

            req = urllib.request.Request(  # noqa: S310
                url, data=json.dumps(body).encode(),
                headers={**headers,
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(  # noqa: S310
                    req, timeout=timeout_s) as resp:
                return json.loads(resp.read())

        async def key_env(ref: SecretRef) -> str:
            return os.environ[ref.key_id]

        a = OpenAICompatAdapter(cfg, http_post=http_post,
                                api_key_resolver=key_env)
        report = asyncio.run(probe_capabilities(a, probe_timeout_s=120))
        vision = report.probes["vision"]
        assert vision.status == "detected", (
            f"真 VLM 应从像素读出密标 {_MARKER!r}：{vision.evidence}"
        )



def _static_response(payload):
    async def http_post(url, headers, body, timeout_s):
        return payload
    return http_post


class TestRealAdapterReviewRegressions:
    """Epic 11 评审修复回归（边界 RA-1/RA-2、盲审 L6/L7）。"""

    async def test_non_dict_response_wrapped(self) -> None:
        """RA-1：http_post 返回 None/list → 受控 VastaError（非裸
        AttributeError）。"""
        for bad in (None, ["choices"], 42):
            a = adapter()
            a._http_post = _static_response(bad)  # noqa: SLF001
            with pytest.raises(VastaError) as err:
                await a.generate(ModelRequest(prompt="hi"))
            assert err.value.code == "real_adapter.invalid_response"

    async def test_upstream_error_body_surfaces(self) -> None:
        """RA-1：上游 error 体语义不再丢失（原先只报无 choices）。"""
        a = adapter(response={"error": {"message": "quota exceeded"}})
        with pytest.raises(VastaError) as err:
            await a.generate(ModelRequest(prompt="hi"))
        assert err.value.code == "real_adapter.upstream_error"
        assert "quota" in err.value.message

    async def test_none_content_wrapped(self) -> None:
        """L7：content=None → 受控错误（非裸 pydantic ValidationError）。"""
        a = adapter(response={"choices": [
            {"message": {"role": "assistant", "content": None}}]})
        with pytest.raises(VastaError) as err:
            await a.generate(ModelRequest(prompt="hi"))
        assert err.value.code == "real_adapter.empty_content"

    async def test_seeds_results_reconciliation(self, store) -> None:
        """L6/RA-3：seeds 与 task_results 键集不符——拒（事件不可
        声称与实际计算不同的种子集）。"""
        with pytest.raises(VastaError) as e:
            await run_real_seed_ci(
                store, adapter(), seeds=[1, 2, 3],
                task_results={1: 0.9, 2: 0.8})
        assert e.value.code == "real_adapter.seed_mismatch"
