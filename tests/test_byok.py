"""Story 10.12：BYOK 与 air-gapped 形态（FR-074，G4）。"""

from __future__ import annotations

import pytest

from vasta_storage import SqliteStorage
from vastacore.governance.byok import (
    LOCAL_CAPABILITY,
    SecretRef,
    airgap_check,
    configure_secret_ref,
    redact_secrets,
)


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


class TestSecretRef:
    async def test_resolve_via_fetcher(self) -> None:
        ref = SecretRef(provider="kms", key_id="arn:aws:kms:…:key/7",
                        version="v3")

        async def fetcher(r: SecretRef) -> str:
            assert r is ref
            return "the-actual-secret"

        assert await ref.resolve(fetcher) == "the-actual-secret"

    async def test_resolve_empty_rejected(self) -> None:
        ref = SecretRef(provider="file", key_id="/run/secrets/x")

        async def empty(r: SecretRef) -> str:
            return ""

        with pytest.raises(ValueError):
            await ref.resolve(empty)

    def test_fingerprint_stable_and_short(self) -> None:
        a = SecretRef(provider="kms", key_id="k1", version="v1")
        b = SecretRef(provider="kms", key_id="k1", version="v1")
        c = SecretRef(provider="kms", key_id="k2", version="v1")
        assert a.fingerprint() == b.fingerprint()
        assert a.fingerprint() != c.fingerprint()
        assert len(a.fingerprint()) == 8


class TestRedaction:
    def test_key_names_redacted(self) -> None:
        config = {"api_key": "ABC123", "model": "gpt-x",
                  "nested": {"client_secret": "zzz", "ok": 1}}
        safe = redact_secrets(config)
        assert safe["api_key"].startswith("***redacted:")
        assert safe["model"] == "gpt-x"  # 非凭证不误伤
        assert safe["nested"]["client_secret"].startswith("***redacted:")
        assert safe["nested"]["ok"] == 1
        # 原配置不改（深拷贝）
        assert config["api_key"] == "ABC123"

    def test_value_prefix_heuristics(self) -> None:
        safe = redact_secrets({"auth": "sk-proj-123456"})
        assert safe["auth"].startswith("***redacted:")

    def test_redacted_not_reversible(self) -> None:
        safe = redact_secrets({"token": "super-secret-value"})
        assert "super-secret-value" not in str(safe)


class TestConfigTrace:
    async def test_secret_ref_traced_without_secret(self, store) -> None:
        """AC：密钥引用配置留痕（不含密钥本体）。"""
        ref = SecretRef(provider="vault", key_id="prod/model-key",
                        version="v2")
        await configure_secret_ref(store, ref, purpose="model-credential",
                                   tenant_id="t-default",
                                   project_id="p-default")
        events = [e for e in store.iter_run_events("access")
                  if e.type == "run.secret_ref_configured"]
        payload = events[-1].payload
        assert payload["provider"] == "vault"
        assert payload["purpose"] == "model-credential"
        assert payload["key_id"].startswith("fp:")  # 指纹面——非本体
        assert "prod/model-key" not in str(payload)
        assert payload["key_id"] == f"fp:{ref.fingerprint()}"


class TestAirgap:
    def test_fully_local_ready(self) -> None:
        """离线形态：全本地配置 → offline_ready + 降级链清单。"""
        report = airgap_check(
            s3_endpoints=("file:///data/blobs",),
            pg_dsns=("postgresql://u@localhost/db",),
            model_base_urls=("http://127.0.0.1:11434/v1",))
        assert report.offline_ready is True
        assert report.violations == []
        assert any("local-stub" in c for c in report.local_capability)

    def test_external_dependencies_listed(self) -> None:
        report = airgap_check(
            s3_endpoints=("https://s3.amazonaws.com",),
            pg_dsns=("postgresql://u@db.prod.corp/app",),
            model_base_urls=("https://api.openai.com/v1",),
            external_http=True)
        assert report.offline_ready is False
        assert len(report.violations) == 4
        assert any("S3" in v for v in report.violations)
        assert any("PG" in v for v in report.violations)

    def test_local_capability_chain_advertised(self) -> None:
        assert len(LOCAL_CAPABILITY) >= 4
        report = airgap_check()
        assert report.local_capability == list(LOCAL_CAPABILITY)

    async def test_offline_smoke_local_router(self, tmp_path) -> None:
        """AC：离线形态冒烟——纯本地配置下 router 降级链到本地
        替身适配器可用（无外网调用）。"""
        from vasta_protocols.protocols import (
            ModelCapabilities,
            ModelRequest,
            ModelResponse,
        )
        from vastacore.models.router import ModelRouter

        class LocalStub:
            protocol_version = "0.1.0"
            capabilities = ModelCapabilities()

            async def generate(self, request: ModelRequest) -> ModelResponse:
                return ModelResponse(content="local-ok")

        router = ModelRouter({"local-stub": (LocalStub(), 0.0)})
        resp = await router.generate(ModelRequest(prompt="hi"))
        assert resp.content == "local-ok"
        # 配套面：airgap 对该形态零违规
        report = airgap_check()
        assert report.offline_ready is True
