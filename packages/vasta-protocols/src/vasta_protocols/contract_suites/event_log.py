"""事件日志契约：(run_id, seq) 唯一（AD-2）、Run 内有序、因果父项可回溯。"""

from __future__ import annotations

import pytest

from ..envelope import EventEnvelope, InMemoryEventLog
from ..errors import DuplicateEventError
from ..ids import new_event_id
from .event_envelope import make_envelope


class EventLogContract:
    """事件日志端口契约。实现方实现 make_log()；InMemoryEventLog 为参考实现。"""

    def make_log(self) -> InMemoryEventLog:
        raise NotImplementedError("adapter package must provide make_log()")

    def test_append_and_get_roundtrip(self) -> None:
        log = self.make_log()
        env = make_envelope()
        log.append(env)
        assert log.get(env.run_id, 0) == env

    def test_duplicate_run_seq_rejected(self) -> None:
        log = self.make_log()
        first = make_envelope()
        log.append(first)
        second = EventEnvelope.model_validate(
            {**first.model_dump(), "event_id": new_event_id()}
        )
        with pytest.raises(DuplicateEventError):
            log.append(second)

    def test_same_seq_across_runs_allowed(self) -> None:
        log = self.make_log()
        a = make_envelope(seq=0)
        b = make_envelope(seq=0)  # 不同 run_id（工厂默认新 run）
        log.append(a)
        log.append(b)

    def test_iter_run_preserves_order(self) -> None:
        log = self.make_log()
        run = a = make_envelope(seq=0)
        from ..ids import new_event_id

        b = EventEnvelope.model_validate(
            # 每信封独立 event_id（Story 10.2 约束对齐——复用 ID 的
            # 假信封在真实存储 UNIQUE 约束下非法）
            {**run.model_dump(), "seq": 1, "type": "observation.decision",
             "parent_event_id": run.event_id, "event_id": new_event_id()}
        )
        log.append(a)
        log.append(b)
        assert [e.seq for e in log.iter_run(run.run_id)] == [0, 1]

    def test_parent_chain_traceable(self) -> None:
        log = self.make_log()
        root = make_envelope(seq=0)
        from ..ids import new_event_id

        child = EventEnvelope.model_validate(
            {**root.model_dump(), "seq": 1, "parent_event_id": root.event_id,
             "event_id": new_event_id()}
        )
        log.append(root)
        log.append(child)
        assert log.get(child.run_id, 1).parent_event_id == root.event_id

    def test_missing_event_raises_error_envelope(self) -> None:
        """缺失键必须以错误信封（VastaError/event.not_found）失败，
        不得裸抛 KeyError（约定：错误形状统一）。"""
        from ..errors import VastaError

        log = self.make_log()
        with pytest.raises(VastaError) as excinfo:
            log.get("run-missing", 0)
        assert excinfo.value.code == "event.not_found"

    def test_duplicate_event_id_rejected(self) -> None:
        """Story 10.2 约束对齐：event_id 全局唯一（跨 run）——与
        sqlite `event_id UNIQUE` 一致（曾缺失致 seeded 接管缺陷在
        fake 面不可见）。"""
        from ..errors import VastaError
        from ..ids import new_event_id

        log = self.make_log()
        a = make_envelope(seq=0)
        dup_id = EventEnvelope.model_validate(
            {**a.model_dump(), "run_id": "other-run", "seq": 0,
             "event_id": a.event_id}
        )
        fresh = EventEnvelope.model_validate(
            {**a.model_dump(), "seq": 1, "event_id": new_event_id()}
        )
        log.append(a)
        with pytest.raises(VastaError) as excinfo:
            log.append(dup_id)  # 跨 run 同 ID 拒
        assert excinfo.value.code == "event.duplicate_id"
        log.append(fresh)  # 新 ID 同 run 正常
