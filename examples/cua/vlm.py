"""VLM 客户端（OpenAI 兼容，本地 LM Studio）+ 平台原生的响应缓存。

照抄 examples/rag/cloud.py 的已验证姿势（坑位经验一并继承）：
- image_url base64 内容段格式；
- 思考型模型 disable thinking + 空 content×finish=length 时 3 倍
  max_tokens 重试一次；
- LM Studio 内存逐出自愈（lms load 重试；超时 unload+load 清僵尸队列）；
- 响应缓存走 vasta-storage 实体索引（AD-2 合规，零侧车文件）：
  entities={"cua_model_call": sha256(规范化请求)} → 重跑零 API。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import urllib.error
import urllib.request
from typing import Any

from .config import CuaConfig

ENTITY_KEY = "cua_model_call"


def _default_http_post(url: str, headers: dict[str, str], body: dict[str, Any],
                       timeout_s: int) -> dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _lms(cmd: str, model: str) -> None:
    import subprocess
    if not model:
        return
    try:
        if cmd == "load":
            subprocess.run(["lms", "load", model, "--yes"],
                           capture_output=True, timeout=600)
        else:
            subprocess.run(["lms", "unload", model], capture_output=True,
                           timeout=120)
            subprocess.run(["lms", "load", model, "--yes"],
                           capture_output=True, timeout=600)
    except Exception:
        pass  # 自愈失败交由上层报错


class VlmClient:
    """单模型 chat/completions 端口（缓存开在 store 实体索引上）。"""

    def __init__(self, cfg: CuaConfig, store: Any = None,
                 http_post: Any = _default_http_post) -> None:
        self._cfg = cfg
        self._store = store  # None = 不缓存（probe 快速模式）
        self._http_post = http_post
        self.api_calls = 0  # 缓存命中等价「零 API」的审计计数

    # ---- HTTP（含自愈，学 rag）----

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {}
        if self._cfg.api_key:
            headers["Authorization"] = f"Bearer {self._cfg.api_key}"
        url = f"{self._cfg.base_url}/chat/completions"
        budget = max(self._cfg.timeout_s,
                     int(body.get("max_tokens", 0) * 0.25) + 60)
        try:
            return await asyncio.to_thread(
                self._http_post, url, headers, body, budget)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            if exc.code == 400 and "unloaded" in detail.lower():
                await asyncio.to_thread(_lms, "load", str(body.get("model", "")))
                try:
                    return await asyncio.to_thread(
                        self._http_post, url, headers, body, budget)
                except urllib.error.HTTPError as exc2:
                    detail = exc2.read().decode("utf-8", "replace")[:300]
            if exc.code == 400 and "image" in detail.lower():
                raise RuntimeError(
                    f"端点拒绝图像输入（模型非视觉？）: {detail}") from exc
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except TimeoutError as exc:
            await asyncio.to_thread(_lms, "reset", str(body.get("model", "")))
            try:
                return await asyncio.to_thread(
                    self._http_post, url, headers, body, budget)
            except TimeoutError:
                raise RuntimeError(
                    f"生成超时（>{budget:.0f}s）——重置模型后仍超时") from exc

    # ---- 缓存（请求哈希 → 实体索引 → CAS 工件）----

    @staticmethod
    def _cache_key(body: dict[str, Any]) -> str:
        canonical = json.dumps({"kind": "cua.chat", "body": body},
                               ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def _cache_get(self, key: str) -> dict[str, Any] | None:
        if self._store is None:
            return None
        hits = await self._store.search_by_entity(
            ENTITY_KEY, key, tenant_id=self._cfg.tenant_id,
            project_id=self._cfg.project_id, include_derived=False)
        for hit in hits:
            if hit.get("kind") != "artifact":
                continue
            raw = await self._store.get_artifact(
                str(hit["ref"]), tenant_id=self._cfg.tenant_id,
                project_id=self._cfg.project_id)
            return json.loads(raw.decode("utf-8"))
        return None

    async def _cache_store(self, key: str, essential: dict[str, Any]) -> None:
        if self._store is None:
            return
        await self._store.save_artifact(
            json.dumps(essential, ensure_ascii=False, sort_keys=True)
            .encode("utf-8"),
            mime="application/json", source="cua.model_call",
            tags={"cua_kind": "model_response"},
            entities={ENTITY_KEY: key},
            tenant_id=self._cfg.tenant_id, project_id=self._cfg.project_id,
        )

    # ---- 生成 ----

    async def generate(self, system: str, prompt: str,
                       images: list[tuple[bytes, str]] | None = None,
                       max_tokens: int | None = None) -> str:
        if self._cfg.no_think:
            prompt = f"{prompt} /no_think"
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for raw, mime in images or []:
            b64 = base64.b64encode(raw).decode("ascii")
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"}})
        body = {
            "model": self._cfg.vlm_model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": content}],
            "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False},
            "max_tokens": max_tokens or self._cfg.max_tokens,
        }
        key = self._cache_key(body)
        cached = await self._cache_get(key)
        if cached is not None:
            return str(cached["content"])
        for attempt in range(2):
            resp = await self._post(body)
            self.api_calls += 1
            choice = resp["choices"][0]
            text = choice["message"].get("content") or ""
            if text.strip():
                await self._cache_store(key, {
                    "content": text,
                    "model": resp.get("model"),
                    "usage": resp.get("usage"),
                    "finish_reason": choice.get("finish_reason"),
                })
                return text
            if attempt == 0 and choice.get("finish_reason") == "length":
                body = {**body, "max_tokens": body["max_tokens"] * 3}
                key = self._cache_key(body)
                continue
            raise RuntimeError(
                "VLM 空 content（reasoning 耗尽 max_tokens？"
                f"finish={choice.get('finish_reason')}）")

    async def ask_json(self, system: str, prompt: str,
                       images: list[tuple[bytes, str]] | None = None,
                       max_tokens: int | None = None) -> dict[str, Any]:
        """生成 + 鲁棒 JSON 提取（首个平衡花括号块；解析失败抛错）。"""
        raw = await self.generate(system, prompt, images, max_tokens)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            raise RuntimeError(f"回答中无 JSON 对象: {raw[:200]!r}")
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"JSON 解析失败（{exc}）: {m.group(0)[:200]!r}") from exc


__all__ = ["VlmClient"]
