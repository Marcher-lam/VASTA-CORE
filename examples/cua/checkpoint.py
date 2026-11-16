"""VISTA 吸收序④：压缩检查点治理（LoopContext 检查点协议）。

VISTA ``backends/claude/compact_hook.py`` + ``core/session.py`` 三态恢复
语义移植到本仓自有循环：

- **无静默丢失**：上下文预算触线（history 超窗）时，被截断的头部以
  紧凑投影（序③ ``history_lines``）保留在 prompt——替换原
  ``history[-4:]`` 裸滑窗（loop.py 实测隐患）；
- **检查点留痕**：每 ``SAVE_EVERY`` 步将全量历史落 CAS 工件 + 实体
  索引（vlm.py 先例，AD-2 合规面）——事件信封 seq 由 engine
  sequencer 独管，loop 侧不手搓 envelope（不破坏唯一写路径）；
- **边界校验 fail-closed**：活历史与最近检查点前缀不符 →
  ``CheckpointBoundaryError``（VISTA "changed before delivery" /
  forced_termination 同精神）；
- 负载确定性：canonical JSON（无时钟熵——AD-5）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from vasta_storage import DEFAULT_PROJECT, DEFAULT_TENANT

from .revisit import history_lines

CONTEXT_WINDOW = 4  # 全量 JSON 窗口（原 history[-4:] 语义）
SAVE_EVERY = 8      # 每 N 步落检查点
ENTITY_KEY = "cua_loop_checkpoint"


class CheckpointBoundaryError(RuntimeError):
    """活历史与检查点边界不符——fail-closed 终止信号。"""


@dataclass(frozen=True)
class LoopCheckpoint:
    """循环续接检查点：全量历史 + 边界步（最小续接集，无时钟熵）。"""

    run_id: str
    task: str
    answer: str
    mode: str
    boundary_step: int
    history: tuple[dict, ...]

    def as_payload(self) -> bytes:
        doc = {"run_id": self.run_id, "task": self.task,
               "answer": self.answer, "mode": self.mode,
               "boundary_step": self.boundary_step,
               "history": [dict(h) for h in self.history]}
        return json.dumps(doc, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_payload(cls, data: bytes) -> LoopCheckpoint:
        doc = json.loads(data.decode("utf-8"))
        return cls(run_id=doc["run_id"], task=doc["task"],
                   answer=doc["answer"], mode=doc["mode"],
                   boundary_step=doc["boundary_step"],
                   history=tuple(doc["history"]))


def should_checkpoint(steps: int, *, save_every: int = SAVE_EVERY) -> bool:
    """检查点节奏：每 save_every 步一存（steps 从 1 起）。"""
    return steps > 0 and steps % save_every == 0


def context_projection(history: list[dict], *,
                       window: int = CONTEXT_WINDOW) -> str:
    """历史 → prompt 上下文块：窗口内原样 JSON；超窗头部紧凑投影。

    窗口内输出与旧 ``json.dumps(history[-4:])`` 逐字节相同（向后
    兼容）；超窗后模型仍能看到归档头部（无静默丢失）。
    """
    if len(history) <= window:
        return json.dumps(history, ensure_ascii=False)
    archived = history_lines(history, end=len(history) - window)
    return ("已归档步骤（紧凑投影）：\n" + "\n".join(archived)
            + "\n当前窗口（全量）："
            + json.dumps(history[-window:], ensure_ascii=False))


async def save_checkpoint(store: Any, ckpt: LoopCheckpoint, *,
                          tenant_id: str | None = None,
                          project_id: str | None = None) -> str:
    """检查点 → CAS 工件 + 实体索引（run_id:boundary_step 寻址）。"""
    kwargs: dict[str, Any] = {}
    if tenant_id is not None and project_id is not None:
        kwargs = {"tenant_id": tenant_id, "project_id": project_id}
    return await store.save_artifact(
        ckpt.as_payload(), mime="application/json",
        source="cua.loop_checkpoint",
        tags={"cua_kind": "loop_checkpoint"},
        entities={ENTITY_KEY: f"{ckpt.run_id}:{ckpt.boundary_step}"},
        **kwargs)


async def load_checkpoint(store: Any, run_id: str, boundary_step: int, *,
                          tenant_id: str | None = None,
                          project_id: str | None = None,
                          ) -> LoopCheckpoint | None:
    """按 run_id + 边界步取检查点；缺失返回 None（不猜）。

    search_by_entity 作用域必填（fail-closed）——缺省回落存储默认
    作用域（与 save_artifact 默认一致）。
    """
    hits = await store.search_by_entity(
        ENTITY_KEY, f"{run_id}:{boundary_step}",
        tenant_id=tenant_id or DEFAULT_TENANT,
        project_id=project_id or DEFAULT_PROJECT, include_derived=False)
    for hit in hits:
        if hit.get("kind") != "artifact":
            continue
        raw = await store.get_artifact(str(hit["ref"]), tenant_id=tenant_id,
                                       project_id=project_id)
        return LoopCheckpoint.from_payload(raw)
    return None


def validate_boundary(ckpt: LoopCheckpoint, live: list[dict]) -> None:
    """边界一致性：活历史前缀须与检查点归档全等（归档不可变性）。"""
    if len(live) < len(ckpt.history):
        raise CheckpointBoundaryError(
            f"活历史（{len(live)} 步）短于检查点边界"
            f"（{len(ckpt.history)} 步）——状态回退或误用")
    for i, archived in enumerate(ckpt.history):
        if live[i] != archived:
            raise CheckpointBoundaryError(
                f"边界校验失败：活历史 s{live[i].get('step', '?')} 与"
                f"检查点归档 s{archived.get('step', i + 1)} 不符"
                "（前缀漂移）——fail-closed")
