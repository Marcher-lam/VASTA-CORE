"""坑位 #29 同源副本修复（rag/cloud.py）：VLM 硬总超时。

vlm.py 当初照抄 rag/cloud.py（其文件头自述）——#29 修复（efe56ff）
只修了学生，老师仍带洞：urlopen(timeout=600) 对滴流免疫（LM Studio
swap 龟速——连接 ESTABLISHED、分钟/token 爬行，字节间隔 < socket
timeout 永不触发）→ RAG 长评测会以与 CUA run1 完全相同的方式永久
挂死。本测试锁同一补丁形态：wait_for 硬总限拉回。
"""

from __future__ import annotations

import dataclasses
import threading

import examples.rag.cloud as cloud_mod
import pytest
from examples.rag.cloud import CloudClient
from examples.rag.config import RagConfig


def _client(http_post, timeout_s: int) -> CloudClient:
    cfg = dataclasses.replace(RagConfig(), base_url="http://127.0.0.1:1/v1",
                              timeout_s=timeout_s)
    return CloudClient(cfg, store=None, http_post=http_post)


async def test_trickling_http_killed_by_hard_deadline(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cloud_mod, "_GEN_FLOOR_S", 1)
    monkeypatch.setattr(cloud_mod, "_HARD_MARGIN_S", 1)
    release = threading.Event()

    def trickling_post(url, headers, body, timeout_s):  # noqa: ANN001
        release.wait(30)  # 连接 ESTABLISHED、永不回——测试放行后线程退出

    vlm = _client(trickling_post, timeout_s=2)  # budget=max(2, 7)=7 → hard=8s
    try:
        with pytest.raises(RuntimeError, match="硬总超时"):
            await vlm.generate("s", "p", max_tokens=8)
    finally:
        release.set()


async def test_hard_deadline_spares_normal_calls(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cloud_mod, "_GEN_FLOOR_S", 1)
    monkeypatch.setattr(cloud_mod, "_HARD_MARGIN_S", 1)

    def fast_post(url, headers, body, timeout_s):  # noqa: ANN001
        return {"choices": [{"message": {"content": "ok"},
                             "finish_reason": "stop"}],
                "usage": {}, "model": "fake"}

    vlm = _client(fast_post, timeout_s=30)
    out = await vlm.generate("s", "p", max_tokens=8)
    assert out["content"] == "ok"
