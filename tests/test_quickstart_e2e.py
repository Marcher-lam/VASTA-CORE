"""Story 1.7：quickstart 端到端首跑（Epic 1 验收演示）。"""

from __future__ import annotations

import json
from pathlib import Path

import vastacore
from vasta_adapters import GridWorldAdapter
from vasta_protocols.contract_suites import EnvironmentAdapterContract
from vasta_storage import SqliteStorage


class TestGridWorldContract(EnvironmentAdapterContract):
    """Story 1.1 环境契约套件驱动 GridWorldAdapter。"""

    valid_action_tool = "right"

    def make_adapter(self) -> GridWorldAdapter:
        return GridWorldAdapter()


class TestQuickstartE2E:
    async def test_full_run_with_evidence_and_causal_chain(self, tmp_path) -> None:
        summary = await vastacore.quickstart(tmp_path / "qs", seed=1, run_id="run-e2e")

        # 摘要
        assert summary.final_state == "completed"
        assert summary.goal_reached is True
        assert summary.steps == 6  # right×3 + down×3
        assert summary.vastacore_version == vastacore.__version__

        # 重开存储：完整事件链 + 因果父链
        store = SqliteStorage(Path(summary.store_root))
        events = list(store.iter_run_events("run-e2e"))
        types = [e.type for e in events]
        assert types[0] == "run.created" and events[0].parent_event_id is None
        assert "observation.terminal" in types
        assert types[-1] == "run.completed"
        for prev, cur in zip(events, events[1:], strict=False):
            assert cur.parent_event_id == prev.event_id

        # 证据全落盘：每条观察事件带 artifact_refs 且可校验取回
        observation_events = [e for e in events if e.type.startswith("observation.")]
        assert observation_events, "no observation events captured"
        for event in observation_events:
            refs = event.payload["artifact_refs"]
            assert isinstance(refs, list) and refs, f"{event.type} lacks artifact_refs"
            captured = json.loads(await store.get_artifact(refs[0]))
            assert captured["kind"] in {
                "decision",
                "transition",
                "terminal",
                "reset",
                "external",
            }
        assert summary.artifacts == len(observation_events)
        store.close()

    async def test_same_run_id_and_seed_byte_identical(self, tmp_path) -> None:
        first = await vastacore.quickstart(tmp_path / "a", seed=7, run_id="run-det")
        second = await vastacore.quickstart(tmp_path / "b", seed=7, run_id="run-det")

        store_a = SqliteStorage(tmp_path / "a" / "store")
        store_b = SqliteStorage(tmp_path / "b" / "store")
        json_a = [e.model_dump_json() for e in store_a.iter_run_events("run-det")]
        json_b = [e.model_dump_json() for e in store_b.iter_run_events("run-det")]
        store_a.close()
        store_b.close()
        assert json_a == json_b  # NFR-002：SDK 级确定性演示
        assert first.events == second.events and first.artifacts == second.artifacts

    async def test_budget_caps_the_run(self, tmp_path) -> None:
        summary = await vastacore.quickstart(
            tmp_path / "tight", seed=1, run_id="run-cap", max_steps=2
        )
        assert summary.goal_reached is False
        assert summary.final_state == "failed"  # 预算安全停止（Story 1.2 路径）


class TestVersionSyncGuard:
    def test_docs_and_example_carry_current_version(self) -> None:
        version = vastacore.__version__
        repo_root = Path(__file__).resolve().parent.parent
        example = (repo_root / "examples" / "quickstart.py").read_text(encoding="utf-8")
        docs = (repo_root / "docs" / "quickstart.md").read_text(encoding="utf-8")
        assert version in example, "examples/quickstart.py 未与 sdk 版本同步"
        assert version in docs, "docs/quickstart.md 未与 sdk 版本同步"

    def test_docs_mention_the_run_command(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        docs = (repo_root / "docs" / "quickstart.md").read_text(encoding="utf-8")
        assert "uv run python examples/quickstart.py" in docs
        assert "uv sync --all-packages" in docs
