"""Story 8.10：历史轨迹离线评估（FR-066，G4）——不重跑生产预判切换影响。

只读重放：导入轨迹 × 新核验器 → 新旧对照 + 偏差定位；零副作用。
"""

from __future__ import annotations

import pytest

from vasta_protocols.protocols import Verification, VerifierManifest
from vasta_storage import SqliteStorage
from vastacore.offline_eval import OfflineEvalReport, offline_evaluate
from vastacore.trajectory import import_trajectory

# ---- 导入轨迹样例（Story 8.2 形态）----

OPENAI_TRAJECTORY = [
    {"type": "message", "role": "user", "content": "把订单 A102 标记发货"},
    {"type": "message", "role": "assistant", "content": None,
     "tool_calls": [{"id": "call_1", "name": "ship_order",
                     "arguments": {"order_id": "A102"}}]},
    {"type": "tool_call", "call_id": "call_1", "name": "ship_order",
     "output": {"ok": True, "status": "shipped"}},
]


class StrictVerifier:
    """严格核验器：要求 detail 含期望值，否则 deviation。"""

    def __init__(self, expect: str) -> None:
        self.manifest = VerifierManifest(
            name="strict_read_back", version="1", kind="read_back"
        )
        self.expect = expect

    async def verify(self, ref, evidence) -> Verification:
        blobs = []
        after = evidence.get("after_observation")
        if isinstance(after, dict):
            blobs.append(str(after.get("detail", {})))
        result = evidence.get("result")
        if isinstance(result, dict):
            blobs.append(str(result))  # 搜整个响应本体（引擎 ToolResult 形态与导入扁平形态皆稳健）
        joined = "".join(blobs)
        if self.expect in joined:
            return Verification(outcome="pass")
        return Verification(
            outcome="deviation", detail={"expected": self.expect,
                                         "seen": joined[:80]},
        )


class AlwaysPass:
    def __init__(self) -> None:
        self.manifest = VerifierManifest(
            name="always_pass", version="1", kind="read_back"
        )

    async def verify(self, ref, evidence) -> Verification:
        return Verification(outcome="pass")


@pytest.fixture
def imported_store(tmp_path):
    store = SqliteStorage(tmp_path / "s")
    yield store
    store.close()


async def seed_imported(store) -> str:
    await import_trajectory(store, OPENAI_TRAJECTORY, run_id="imp-eval",
                            source_format="openai")
    return "imp-eval"


class TestOfflineEval:
    async def test_imported_trajectory_strict_verifier_flags_deviation(
        self, imported_store
    ) -> None:
        """AC：导入轨迹 × 严核验器 → 偏差清单含事件定位。

        轨迹结果 status=shipped；严核验器期望 archived → 新判 deviation，
        旧判 none-recorded（导入无核验历史）。"""
        run_id = await seed_imported(imported_store)
        report = await offline_evaluate(
            imported_store, run_id,
            verifiers={"strict": StrictVerifier(expect="archived")},
        )
        assert isinstance(report, OfflineEvalReport)
        assert report.actions_evaluated == 1
        assert len(report.changed) == 1
        entry = report.changed[0]
        assert entry.tool == "ship_order"
        assert entry.old_outcome == "none-recorded"  # 不伪造旧 pass
        assert entry.new_outcomes["strict"] == "deviation"
        assert entry.seq >= 0  # 事件定位
        assert "archived" in entry.detail  # 证据摘要

    async def test_matching_verifier_unchanged(self, imported_store) -> None:
        """期望值匹配轨迹 → pass vs none-recorded 记为 changed=False？

        语义判定：导入轨迹无旧核验——新核验器通过不构成「偏差」（切换无影响）。
        changed 仅在新旧判定冲突时置位：none-recorded + pass → 不算冲突。"""
        run_id = await seed_imported(imported_store)
        report = await offline_evaluate(
            imported_store, run_id,
            verifiers={"ok": StrictVerifier(expect="shipped")},
        )
        assert report.changed == []  # 新核验通过 → 无切换影响
        assert report.unchanged == 1

    async def test_engine_run_old_verification_compared(self, tmp_path) -> None:
        """引擎产生的 run（有旧核验事件）→ 新旧对照。"""
        from vasta_protocols.protocols import Action
        from vastacore import AgentSession

        from .test_agent_sdk import STATUS_CONTRACT, SetStatusTool, TodoEnv

        session = await AgentSession.create(
            env=TodoEnv(), tools=[SetStatusTool()],
            contracts={"set_status": STATUS_CONTRACT},
            root=tmp_path / "eng", seed=1,
        )
        async with session:
            await session.start()
            await session.reset()
            await session.act(Action(tool="set_status", args={"status": "done"}))
            await session.complete()
            run_id = session.run_id
        store = SqliteStorage(tmp_path / "eng" / "store")
        try:
            # 期望 done（与原核验一致）→ pass vs pass → unchanged
            report = await offline_evaluate(
                store, run_id,
                verifiers={"same": StrictVerifier(expect="done")},
            )
            assert report.actions_evaluated == 1
            assert report.changed == []
            assert report.results[0].old_outcome == "pass"
            # 期望错值 → deviation vs passed → changed
            report2 = await offline_evaluate(
                store, run_id,
                verifiers={"harsh": StrictVerifier(expect="archived")},
            )
            assert len(report2.changed) == 1
            assert report2.changed[0].old_outcome == "pass"
            assert report2.changed[0].new_outcomes["harsh"] == "deviation"
        finally:
            store.close()

    async def test_zero_side_effect(self, imported_store) -> None:
        """AC：评估零副作用——事件数/工件数不变，不产生新动作。"""
        run_id = await seed_imported(imported_store)
        events_before = len(list(imported_store.iter_run_events(run_id)))
        arts_before = len(await imported_store.list_artifacts(
            "t-default", "p-default"))
        for _ in range(2):
            await offline_evaluate(
                imported_store, run_id,
                verifiers={"s": StrictVerifier(expect="nope")},
            )
        assert len(list(imported_store.iter_run_events(run_id))) == events_before
        assert len(await imported_store.list_artifacts(
            "t-default", "p-default")) == arts_before

    async def test_unknown_run_rejected(self, imported_store) -> None:
        from vasta_protocols.errors import VastaError

        with pytest.raises(VastaError):
            await offline_evaluate(imported_store, "ghost",
                                   verifiers={"s": AlwaysPass()})
