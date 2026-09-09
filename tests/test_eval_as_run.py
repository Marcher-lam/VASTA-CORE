"""Story 8.9：评测即 Run——替身模型批量回放（AC-01 关键路径，G4）。

≥40 VastaLab 任务经 RunEngine 批量运行；每任务完整事件流 + 复现包可离线重放。
"""

from __future__ import annotations

import json

import pytest

from vasta_eval import generate_tasks
from vasta_storage import SqliteStorage, export_repro_bundle, replay_non_model_events, timeline
from vastacore.batch import BatchRunSummary, run_tasks_as_runs


@pytest.fixture(scope="module")
def forty_plus_tasks():
    tasks = generate_tasks(20, seed=42)  # 20 主 + 20 噪声 + 10 偏差 = 50 ≥ 40
    assert len(tasks) >= 40
    return tasks


class TestBatchRun:
    async def test_forty_plus_tasks_all_succeed_with_full_streams(
        self, tmp_path, forty_plus_tasks
    ) -> None:
        """AC：≥40 任务批量运行——全成功 + 每任务 timeline 全覆盖。"""
        summary = await run_tasks_as_runs(
            forty_plus_tasks, root=tmp_path / "batch", seed=42
        )
        assert isinstance(summary, BatchRunSummary)
        assert summary.runs == len(forty_plus_tasks)
        assert summary.success_rate == 1.0  # solve 路径保证可达
        assert summary.total_events > len(forty_plus_tasks) * 5  # 每任务实质事件量

        store = SqliteStorage(tmp_path / "batch" / "store")
        try:
            for result in summary.results:
                events = list(store.iter_run_events(result.run_id))
                assert len(events) == result.events
                tl = timeline(events)
                assert tl.covers_all_events, result.task_id  # AC-01 完整回放
                assert tl.max_depth >= 1  # 因果链可溯
                types = [e.type for e in events]
                assert types[0] == "run.created" and types[-1] == "run.completed"
                assert "observation.terminal" in types  # 到达终局
        finally:
            store.close()

    async def test_repro_bundle_offline_replayable(self, tmp_path,
                                                   forty_plus_tasks) -> None:
        """AC：复现包可导出且离线重放数=事件数。"""
        tasks = forty_plus_tasks[:5]  # 抽样 5 个任务足够验证
        summary = await run_tasks_as_runs(tasks, root=tmp_path / "b2", seed=7)
        store = SqliteStorage(tmp_path / "b2" / "store")
        try:
            for result in summary.results:
                bundle, event_bytes = await export_repro_bundle(
                    store, result.run_id
                )
                assert bundle.event_count == result.events
                replayed = replay_non_model_events(event_bytes)
                assert len(replayed) == bundle.event_count  # 全量离线重放
        finally:
            store.close()

    async def test_same_seed_deterministic_across_stores(self, tmp_path,
                                                         forty_plus_tasks) -> None:
        """同 seed 双库批量 → 逐任务归一化流逐字节一致。"""
        tasks = forty_plus_tasks[:6]
        streams = []
        for sub in ("s1", "s2"):
            await run_tasks_as_runs(tasks, root=tmp_path / sub, seed=11)
            store = SqliteStorage(tmp_path / sub / "store")
            try:
                per_task = {}
                for t in tasks:
                    run_id = f"vlrun-{t.task_id}"
                    rows = [
                        {"seq": e.seq, "type": e.type, "payload": e.payload}
                        for e in store.iter_run_events(run_id)
                    ]
                    per_task[t.task_id] = json.dumps(
                        rows, sort_keys=True, ensure_ascii=False
                    )
                streams.append(per_task)
            finally:
                store.close()
        assert streams[0] == streams[1]

    async def test_summary_carries_per_task_results(self, tmp_path) -> None:
        tasks = generate_tasks(4, seed=3)[:4]
        summary = await run_tasks_as_runs(tasks, root=tmp_path / "b3", seed=3)
        assert len(summary.results) == 4
        for result, task in zip(summary.results, tasks, strict=True):
            assert result.task_id == task.task_id
            assert result.run_id == f"vlrun-{task.task_id}"
            assert result.success is True
            assert result.steps >= 3  # 4x4 网格最短路径 ≥3 步
            assert result.events >= 6

    async def test_model_exchange_artifacts_persisted(self, tmp_path) -> None:
        """每步模型交换落 Artifact（AD-5）——预算与证据双登记。"""
        tasks = generate_tasks(2, seed=5)[:2]
        summary = await run_tasks_as_runs(tasks, root=tmp_path / "b4", seed=5)
        store = SqliteStorage(tmp_path / "b4" / "store")
        try:
            arts = await store.list_artifacts("t-default", "p-default")
            exchanges = [a for a in arts if a.get("source") == "model.exchange"]
            # 每步一个交换 artifact ≥ 总步数
            total_steps = sum(r.steps for r in summary.results)
            assert len(exchanges) >= total_steps
        finally:
            store.close()
