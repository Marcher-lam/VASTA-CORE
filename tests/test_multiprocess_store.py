"""Story 9.15：多进程共享单库部署形态（NFR-006 工程面）。

分布式形态的工程内锚点：3 个真实 OS 进程并发写同一个 SQLite 库——
**每流单写者**（分区契约：同流 seq 分配无跨进程锁，跨机/跨进程部署
按流分区）。断言：各流序号连续无洞、event_id 全局唯一、全库完整性
校验绿（真跨机部署的属地运营不在工程内验证——PRD 口径）。
"""

from __future__ import annotations

import subprocess
import sys

from vasta_storage import SqliteStorage
from vastacore.ops.ops import verify_stream_integrity

_WORKER = r"""
import asyncio, sys
from pathlib import Path
from vasta_protocols.sequencer import EventSequencer
from vasta_storage import SqliteStorage

store_path, run_id, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
store = SqliteStorage(Path(store_path))

async def main():
    seq = EventSequencer(store, run_id,
                         tenant_id="t-default", project_id="p-default")
    for i in range(n):
        await seq.emit("observation.decision", {"worker": run_id, "i": i})
    store.close()

asyncio.run(main())
print("ok", run_id)
"""


class TestMultiprocessSharedStore:
    def test_three_processes_each_own_stream(self, tmp_path) -> None:
        store_path = tmp_path / "shared" / "s"
        store_path.parent.mkdir(parents=True)
        SqliteStorage(store_path).close()  # 建库（进程并发首开安全）
        n = 25
        procs = [
            subprocess.Popen(  # noqa: S603
                [sys.executable, "-c", _WORKER, str(store_path),
                 f"stream-{k}", str(n)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for k in range(3)
        ]
        for proc in procs:
            _, err = proc.communicate(timeout=60)
            assert proc.returncode == 0, err.decode(errors="replace")[-400:]

        store = SqliteStorage(store_path)
        try:
            for k in range(3):
                events = list(store.iter_run_events(f"stream-{k}"))
                assert [e.seq for e in events] == list(range(n)), \
                    f"stream-{k} 序号有洞/乱序"
                assert all(e.payload["worker"] == f"stream-{k}"
                           for e in events)
            # event_id 全局唯一（跨进程无碰撞）
            ids = [e.event_id
                   for k in range(3)
                   for e in store.iter_run_events(f"stream-{k}")]
            assert len(ids) == len(set(ids)) == 3 * n
            # 全库完整性（含 CAS 引用与流校验）
            report = verify_stream_integrity(store)
            assert report.ok, report.missing_artifacts
        finally:
            store.close()
