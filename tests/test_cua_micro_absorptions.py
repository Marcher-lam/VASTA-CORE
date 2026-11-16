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

from examples.cua.loop import SYSTEM_PROMPT
from examples.cua.revisit import history_lines

from vasta_storage import SqliteStorage

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
