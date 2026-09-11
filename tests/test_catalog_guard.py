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
