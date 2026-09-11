"""事件目录生成器（Story 11.1，Epic 10 复盘 D1，G0）。

从代码发射点自动提取事件类型——手工快照必然漂移（10.7 建立时全量
对拍零缺失、G3-G5 新事件后立刻陈旧）：

- ``collect_emitted_types``：扫描 packages/*/src 的 ``emit("…")`` /
  ``_emit("…")`` / ``sequencer.emit("…", …)`` 字符串字面量调用点；
- ``catalog_drift``：发射点集合 vs ``_EVENT_CATALOG`` 的缺漏/多余；
- ``generate_catalog``：从发射点生成目录（family→sorted 事件集）；
- 守卫测试（tests/test_catalog_guard.py）锚定零漂移。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .envelope import EVENT_FAMILIES

#: 发射调用形态：emit("type.event", …) —— 函数名以 emit 结尾、
#: 首参为字符串字面量。
_EMIT_CALL = re.compile(
    r"""(?:sequencer\.)?\b_?emit\w*\(\s*["']([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)["']""",
    re.IGNORECASE,
)

#: 非字面量发射面的事件类型（动态 f-string / 状态机常量 / 错误码
#: raise 面）——这些类型真实存在于事件流但不在 emit 字面量调用里。
#: 每族注明来源；守卫测试对拍时并入。
_DYNAMIC_SUPPLEMENT: dict[str, set[str]] = {
    # runner: _emit(f"observation.{obs.kind}") 五类观察
    "observation": {"decision", "external", "reset", "transition",
                    "terminal"},
    # runner 状态机 _transition（event_type 常量在调用面）
    "run": {"cancelled", "failed", "paused", "resumed", "started"},
    # model-lab 世界模型桥接（_bookkeeping_stub）
    "world_model": {"suspended", "updated", "validated"},
    # 存储层错误码事件面（artifact.corrupted/not_found 等）
    "artifact": {"corrupted", "not_found"},
    "verification": {"deviated", "passed"},
    "memory": {"note"},
    "action": {"contracted", "takeover_required"},
}


#: 排除的路径段（测试/脚本/评审临时物不进目录）。
_EXCLUDE_PARTS = {"tests", "scripts", "examples", ".review-tmp",
                  "__pycache__", "node_modules"}


def _packages_src(root: Path) -> list[Path]:
    base = root / "packages"
    if not base.is_dir():
        return []
    return [p for p in base.glob("*/src") if p.is_dir()]


def collect_emitted_types(
    root: str | Path = ".",
) -> dict[str, set[str]]:
    """扫描 packages/*/src 全部 .py 文件的发射调用点 → family→事件集。"""
    result: dict[str, set[str]] = {f: set() for f in EVENT_FAMILIES}
    for src_dir in _packages_src(Path(root)):
        for py in src_dir.rglob("*.py"):
            if any(part in _EXCLUDE_PARTS for part in py.parts):
                continue
            try:
                text = py.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for match in _EMIT_CALL.finditer(text):
                event_type = match.group(1)
                family = event_type.split(".", 1)[0]
                if family in result:
                    result[family].add(event_type.split(".", 1)[1])
    for family, events in _DYNAMIC_SUPPLEMENT.items():
        result.setdefault(family, set()).update(events)
    return result


def catalog_drift(
    catalog: dict[str, Any],
    emitted: dict[str, set[str]] | None = None,
    *, root: str | Path = ".",
) -> dict[str, list[str]]:
    """目录 vs 发射点漂移：missing（目录缺发射的）/ extra（目录有
    但无发射点——可能是动态类型或已删除）。"""
    if emitted is None:
        emitted = collect_emitted_types(root)
    drift: dict[str, list[str]] = {"missing": [], "extra": []}
    for family in EVENT_FAMILIES:
        in_catalog = set(catalog.get(family) or [])
        in_code = emitted.get(family, set())
        for event in sorted(in_code - in_catalog):
            drift["missing"].append(f"{family}.{event}")
        for event in sorted(in_catalog - in_code):
            drift["extra"].append(f"{family}.{event}")
    return drift


def generate_catalog(
    root: str | Path = ".",
) -> dict[str, list[str]]:
    """从发射点生成目录快照（family→sorted list——与 event_catalog
    同形态，可直接回写 _EVENT_CATALOG）。"""
    emitted = collect_emitted_types(root)
    return {family: sorted(events)
            for family, events in sorted(emitted.items())}


__all__ = ["catalog_drift", "collect_emitted_types", "generate_catalog"]
