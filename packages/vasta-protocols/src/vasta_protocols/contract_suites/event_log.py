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
        b = EventEnvelope.model_validate(
            {**run.model_dump(), "seq": 1, "type": "observation.decision",
             "parent_event_id": run.event_id}
        )
        log.append(a)
        log.append(b)
        assert [e.seq for e in log.iter_run(run.run_id)] == [0, 1]

    def test_parent_chain_traceable(self) -> None:
        log = self.make_log()
        root = make_envelope(seq=0)
        child = EventEnvelope.model_validate(
            {**root.model_dump(), "seq": 1, "parent_event_id": root.event_id}
        )
        log.append(root)
        log.append(child)
        assert log.get(child.run_id, 1).parent_event_id == root.event_id
