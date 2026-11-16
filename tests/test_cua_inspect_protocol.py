"""Story va-7（边界清偿③）：inspect 请求进决策协议（va-3 遗留收口）。

模型侧回看闭环：决策 JSON 可选 ``inspect`` 字段——不确定时只发
inspect 不发 button，循环裁剪当前场景指定 mark 区域（NEAREST 放大）
作为额外图像回喂下一轮决策。VISTA ``inspect`` 语义落到本仓决策
协议的形态：区域按 **mark 编号**指定（模型既有词汇），pt×scale 换算
（va-3 的 Region.from_pt）。
"""

from __future__ import annotations

from examples.cua.loop import SYSTEM_PROMPT, _inspect_prompt_note, _parse_inspect

MARKS = {27: {"x_pt": 10.0, "y_pt": 20.0, "w_pt": 30.0, "h_pt": 30.0},
         5: {"x_pt": 0.0, "y_pt": 0.0, "w_pt": 40.0, "h_pt": 40.0}}


# ---- AC1：协议在提示词里 ----

def test_system_prompt_documents_inspect() -> None:
    assert '"inspect"' in SYSTEM_PROMPT
    assert "mark" in SYSTEM_PROMPT


# ---- AC2：解析与校验（mark 词汇 → Region 视图） ----

def test_parse_valid_inspect_request() -> None:
    views, err = _parse_inspect(
        [{"mark": 27, "why": "看不清数字牌"}], MARKS, scale=2.0)
    assert err is None and len(views) == 1
    label, region = views[0]
    assert "27" in label and "看不清" in label
    assert (region.x, region.y, region.width, region.height) == (20, 40, 60, 60)


def test_parse_caps_two_views() -> None:
    req = [{"mark": m, "why": ""} for m in (27, 5, 27)]
    views, err = _parse_inspect(req, MARKS, scale=1.0)
    assert err is None and len(views) == 2  # 超出截断


def test_parse_unknown_mark_feedback() -> None:
    views, err = _parse_inspect([{"mark": 999}], MARKS, scale=1.0)
    assert views == [] and err is not None and "999" in err


def test_parse_no_marks_memory_mode() -> None:
    views, err = _parse_inspect([{"mark": 1}], {}, scale=1.0)
    assert views == [] and err is not None and "memory" in err


def test_parse_ignores_malformed_entries() -> None:
    views, err = _parse_inspect(
        [{"mark": "abc"}, {"mark": 5}], MARKS, scale=1.0)
    assert err is None and len(views) == 1  # 坏条目跳过，好条目保留


# ---- AC3：回喂提示注记 ----

def test_inspect_prompt_note_lists_labels() -> None:
    note = _inspect_prompt_note([("mark27:看不清", object()),
                                 ("mark5:", object())])
    assert "mark27" in note and "mark5" in note
    assert "放大" in note


def test_inspect_prompt_note_empty_is_none() -> None:
    assert _inspect_prompt_note([]) is None
