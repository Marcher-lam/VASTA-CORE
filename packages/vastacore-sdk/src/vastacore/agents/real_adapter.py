"""真实模型适配器接入（Story 11.11，G5——W-1 解除挂载）。

平台从替身模型走向真实模型：

- **OpenAICompatAdapter**：OpenAI 兼容 HTTP 形态参考实现
  （/v1/chat/completions）——ModelAdapter 协议完整实现；
- **BYOK 凭证**：SecretRef 注入（10.12——api_key 运行期解析，
  **不落库不进日志**；redact_secrets 脱敏面覆盖 adapter 配置）；
- **airgap 感知**：base_url 自动纳入 airgap_check 依赖清单；
- **W-1 解除路径**：``run_real_seed_ci``——真实适配器 × VastaLab
  任务集 ≥N 种子 → ``seed_confidence_interval``（9.11）并入评测
  报告的**接线**（本 Story 交付接线；真实解除由复评确认）；
- **门控集成测试**：``VASTA_REAL_ADAPTER`` 环境变量（base_url
  + api_key SecretRef 形态——未设 skip，先例 VASTA_PG_DSN/OIDC）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import (
    ModelAdapter,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
)

from ..governance.byok import SecretRef, airgap_check, redact_secrets


class RealAdapterConfig(BaseModel):
    """真实适配器配置（凭证仅 SecretRef——本体绝不入配置）。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    api_key_ref: SecretRef = Field(description="凭证引用（BYOK）")
    model_id: str = Field(min_length=1,
                          description="服务端模型 ID（如 gpt-4o-mini）")
    timeout_s: float = Field(default=30.0, gt=0)
    price_per_1k: float = Field(default=0.0, ge=0,
                                 description="成本面（router 排序用）")

    def redacted(self) -> dict[str, Any]:
        """脱敏视图（落库/日志面——凭证键替换指纹）。"""
        return redact_secrets({
            "name": self.name, "base_url": self.base_url,
            "model_id": self.model_id,
            "api_key": "byok-ref",
        })


class OpenAICompatAdapter(ModelAdapter):
    """OpenAI 兼容 HTTP 适配器（参考实现）。

    http_post 注入（async (url, headers, body) -> dict——测试
    fake 零网络；生产 httpx）。api_key_resolver 注入（SecretRef →
    key——运行期解析，缓存单次调用周期）。"""

    protocol_version = "0.1.0"

    def __init__(
        self, config: RealAdapterConfig, *,
        http_post: Any, api_key_resolver: Any,
    ) -> None:
        self.config = config
        self.capabilities = ModelCapabilities()
        self._http_post = http_post
        self._api_key_resolver = api_key_resolver

    async def generate(self, request: ModelRequest) -> ModelResponse:
        key = await self.config.api_key_ref.resolve(
            self._api_key_resolver)
        # 多模态接线（probe.vision 约定）：context.image_b64 → OpenAI
        # image_url data-URL 消息——真 VLM 才收得到像素；无图保持纯
        # 文本形态（后端兼容面最大）
        content: Any = request.prompt
        image_b64 = request.context.get("image_b64")
        if isinstance(image_b64, str) and image_b64:
            mime = str(request.context.get("image_mime", "image/png"))
            content = [
                {"type": "text", "text": request.prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
            ]
        body = {
            "model": self.config.model_id,
            "messages": [{"role": "user", "content": content}],
        }
        response = await self._http_post(
            f"{self.config.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            body=body,
            timeout_s=self.config.timeout_s,
        )
        if not isinstance(response, dict):
            raise VastaError(
                code="real_adapter.invalid_response",
                message=(f"{self.config.name} 返回体须为对象（得到 "
                         f"{type(response).__name__}——非 dict 响应"
                         "不可裸 AttributeError 传播）"),
            )
        if "error" in response:
            raise VastaError(
                code="real_adapter.upstream_error",
                message=(f"{self.config.name} 上游错误："
                         f"{response['error']!r}"),
            )
        choices = response.get("choices") or []
        if not choices:
            raise VastaError(
                code="real_adapter.empty_response",
                message=f"{self.config.name} 返回无 choices",
            )
        content = choices[0].get("message", {}).get("content", "")
        if not isinstance(content, str) or not content:
            raise VastaError(
                code="real_adapter.empty_content",
                message=(f"{self.config.name} 返回 content 空/非字符串"
                         f"（{content!r}）——不可裸 ValidationError"),
            )
        usage = response.get("usage") or {}
        return ModelResponse(content=content, detail={
            "usage": usage, "adapter": self.config.name,
        })


def adapter_airgap_dependency(config: RealAdapterConfig) -> Any:
    """适配器的外网依赖报告（airgap_check 联动）。"""
    return airgap_check(model_base_urls=(config.base_url,))


async def run_real_seed_ci(
    store: Any, adapter: OpenAICompatAdapter, *,
    seeds: list[int], task_results: dict[int, float],
    ci_level: float = 0.95,
    tenant_id: str = "t-default", project_id: str = "p-default",
) -> dict[str, Any]:
    """W-1 接线：真实适配器多种子结果 → CI 并入评测报告事件。

    task_results：seed → 成功率（真实评测产出——由调用方经
    adapter × VastaLab 跑出）；≥2 种子才产 CI（<2 拒——
    seed_confidence_interval 契约）。

    评审修复（边界 RA-3）：``seeds`` 与 ``task_results`` 键集对账
    ——事件声称的种子集必须与实际算 CI 的种子集一致（原先事件可
    声称与计算不同的种子集）。"""
    from ..governance.revalidation import seed_confidence_interval

    if set(task_results) != set(seeds):
        raise VastaError(
            code="real_adapter.seed_mismatch",
            message=(f"seeds {sorted(seeds)} 与 task_results 键集 "
                     f"{sorted(task_results)} 不符——事件声称的种子集"
                     "须与实际计算一致"),
        )
    if len(task_results) < 2:
        raise VastaError(
            code="real_adapter.needs_seeds",
            message=f"W-1 CI 需 ≥2 种子（得到 {len(task_results)}）",
        )
    values = [v for _, v in sorted(task_results.items())]
    ci = seed_confidence_interval(values, level=ci_level)
    from vasta_protocols.sequencer import EventSequencer

    sequencer = EventSequencer(
        store, "evaluation",
        tenant_id=tenant_id, project_id=project_id)
    await sequencer.emit("evaluation.real_seed_ci", {
        "adapter": adapter.config.name,
        "seeds": list(seeds),
        "ci": ci,
    })
    return ci


__all__ = ["OpenAICompatAdapter", "RealAdapterConfig",
           "adapter_airgap_dependency", "run_real_seed_ci"]
