"""系统流清单生成器（Story 12.1，Epic 11 复盘 F3/item-23，G0）。

SYSTEM_STREAMS 手工快照必然漂移——Epic 11 引入 7 个系统流
（delegations/memory/sharing/agent-roles/autonomy/risk-budgets/
edge-stream）全部缺册，与事件类型目录（D1）同型的第二处漂移。
本模块把流清单同样交给代码发射点（同 11.1 catalog_gen 模式）：

- ``collect_stream_names``：AST 扫描 packages/*/src 的系统流声明面——
  ① 名以 ``_RUN``/``_STREAM`` 结尾的字符串常量赋值（各治理模块的
  系统流常量约定：``_DELEGATION_RUN = "delegations"``）；②
  ``EventSequencer(store, "字面量", …)`` 第二位置参字符串字面量；
- ``stream_drift``：发射点集合 vs ``SYSTEM_STREAMS`` 的缺漏/多余；
- ``generate_stream_catalog``：从发射点生成流清单（sorted list——与
  SYSTEM_STREAMS 同形态，可直接回写）；
- 守卫测试（tests/test_stream_catalog_guard.py）锚定零漂移。

设计口径：**只有固定命名（字面量/常量）才是系统流**——用户 Run 的
run_id 以变量传入（如 trajectory 的 ``run_id`` 参数），不属治理/审计
固定流，扫描器天然不捕获（JoinStr/变量均不可见）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

#: 保留声明面：10.7 手收集的在册流，当前无字面量发射面（预留命名——
#: 与目录 _DYNAMIC_SUPPLEMENT 同型的补充表，来源注明）。
_DECLARED_SUPPLEMENT: frozenset[str] = frozenset({
    # schema_registry 10.7 建立时手收集——导入管线/桥接预留命名
    "import", "bridge",
})

#: 排除的路径段（测试/脚本/评审临时物不进清单）。
_EXCLUDE_PARTS = {"tests", "scripts", "examples", ".review-tmp",
                  "__pycache__", "node_modules"}

#: 系统流命名约束（与 EventEnvelope run_id 校验对齐——小写字母/
#: 数字/连字符/下划线；排除路径分隔符形态。注意：envelope 的 run_id
#: 本体只校验 min_length——本约束是流清单自己的治理口径，非 envelope
#: 对齐（评审修复 1-4：注释失实改口）。
_STREAM_NAME_OK = re.compile(r"^[a-z][a-z0-9_-]*$")


def _func_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _streams_of(tree: ast.Module) -> set[str]:
    """单模块的系统流声明面集合。"""
    found: set[str] = set()
    for node in ast.walk(tree):
        # ① *_RUN / *_STREAM 字符串常量（治理模块系统流约定）
        targets: list[str] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            value = node.value
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target,
                                                            ast.Name):
            value = node.value
            targets = [node.target.id]
        if value is not None and isinstance(value, ast.Constant) \
                and isinstance(value.value, str):
            for name in targets:
                if name.endswith("_RUN") or name.endswith("_STREAM"):
                    found.add(value.value)
        # ② EventSequencer(store, "字面量", …)——位置参与 run_id=
        # 关键字两种形态（评审修复 1-2：关键字传参漏扫）
        if isinstance(node, ast.Call) \
                and _func_name(node) == "EventSequencer":
            if len(node.args) >= 2 \
                    and isinstance(node.args[1], ast.Constant) \
                    and isinstance(node.args[1].value, str):
                found.add(node.args[1].value)
            for kw in node.keywords:
                if kw.arg == "run_id" \
                        and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, str):
                    found.add(kw.value.value)
    return {s for s in found if _STREAM_NAME_OK.match(s)}


def _packages_src(root: Path) -> list[Path]:
    base = root / "packages"
    if not base.is_dir():
        return []
    return [p for p in base.glob("*/src") if p.is_dir()]


def collect_stream_names(
    root: str | Path = ".",
) -> set[str]:
    """AST 扫描 packages/*/src 全部 .py 的系统流声明面 → 流名集合。"""
    result: set[str] = set()
    for src_dir in _packages_src(Path(root)):
        for py in src_dir.rglob("*.py"):
            if any(part in _EXCLUDE_PARTS for part in py.parts):
                continue
            try:
                tree = ast.parse(
                    py.read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError):
                continue
            result |= _streams_of(tree)
    return result | _DECLARED_SUPPLEMENT


def stream_drift(
    catalog: tuple[str, ...] | list[str],
    emitted: set[str] | None = None,
    *,
    root: str | Path = ".",
) -> dict[str, list[str]]:
    """注册表 vs 发射点漂移：missing（注册表缺发射的）/ extra（注册表
    有但无发射点——可能是保留声明或已删除）。"""
    if emitted is None:
        emitted = collect_stream_names(root)
    in_catalog = set(catalog)
    return {
        "missing": sorted(emitted - in_catalog),
        "extra": sorted(in_catalog - emitted),
    }


def generate_stream_catalog(
    root: str | Path = ".",
) -> list[str]:
    """从发射点生成流清单快照（sorted——与 SYSTEM_STREAMS 同形态，
    可直接回写）。"""
    return sorted(collect_stream_names(root))


__all__ = ["collect_stream_names", "generate_stream_catalog",
           "stream_drift"]
