"""事件目录生成器（Story 11.1，Epic 10 复盘 D1，G0）。

从代码发射点自动提取事件类型——手工快照必然漂移（10.7 建立时全量
对拍零缺失、G3-G5 新事件后立刻陈旧）：

- ``collect_emitted_types``：AST 扫描 packages/*/src 的 ``emit("…")``
  / ``_emit("…")`` / ``sequencer.emit("…")`` 及 emit 前缀发射包装
  （如 ``emit_world_model_event``）的调用点；
- ``catalog_drift``：发射点集合 vs ``_EVENT_CATALOG`` 的缺漏/多余；
- ``generate_catalog``：从发射点生成目录（family→sorted 事件集）；
- 守卫测试（tests/test_catalog_guard.py）锚定零漂移。

Epic 11 评审修复（盲审 H1 / 边界 G-1/G-2）：正则文本扫描改为 AST
扫描——

- 注释/docstring/长字符串中的 ``emit("…")`` 文本不再误入目录
  （假阳性），注释掉的真实发射点不再被计数（假阴性——删除发射
  后目录条目立即落入 ``extra`` 被守卫抓出）；
- ``emit("a.x" if cond else "b.y", …)`` 三元发射**双支**全捕获
  （sharing.py 的 claim/artifact 分支曾是正则盲区）；
- emit 前缀包装函数（首个参数非事件类型的发射器）按全部位置参数
  扫描——``world_model.meta_decision`` 等包装发射面入册。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from .envelope import EVENT_FAMILIES

#: 事件类型形态：family.event（各段小写字母/数字/下划线）。
_EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")

#: 家族前缀集合（扫描结果按此过滤——封闭集外的类型不进目录）。
_FAMILY_SET = frozenset(EVENT_FAMILIES)


def _func_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _is_emitter(name: str) -> bool:
    """发射函数名：emit / _emit 及 emit 前缀发射包装。

    精确等值匹配 emit（首参即事件类型）；``emit*``/``_emit*`` 前缀
    视为发射包装（如 emit_world_model_event——事件类型在后续位置
    参数）。AST 精确到函数名，注释/docstring 中的同名文本不命中。
    """
    return name == "emit" or name.startswith("emit") \
        or name.startswith("_emit")


def _string_types_in(expr: ast.AST) -> set[str]:
    """表达式子树内的事件类型形态字符串常量（JoinedStr 段除外——
    f-string 片段不是完整类型名，动态面走 _DYNAMIC_SUPPLEMENT）。"""
    found: set[str] = set()

    class _Visitor(ast.NodeVisitor):
        def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
            return  # f-string 常量段跳过

        def visit_Constant(self, node: ast.Constant) -> None:
            value = node.value
            if isinstance(value, str) and _EVENT_TYPE_RE.match(value):
                found.add(value)

    _Visitor().visit(expr)
    return found


def _emitted_types_of(tree: ast.Module) -> set[str]:
    """单模块全部发射调用点的事件类型集合。"""
    emitted: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _func_name(node)
        if name is None or not _is_emitter(name):
            continue
        if name == "emit":
            # 首参即事件类型（含 IfExp 双支/嵌套表达式）
            if node.args:
                emitted |= _string_types_in(node.args[0])
            continue
        # 发射包装（store 等在前）——扫描全部位置参数
        for arg in node.args:
            emitted |= _string_types_in(arg)
    return {t for t in emitted if t.split(".", 1)[0] in _FAMILY_SET}


#: 非字面量发射面的事件类型（动态 f-string / 状态机常量 / 返回值
#: 构造 / 错误码 raise 面）——这些类型真实存在于事件流但不在 emit
#: 字面量调用里。每族注明来源；守卫测试对拍时并入。
_DYNAMIC_SUPPLEMENT: dict[str, set[str]] = {
    # runner: _emit(f"observation.{obs.kind}") 五类观察
    "observation": {"decision", "external", "reset", "transition",
                    "terminal"},
    # runner 状态机 _transition（event_type 常量在调用面）
    "run": {"cancelled", "failed", "paused", "resumed", "started"},
    # model-lab 世界模型桥接/生命周期（变量发射面）
    "world_model": {"suspended", "updated", "validated",
                    # governance/versioning._event_type_of("model")
                    # 返回值发射（publish_policy_snapshot 同路）
                    "published"},
    # governance/versioning._event_type_of("policy") 返回值发射
    "artifact": {"corrupted", "not_found", "published"},
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
    """AST 扫描 packages/*/src 全部 .py 发射调用点 → family→事件集。"""
    result: dict[str, set[str]] = {f: set() for f in EVENT_FAMILIES}
    for src_dir in _packages_src(Path(root)):
        for py in src_dir.rglob("*.py"):
            if any(part in _EXCLUDE_PARTS for part in py.parts):
                continue
            try:
                tree = ast.parse(
                    py.read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError):
                continue
            for event_type in _emitted_types_of(tree):
                family, _, event = event_type.partition(".")
                result[family].add(event)
    for family, events in _DYNAMIC_SUPPLEMENT.items():
        result.setdefault(family, set()).update(events)
    return result


def catalog_drift(
    catalog: dict[str, Any],
    emitted: dict[str, set[str]] | None = None,
    *,
    root: str | Path = ".",
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
