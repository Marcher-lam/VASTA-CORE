"""本地模型客户端（OpenAI 兼容）+ 平台原生的内容寻址响应缓存。

设计要点：
- http 注入式（学 real_adapter 模式）：默认 stdlib urllib 经 to_thread，
  测试可注入 fake http_post，零新增运行时依赖；
- 响应缓存走 vasta-storage 实体索引（AD-2 合规，零侧车文件）：
  cache key = sha256(规范化请求 JSON) 作为实体值登记
  （entities={"rag_model_call": key} → search_by_entity 反查工件），
  命中即读 CAS、不再调 API → 评测重跑零 API 调用、结果可复现。
  缓存只存本质字段（剥离 id/created 等非确定内容）。
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import urllib.error
import urllib.request
from typing import Any

from .config import RagConfig

ENTITY_KEY = "rag_model_call"


def _lms_load(model: str) -> None:
    """LM Studio 模型被逐出时的自愈重载（阻塞；失败静默交由上层报错）。"""
    import subprocess
    if not model:
        return
    with contextlib.suppress(Exception):
        subprocess.run(["lms", "load", model, "--yes"], capture_output=True,
                       timeout=600)


def _lms_reset(model: str) -> None:
    """超时自愈：卸载（清空卡死的生成队列/僵尸生成）再重载。"""
    import subprocess
    if not model:
        return
    try:
        subprocess.run(["lms", "unload", model], capture_output=True, timeout=120)
        subprocess.run(["lms", "load", model, "--yes"], capture_output=True,
                       timeout=600)
    except Exception:
        pass


def _default_http_post(url: str, headers: dict[str, str], body: dict[str, Any],
                       timeout_s: int) -> dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


class CloudClient:
    """embedding + 多模态 VLM 双端口，同一 OpenAI 兼容服务。"""

    def __init__(self,cfg: RagConfig, store: Any = None,
                 http_post: Any = _default_http_post) -> None:
        self._cfg = cfg
        self._store = store  # 提供则启用响应缓存
        self._http_post = http_post

    # ---- 基础 HTTP ----

    async def _post(self, path: str, body: dict[str, Any],
                    timeout_s: int | None = None) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if self._cfg.api_key:
            headers["Authorization"] = f"Bearer {self._cfg.api_key}"
        url = f"{self._cfg.base_url}{path}"
        # 超时随生成长度缩放（实测持续 ~8-20 tok/s，取保守 0.25s/token）
        budget = timeout_s or self._cfg.timeout_s
        if path.endswith("/chat/completions"):
            budget = max(budget, int(body.get("max_tokens", 0) * 0.25) + 60)
        try:
            return await asyncio.to_thread(
                self._http_post, url, headers, body, budget)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            # LM Studio 内存压力会逐出模型：自动 lms load 后重试一次
            if exc.code == 400 and "unloaded" in detail.lower():
                model = str(body.get("model", ""))
                await asyncio.to_thread(_lms_load, model)
                try:
                    return await asyncio.to_thread(
                        self._http_post, url, headers, body, budget)
                except urllib.error.HTTPError as exc2:
                    detail = exc2.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"HTTP {exc.code} {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"无法连接 {self._cfg.base_url}（{exc.reason}）") from exc
        except TimeoutError as exc:
            # 超时多为僵尸生成堵队（客户端断连后服务端仍会跑完）：
            # 卸载清队列 + 重载 + 重试一次
            await asyncio.to_thread(_lms_reset, str(body.get("model", "")))
            try:
                return await asyncio.to_thread(
                    self._http_post, url, headers, body, budget)
            except TimeoutError:
                raise RuntimeError(
                    f"生成超时（>{budget:.0f}s，max_tokens="
                    f"{body.get('max_tokens')}）——重置模型后仍超时"
                ) from exc

    # ---- 响应缓存（实体索引：请求哈希 → 工件） ----

    @staticmethod
    def _cache_key(kind: str, body: dict[str, Any]) -> str:
        canonical = json.dumps({"kind": kind, "body": body},
                               ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def _cache_get(self, key: str) -> dict[str, Any] | None:
        if self._store is None:
            return None
        hits = await self._store.search_by_entity(
            ENTITY_KEY, key,
            tenant_id=self._cfg.tenant_id, project_id=self._cfg.project_id,
            include_derived=False)
        for hit in hits:
            if hit.get("kind") != "artifact":
                continue
            raw = await self._store.get_artifact(
                str(hit["ref"]),
                tenant_id=self._cfg.tenant_id, project_id=self._cfg.project_id)
            return json.loads(raw.decode("utf-8"))
        return None

    async def _cache_store(self, key: str, essential: dict[str, Any]) -> None:
        if self._store is None:
            return
        await self._store.save_artifact(
            json.dumps(essential, ensure_ascii=False, sort_keys=True).encode("utf-8"),
            mime="application/json", source="rag.model_call",
            tags={"rag_kind": "model_response"},
            entities={ENTITY_KEY: key},
            tenant_id=self._cfg.tenant_id, project_id=self._cfg.project_id,
        )

    # ---- embedding 端口 ----

    async def embed(self, texts: list[str]) -> list[list[float]]:
        body: dict[str, Any] = {"model": self._cfg.embed_model, "input": texts}
        key = self._cache_key("embed", body)
        cached = await self._cache_get(key)
        if cached is not None:
            return cached["embeddings"]
        resp = await self._post("/embeddings", body)
        data = sorted(resp["data"], key=lambda d: d["index"])
        embeddings = [item["embedding"] for item in data]
        essential = {"embeddings": embeddings, "model": resp.get("model"),
                     "dim": len(embeddings[0]) if embeddings else 0}
        await self._cache_store(key, essential)
        return embeddings

    # ---- VLM 端口（多模态） ----

    async def generate(self, system: str, prompt: str,
                       images: list[tuple[bytes, str]] | None = None,
                       max_tokens: int | None = None) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for raw, mime in images or []:
            b64 = base64.b64encode(raw).decode("ascii")
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"}})
        body = {"model": self._cfg.vlm_model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": content}],
                "temperature": 0,
                # 思考型模型：尽力压短 reasoning（LM Studio 会尽力传给模板）
                "chat_template_kwargs": {"enable_thinking": False},
                "max_tokens": max_tokens or self._cfg.max_tokens}
        key = self._cache_key("generate", body)
        cached = await self._cache_get(key)
        if cached is not None:
            return cached
        # 思考型模型的 reasoning 长度非确定（同 prompt 可能远超平均）：
        # 空 content 且 finish=length 时按 3 倍预算重试一次
        for attempt in range(2):
            resp = await self._post("/chat/completions", body)
            choice = resp["choices"][0]
            msg = choice["message"]
            content_text = msg.get("content") or ""
            if content_text.strip():
                break
            if attempt == 0 and choice.get("finish_reason") == "length":
                body = {**body, "max_tokens": body["max_tokens"] * 3}
                key = self._cache_key("generate", body)
                continue
            raise RuntimeError(
                "VLM 返回空 content（reasoning 耗尽 max_tokens？"
                f"finish={choice.get('finish_reason')}，"
                "请调大 max_tokens 或 RAG_VLM_MODEL 换非思考模型)")
        essential = {"content": content_text,
                     "reasoning": msg.get("reasoning_content", ""),
                     "usage": resp.get("usage", {}), "model": resp.get("model")}
        await self._cache_store(key, essential)
        return essential
