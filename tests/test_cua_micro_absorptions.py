"""Story va-6（吸收方案 §七 序⑥）：G/H 微吸收。

- **G prompt 纪律**（VISTA ``prompts/claude.md``「动作前简述预期、
  动作后报告全部变化含意外」）：SYSTEM_PROMPT 增可选 ``note`` 字段
  纪律——模型 ex-ante 预期落 history（``model_expect``），与核验器
  事后裁决（``verified``）形成同一条历史里的前后对照（审计面）；
  history_lines 投影渲染「预期：」。
- **H 权限位**（VISTA artifacts.py 帧 chmod 0o400）：CAS 落盘后
  工件置只读——防篡改位（存储层已有 exists→字节校验分支，幂等
  重复存不受影响）。
"""

from __future__ import annotations

import stat

from examples.cua.loop import (
    SYSTEM_PROMPT,
    _mark_mismatch_feedback,
    _unavailable_feedback,
)
from examples.cua.revisit import history_lines

from vasta_storage import SqliteStorage

# ---- va-8：闸拒活锁修复（集成 run #1 发现）——反馈带次数与候选，
# 每次 prompt 变化避开响应缓存（与 va-1 同族根因：同 prompt=同缓存=同答案） ----

def test_unavailable_feedback_carries_attempt_and_candidates() -> None:
    fb = _unavailable_feedback("AC", {"1", "7", "=", "AC×"}, attempts=2)
    assert "第 2 次" in fb
    assert "可用按钮" in fb and "7" in fb
    assert "AC" in fb.replace("AC×", "") or "AC×" in fb  # 候选清单在场


def test_unavailable_feedback_changes_per_attempt() -> None:
    a = _unavailable_feedback("AC", {"1"}, attempts=1)
    b = _unavailable_feedback("AC", {"1"}, attempts=2)
    assert a != b  # prompt 逐次变化 → 缓存键逐次变化 → 真重采样


def test_mark_mismatch_feedback_carries_attempt() -> None:
    fb = _mark_mismatch_feedback("7", 5, "4", attempts=3)
    assert "第 3 次" in fb and "5" in fb and "4" in fb


# ---- G：ex-ante 预期纪律 ----

def test_system_prompt_carries_note_discipline() -> None:
    assert '"note"' in SYSTEM_PROMPT
    assert "预期" in SYSTEM_PROMPT


def test_history_lines_renders_model_expect() -> None:
    h = [{"step": 1, "button": "7", "mark": 3, "expect": "display=7",
          "model_expect": "显示屏应变为 7"}]
    assert "预期:显示屏应变为 7" in history_lines(h)[0]


def test_history_lines_without_model_expect_unchanged() -> None:
    h = [{"step": 1, "button": "7", "mark": 3, "expect": "display=7"}]
    assert "预期:" not in history_lines(h)[0]


# ---- H：CAS 工件只读位 ----

async def test_cas_blob_is_readonly(tmp_path) -> None:
    store = SqliteStorage(tmp_path / "s")
    sha = await store.save_artifact(b"evidence-bytes", mime="image/png")
    blob = tmp_path / "s" / "objects" / sha[:2] / sha
    assert stat.S_IMODE(blob.stat().st_mode) == 0o400  # r--------


async def test_duplicate_save_after_readonly_still_ok(tmp_path) -> None:
    store = SqliteStorage(tmp_path / "s")
    first = await store.save_artifact(b"evidence-bytes", mime="image/png")
    second = await store.save_artifact(b"evidence-bytes", mime="image/png")
    assert first == second  # 幂等分支（读校验）不受只读位影响


# ---- 坑位 #25 族第三层（va-10）：按钮决策层字形归一 ----

def test_button_glyph_normalization_family() -> None:
    from examples.cua.loop import _normalize_button

    assert _normalize_button("-") == "−"    # ASCII → 数学减号
    assert _normalize_button("*") == "×"
    assert _normalize_button("/") == "÷"
    assert _normalize_button("C") == "AC"   # 既有惯例保留
    assert _normalize_button("7") == "7"    # 数字不动
    assert _normalize_button("−") == "−"    # 已合法不动


# ---- va-11：种子偏移（睡眠事故后 seed-9 补齐通道） ----

def test_seed_indices_offset() -> None:
    from examples.cua.seeds import _seed_indices

    assert _seed_indices(0, 10) == list(range(10))
    assert _seed_indices(9, 1) == [9]     # 单补第 9 颗
    assert _seed_indices(5, 3) == [5, 6, 7]


# ---- 坑位 #26 族第四层（va-12）：loop 历史快检的字形归一 ----

def test_history_quick_check_normalizes_minus() -> None:
    from examples.cua.loop import _step_verified

    # VM 屏值 ASCII '-'（#25），期望 U+2212——引擎核验器 #26 已归一，
    # loop 自己的快检漏了（run5 sub/mix 崩塌根因：verifier 3✓ 全过
    # 而快检误判 → 假恢复指令带崩模型）
    assert _step_verified("display_contains=−", "90-") is True
    assert _step_verified("display=75", "75") is True
    assert _step_verified("display=76", "75") is False
