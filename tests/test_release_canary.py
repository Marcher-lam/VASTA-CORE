"""Story 9.6：资产发布灰度与回滚（FR-065，G3）。

状态机 candidate→testing→shadow→canary→active(+rolled_back)；
回滚恢复前 active；影子对比；灰度比例可配。
"""

from __future__ import annotations

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.governance.release import (
    compare_shadow,
    get_canary_percent,
    get_release_status,
    promote_release,
    rollback_release,
    set_canary_percent,
)
from vastacore.governance.versioning import publish_model_version

RULESET_V1 = {"rules": {"right": {"add": {"col": 1}}}, "goal_check": "done"}
RULESET_V2 = {"rules": {"right": {"add": {"col": 2}}}, "goal_check": "done"}
MANIFEST = {"name": "grid", "version": "1.0", "scope": "grid",
            "unknowns": ["u"], "coverage": ["right"]}


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


async def seed_two_versions(store) -> None:
    await publish_model_version(store, "grid", "1.0.0",
                                ruleset=RULESET_V1, manifest=MANIFEST)
    await publish_model_version(store, "grid", "2.0.0",
                                ruleset=RULESET_V2, manifest=MANIFEST)


class TestStateMachine:
    async def test_full_promotion_path(self, store) -> None:
        """AC：candidate→testing→shadow→canary→active 全路径。"""
        await seed_two_versions(store)
        for to_status in ("testing", "shadow", "canary", "active"):
            result = await promote_release(store, "model", "grid", "2.0.0",
                                           to=to_status)
            assert result.status == to_status
        assert await get_release_status(store, "model", "grid") == "active"

    async def test_illegal_skip_rejected(self, store) -> None:
        """AC：candidate 直跳 active 拒绝。"""
        await seed_two_versions(store)
        with pytest.raises(VastaError) as excinfo:
            await promote_release(store, "model", "grid", "2.0.0", to="active")
        assert excinfo.value.code == "release.invalid_transition"

    async def test_transitions_logged(self, store) -> None:
        """AC：各状态转换落事件。"""
        await seed_two_versions(store)
        await promote_release(store, "model", "grid", "2.0.0", to="testing")
        events = [e for e in store.iter_run_events("registry")
                  if e.type == "release.transition"]
        assert len(events) >= 1
        assert events[-1].payload["to"] == "testing"

    async def test_unpublished_version_rejected(self, store) -> None:
        with pytest.raises(VastaError):
            await promote_release(store, "model", "grid", "9.9.9", to="testing")


class TestRollback:
    async def test_rollback_restores_previous_active(self, store) -> None:
        """AC：回滚恢复引用至前 active 版本。"""
        await seed_two_versions(store)
        # v1 全推到 active
        for s in ("testing", "shadow", "canary", "active"):
            await promote_release(store, "model", "grid", "1.0.0", to=s)
        # v2 全推到 active（替换 v1）
        for s in ("testing", "shadow", "canary", "active"):
            await promote_release(store, "model", "grid", "2.0.0", to=s)
        assert await get_release_status(store, "model", "grid") == "active"
        # 回滚 → 恢复 v1 active
        result = await rollback_release(store, "model", "grid")
        assert result.rolled_back_to == "1.0.0"
        assert await get_release_status(store, "model", "grid") == "active"
        # 回滚事件
        events = [e for e in store.iter_run_events("registry")
                  if e.type == "release.rolled_back"]
        assert len(events) >= 1

    async def test_rollback_no_active_fails(self, store) -> None:
        """无 active 版可回滚 → 拒。"""
        await seed_two_versions(store)  # 均未推到 active
        with pytest.raises(VastaError):
            await rollback_release(store, "model", "grid")


class TestShadowAndCanary:
    async def test_shadow_compare_diff(self, store) -> None:
        """AC：影子期新旧版本并行对比产出差异报告（评审修复 G1 锚定：
        差异**非空**——曾两次取同一版本恒 0 差异也过本测试）。"""
        await seed_two_versions(store)
        report = await compare_shadow(store, "model", "grid",
                                     new_version="2.0.0",
                                     old_version="1.0.0")
        assert report["old_version"] == "1.0.0"
        assert report["new_version"] == "2.0.0"
        assert report["total_diffs"] >= 1  # ruleset 确实不同 → 差异必非空
        fields = {d["field"] for d in report["differences"]}
        assert fields  # 差异字段可定位（灰度放行依据）

    async def test_shadow_compare_identical_versions_no_diff(
            self, store) -> None:
        """同版本自比 → 0 差异（对照锚定——差异检测真实工作）。"""
        await seed_two_versions(store)
        report = await compare_shadow(store, "model", "grid",
                                     new_version="1.0.0",
                                     old_version="1.0.0")
        assert report["total_diffs"] == 0

    async def test_phantom_version_rejected(self, store) -> None:
        """评审修复：幻影版本号不可入状态机（曾只查资产级存在性）。"""
        await seed_two_versions(store)
        with pytest.raises(VastaError) as excinfo:
            await promote_release(store, "model", "grid", "9.9.9",
                                  to="testing")
        assert excinfo.value.code == "release.version_not_published"

    async def test_canary_percent_configurable(self, store) -> None:
        """AC：灰度比例可配。"""
        await seed_two_versions(store)
        await set_canary_percent(store, "model", "grid", 25)
        assert await get_canary_percent(store, "model", "grid") == 25
        await set_canary_percent(store, "model", "grid", 100)
        assert await get_canary_percent(store, "model", "grid") == 100

    async def test_canary_percent_validation(self, store) -> None:
        await seed_two_versions(store)
        with pytest.raises(VastaError):
            await set_canary_percent(store, "model", "grid", 0)
        with pytest.raises(VastaError):
            await set_canary_percent(store, "model", "grid", 101)
