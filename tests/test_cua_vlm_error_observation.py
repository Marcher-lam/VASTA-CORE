"""Story va-1（吸收方案 §七 序①）：VISTA「错误即观测」。

VLM 坏 JSON 不盲重试——错误观测回喂下一轮 prompt，模型自我纠正。
根因（Phase 4 基线「VLM 坏 JSON 重试耗尽」的机制层）：loop 盲重试
（prompt 不变）× vlm 响应缓存（同 body 同 key）→ 二次请求命中缓存
取回同一份坏文本 → 必然二连炸。修法（VISTA ``core/session.py`` 模式：
``{"ok": False, "error": …}`` 回喂而非抛完即弃）：错误与原文片段
作为「系统观测」注入 prompt——模型可见，且 prompt 变化天然避开
坏响应的缓存命中。
"""

from __future__ import annotations

import pytest
from examples.cua.config import CuaConfig
from examples.cua.loop import _memory_prompt, _vision_prompt, _vlm_error_note
from examples.cua.vlm import VlmClient, VlmFormatError

OBS_MARKER = "系统观测（上一轮输出问题）"


def _client(reply_text: str) -> VlmClient:
    """单次应答恒为 reply_text 的假 VLM（无缓存，隔离存储）。"""

    def fake_post(url, headers, body, timeout_s):  # noqa: ANN001
        return {"choices": [{"message": {"content": reply_text},
                             "finish_reason": "stop"}],
                "model": "fake", "usage": {}}

    return VlmClient(CuaConfig(), store=None, http_post=fake_post)


# ---- AC1：解析失败抛类型化错误，raw 原文随行 ----

async def test_no_json_raises_format_error_with_raw() -> None:
    raw = "我认为应该按 7（推理过程，未输出 JSON）"
    with pytest.raises(VlmFormatError) as ei:
        await _client(raw).ask_json("sys", "prompt")
    assert ei.value.raw == raw


async def test_bad_json_raises_format_error_with_raw() -> None:
    raw = '{"button": "7", "mark": 3,}'  # 尾逗号——正则能捞到但解析失败
    with pytest.raises(VlmFormatError) as ei:
        await _client(raw).ask_json("sys", "prompt")
    assert ei.value.raw == raw


async def test_good_json_still_returns_dict() -> None:
    out = await _client('嗯好的 {"button": "7", "mark": 3}').ask_json(
        "sys", "prompt")
    assert out == {"button": "7", "mark": 3}


# ---- AC2：错误观测构造（错误原因 + 原文截断 + 修正指令） ----

def test_error_note_contains_reason_and_capped_raw() -> None:
    note = _vlm_error_note(VlmFormatError("JSON 解析失败（尾逗号）",
                                          raw="A" * 500))
    assert "JSON 解析失败" in note
    assert note.count("A") <= 160  # 原文片段截断，不撑爆上下文
    assert "JSON" in note  # 修正指令在场


def test_error_note_marks_truncation() -> None:
    note = _vlm_error_note(VlmFormatError("无 JSON", raw="X" * 500))
    assert "…" in note  # 截断对模型可见


# ---- AC3：观测注入两模式 prompt；无错不渲染 ----

def test_vision_prompt_renders_observation() -> None:
    p = _vision_prompt("任务", "12", [], None,
                       vlm_error="上次：{'button'…尾逗号")
    assert OBS_MARKER in p and "尾逗号" in p


def test_vision_prompt_without_error_is_clean() -> None:
    assert OBS_MARKER not in _vision_prompt("任务", "12", [], None)


def test_memory_prompt_renders_observation() -> None:
    p = _memory_prompt("任务", "12", [], vlm_error="bad {")
    assert OBS_MARKER in p and "bad {" in p


def test_memory_prompt_without_error_is_clean() -> None:
    assert OBS_MARKER not in _memory_prompt("任务", "12", [])


# ---- va-10（坑位 #29）：硬总超时——socket 超时对滴流免疫的补丁 ----

async def test_trickling_http_killed_by_hard_deadline(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """对端收下请求后滴流/挂死（LM Studio swap 龟速实测形态）——
    socket 超时永不触发，硬总限时必须把 generate 拉回来。"""
    import dataclasses
    import threading

    import examples.cua.vlm as vlm_mod
    from examples.cua.config import CuaConfig

    monkeypatch.setattr(vlm_mod, "_GEN_FLOOR_S", 1)
    monkeypatch.setattr(vlm_mod, "_HARD_MARGIN_S", 1)
    release = threading.Event()

    def trickling_post(url, headers, body, timeout_s):  # noqa: ANN001
        release.wait(30)  # 连接 ESTABLISHED、永不回——测试放行后线程退出

    cfg = dataclasses.replace(CuaConfig(), timeout_s=1)
    vlm = VlmClient(cfg, store=None, http_post=trickling_post)
    try:
        with pytest.raises(RuntimeError, match="硬总超时"):
            await vlm.generate("s", "p", max_tokens=8)
    finally:
        release.set()


async def test_hard_deadline_spares_normal_calls() -> None:
    from examples.cua.config import CuaConfig

    def fast_post(url, headers, body, timeout_s):  # noqa: ANN001
        return {"choices": [{"message": {"content": '{"ok": 1}'},
                             "finish_reason": "stop"}]}

    vlm = VlmClient(CuaConfig(), store=None, http_post=fast_post)
    assert "1" in await vlm.generate("s", "p", max_tokens=8)
