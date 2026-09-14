"""Story 12.1：系统流清单守卫（Epic 11 复盘 F3/item-23，G0）。

SYSTEM_STREAMS vs 代码发射点零漂移——CI 级守卫防再次陈旧
（同 11.1 事件目录守卫模式）。
"""

from __future__ import annotations

import ast
from pathlib import Path

from vasta_protocols.stream_catalog_gen import (
    _streams_of,
    collect_stream_names,
    generate_stream_catalog,
    stream_drift,
)

ROOT = Path(__file__).resolve().parent.parent


class TestStreamCatalogGuard:
    def test_zero_drift(self) -> None:
        """AC：注册表与发射点零漂移（missing/extra 双向空）。"""
        from vasta_protocols.schema_registry import SYSTEM_STREAMS

        drift = stream_drift(SYSTEM_STREAMS, root=ROOT)
        assert drift == {"missing": [], "extra": []}, (
            f"流清单漂移：缺 {drift['missing']}，多 {drift['extra']}"
            "——运行 generate_stream_catalog() 回写 SYSTEM_STREAMS")

    def test_generated_matches_current(self) -> None:
        """AC：生成器输出与现行注册表同形态（sorted 逐项一致——
        可一键回写）。"""
        from vasta_protocols.schema_registry import SYSTEM_STREAMS

        assert generate_stream_catalog(ROOT) == sorted(SYSTEM_STREAMS)

    def test_epic11_streams_registered(self) -> None:
        """AC：Epic 11 复盘点名的 7 个缺失流全部入册（独立白名单
        断言——不依赖扫描器视野）。"""
        from vasta_protocols.schema_registry import SYSTEM_STREAMS

        for stream in ("delegations", "memory", "sharing", "agent-roles",
                       "autonomy", "risk-budgets", "edge-stream"):
            assert stream in SYSTEM_STREAMS, stream

    def test_drift_detects_missing(self) -> None:
        """守卫真实工作：注册表删一条 → missing 检出。"""
        from vasta_protocols.schema_registry import SYSTEM_STREAMS

        broken = tuple(s for s in SYSTEM_STREAMS if s != "billing")
        drift = stream_drift(broken, root=ROOT)
        assert "billing" in drift["missing"]

    def test_drift_detects_extra(self) -> None:
        from vasta_protocols.schema_registry import SYSTEM_STREAMS

        bloated = (*SYSTEM_STREAMS, "ghost-stream")
        drift = stream_drift(bloated, root=ROOT)
        assert "ghost-stream" in drift["extra"]


class TestScannerSurface:
    """扫描器行为锚定（AST 口径——注释/变量/f-string 不可见）。"""

    def test_run_constant_captured(self) -> None:
        """治理模块约定：*_RUN/*_STREAM 字符串常量即系统流声明。"""
        tree = ast.parse('_DELEGATION_RUN = "delegations"\n')
        assert _streams_of(tree) == {"delegations"}

    def test_annotated_run_constant_captured(self) -> None:
        tree = ast.parse('_RUN: str = "edge-stream"\n')
        assert _streams_of(tree) == {"edge-stream"}

    def test_sequencer_literal_captured(self) -> None:
        """EventSequencer 第二位置参字面量捕获。"""
        tree = ast.parse(
            'EventSequencer(store, "evaluation", tenant_id="t")\n')
        assert _streams_of(tree) == {"evaluation"}

    def test_variable_run_id_not_captured(self) -> None:
        """用户 Run 的 run_id 以变量传入——不属系统流（设计口径：
        只有固定命名才是治理/审计流）。f-string 同样不可见。"""
        tree = ast.parse(
            "async def emit(store, run_id):\n"
            "    seq = EventSequencer(store, run_id)\n"
            "    await seq.emit('run.created', {})\n")
        assert _streams_of(tree) == set()

    def test_commented_declaration_not_captured(self) -> None:
        """注释掉的流声明不可见（删除流 → extra 检出的前提）。"""
        tree = ast.parse('# _GHOST_RUN = "ghost"\n')
        assert _streams_of(tree) == set()

    def test_stream_name_shape_enforced(self) -> None:
        """非流命名形态（路径分隔符/大写）不入清单。"""
        tree = ast.parse('_BAD_RUN = "../escape"\n_UPPER_RUN = "Bad"\n')
        assert _streams_of(tree) == set()

    def test_supplement_declared_streams_included(self) -> None:
        """10.7 手收集的保留声明（import/bridge）经补充表入册。"""
        emitted = collect_stream_names(ROOT)
        assert {"import", "bridge"} <= emitted
