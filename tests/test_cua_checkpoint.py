"""Story va-4（吸收方案 §七 序④）：压缩检查点治理（LoopContext 协议）。

VISTA ``compact_hook.py`` + ``core/session.py`` 三态恢复语义移植到本仓
自有循环：
- **无静默丢失**：上下文预算触线（history 超窗）时，被截断的头部以
  紧凑投影（序③ history_lines）保留在 prompt 中——替换原
  ``history[-4:]`` 裸滑窗；
- **检查点留痕**：每 SAVE_EVERY 步将全量历史落 CAS 工件 + 实体索引
  （vlm.py 先例，AD-2 合规面——事件信封 seq 由 engine sequencer
  独管，loop 侧不手搓）；
- **边界校验 fail-closed**：活历史与最近检查点前缀不符 → 抛
  CheckpointBoundaryError（VISTA "guide changed before delivery" /
  forced_termination 同精神）。
"""

from __future__ import annotations

import json

import pytest
from examples.cua.checkpoint import (
    CheckpointBoundaryError,
    LoopCheckpoint,
    context_projection,
    load_checkpoint,
    save_checkpoint,
    should_checkpoint,
    validate_boundary,
)

from vasta_storage import SqliteStorage


def _hist(n: int) -> list[dict]:
    return [{"step": i + 1, "button": str(i + 1), "mark": i + 1,
             "expect": f"display={i + 1}", "display_after": str(i + 1),
             "verified": True} for i in range(n)]


def _ckpt(n: int, **kw: object) -> LoopCheckpoint:
    return LoopCheckpoint(run_id="run-x", task="t", answer="6", mode="vision",
                          boundary_step=n, history=tuple(_hist(n)), **kw)


# ---- AC1：上下文投影（窗口内原样；超窗归档头部紧凑保留） ----

def test_projection_short_history_unchanged() -> None:
    h = _hist(3)
    assert context_projection(h) == json.dumps(h, ensure_ascii=False)


def test_projection_archives_head_beyond_window() -> None:
    h = _hist(6)
    out = context_projection(h, window=4)
    assert "已归档" in out and "s1" in out and "s2" in out  # 头部紧凑行
    assert json.dumps(h[-4:], ensure_ascii=False) in out    # 窗口全量 JSON
    assert '"step": 6' in out                               # 窗口含最新步
    assert "s6" not in out.replace('"step": 6', "")          # 紧凑行止于 s2


# ---- AC2：检查点触发节奏 ----

def test_should_checkpoint_rhythm() -> None:
    assert not should_checkpoint(0)
    assert not should_checkpoint(7)
    assert should_checkpoint(8)
    assert should_checkpoint(16)


# ---- AC3：负载确定性 + 往返 ----

def test_payload_deterministic_and_roundtrip() -> None:
    a, b = _ckpt(5), _ckpt(5)
    assert a.as_payload() == b.as_payload()  # 同构造同字节（无时钟熵）
    assert LoopCheckpoint.from_payload(a.as_payload()) == a


def test_payload_is_json() -> None:
    data = json.loads(_ckpt(2).as_payload())
    assert data["boundary_step"] == 2 and len(data["history"]) == 2


# ---- AC4：CAS 留痕（保存/检索/缺失） ----

async def test_save_load_roundtrip(tmp_path) -> None:
    store = SqliteStorage(tmp_path / "s")
    ckpt = _ckpt(8)
    ref = await save_checkpoint(store, ckpt)
    assert len(ref) == 64  # sha256 hex（CAS 寻址）
    loaded = await load_checkpoint(store, "run-x", 8)
    assert loaded == ckpt


async def test_load_missing_returns_none(tmp_path) -> None:
    store = SqliteStorage(tmp_path / "s")
    assert await load_checkpoint(store, "run-x", 8) is None


async def test_checkpoint_isolated_by_boundary(tmp_path) -> None:
    store = SqliteStorage(tmp_path / "s")
    await save_checkpoint(store, _ckpt(8))
    await save_checkpoint(store, _ckpt(16))
    assert (await load_checkpoint(store, "run-x", 16)).boundary_step == 16
    assert (await load_checkpoint(store, "run-x", 8)).boundary_step == 8


# ---- AC5：边界校验 fail-closed ----

def test_validate_boundary_prefix_match_ok() -> None:
    validate_boundary(_ckpt(8), _hist(10))  # 前缀全等 → 通过


def test_validate_boundary_divergence_raises() -> None:
    live = _hist(10)
    live[1]["button"] = "MUTATED"
    with pytest.raises(CheckpointBoundaryError, match="s2"):
        validate_boundary(_ckpt(8), live)


def test_validate_boundary_short_history_raises() -> None:
    with pytest.raises(CheckpointBoundaryError, match="短于"):
        validate_boundary(_ckpt(8), _hist(3))
