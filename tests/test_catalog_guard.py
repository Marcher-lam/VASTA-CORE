"""Story 11.1：事件目录守卫（Epic 10 复盘 D1，G0）。

目录 vs 代码发射点零漂移——CI 级守卫防再次陈旧。
"""

from __future__ import annotations

from pathlib import Path

from vasta_protocols.catalog_gen import (
    catalog_drift,
    collect_emitted_types,
    generate_catalog,
)
from vasta_protocols.envelope import EVENT_FAMILIES

ROOT = Path(__file__).resolve().parent.parent


class TestCatalogGuard:
    def test_zero_drift(self) -> None:
        """AC：目录与发射点零漂移（missing/extra 双向空）。"""
        from vasta_protocols.schema_registry import _EVENT_CATALOG

        drift = catalog_drift(_EVENT_CATALOG, root=ROOT)
        assert drift == {"missing": [], "extra": []}, (
            f"目录漂移：缺 {drift['missing']}，多 {drift['extra']}"
            "——运行 generate_catalog() 回写 _EVENT_CATALOG")

    def test_generated_catalog_matches_current(self) -> None:
        """生成器输出与现行目录逐族一致。"""
        from vasta_protocols.schema_registry import _EVENT_CATALOG

        generated = generate_catalog(ROOT)
        for family in EVENT_FAMILIES:
            assert generated.get(family, []) == sorted(
                _EVENT_CATALOG.get(family) or []), family

    def test_emitted_types_cover_all_families(self) -> None:
        """每个族至少有发射点或补充面（空族=episode 显式豁免）。"""
        emitted = collect_emitted_types(ROOT)
        for family in EVENT_FAMILIES:
            if family == "episode":
                continue  # 声明保留的空族
            assert emitted.get(family), f"族 {family} 无任何事件面"

    def test_drift_detects_missing(self) -> None:
        """守卫真实工作：删目录一条 → missing 检出。"""
        from vasta_protocols.schema_registry import _EVENT_CATALOG

        broken = {f: set(v) for f, v in _EVENT_CATALOG.items()}
        broken["run"].discard("created")
        drift = catalog_drift(broken, root=ROOT)
        assert "run.created" in drift["missing"]

    def test_drift_detects_extra(self) -> None:
        from vasta_protocols.schema_registry import _EVENT_CATALOG

        bloated = {f: set(v) for f, v in _EVENT_CATALOG.items()}
        bloated["run"].add("ghost_event")
        drift = catalog_drift(bloated, root=ROOT)
        assert "run.ghost_event" in drift["extra"]


class TestKnownLiveEvents:
    """Epic 11 评审修复（盲审 H1）：已知活事件白名单——不依赖扫描器
    视野的独立断言（三元发射/包装发射/注释盲区曾是正则的三个洞）。"""

    def test_conditional_and_wrapper_emits_in_catalog(self) -> None:
        """sharing.py 三元发射双支 + meta.py 包装发射 + versioning
        返回值发射面——全部入册。"""
        from vasta_protocols.schema_registry import _EVENT_CATALOG

        for event_type in (
            "artifact.shared", "artifact.shared_revoked",
            "artifact.published", "world_model.published",
            "world_model.meta_decision",
            # AST 扫描新抓获的 noqa 注释后发射面（9.x 遗漏）
            "run.takeover", "run.control_released",
            "run.deviation_context",
        ):
            family, _, event = event_type.partition(".")
            assert event in _EVENT_CATALOG.get(family, set()), event_type

    def test_scanner_captures_ifexp_both_branches(self) -> None:
        """三元发射双支全捕获（sharing 的 claim/artifact 分支）。"""
        emitted = collect_emitted_types(ROOT)
        assert "shared" in emitted["artifact"]
        assert "shared" in emitted["claim"]

    def test_scanner_ignores_comments_and_docstrings(self) -> None:
        """注释/docstring 中的 emit 文本不进目录（假阳性根治）。"""
        import ast as ast_mod

        from vasta_protocols.catalog_gen import _emitted_types_of

        # docstring 内的 emit 示例 + 注释掉的发射——AST 均不可见
        source = (
            '"""示例：await seq.emit("claim.fake_from_doc", {})"""\n'
            "# await seq.emit('run.fake_from_comment', {})\n"
            'async def f(seq):\n'
            '    await seq.emit("run.real_event", {})\n'
        )
        emitted = _emitted_types_of(ast_mod.parse(source))
        assert emitted == {"run.real_event"}

    def test_scanner_flags_commented_out_emit_as_extra(self) -> None:
        """真实发射被注释掉 → 目录条目落入 extra（假阴性根治）。"""
        import ast as ast_mod

        from vasta_protocols.catalog_gen import _emitted_types_of

        live = _emitted_types_of(ast_mod.parse(
            'async def f(seq):\n'
            '    await seq.emit("run.legacy_removed", {})\n'))
        dead = _emitted_types_of(ast_mod.parse(
            'async def f(seq):\n'
            '    # await seq.emit("run.legacy_removed", {})\n'
            '    return None\n'))
        assert "run.legacy_removed" in live
        assert "run.legacy_removed" not in dead

    def test_scanner_captures_wrapper_emission(self) -> None:
        """emit 前缀包装（首参 store）按全部位置参数扫描。"""
        import ast as ast_mod

        from vasta_protocols.catalog_gen import _emitted_types_of

        source = (
            'async def f(store):\n'
            '    await emit_world_model_event(\n'
            '        store, "world_model.meta_decision", {})\n'
        )
        assert _emitted_types_of(ast_mod.parse(source)) == {
            "world_model.meta_decision"}
