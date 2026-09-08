"""信封的性质测试（hypothesis）：合法 seq 全域可接受、族外类型必拒。"""

from __future__ import annotations

from datetime import timedelta

from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from vasta_protocols.envelope import EVENT_FAMILIES, EventEnvelope
from vasta_protocols.ids import new_event_id, new_run_id, now_utc


def _base() -> dict[str, object]:
    return {
        "run_id": new_run_id(),
        "seq": 0,
        "type": "run.created",
        "ts": now_utc(),
        "tenant_id": "t",
        "project_id": "p",
        "event_id": new_event_id(),
    }


class TestEnvelopeProperties:
    @given(seq=st.integers(min_value=0, max_value=10**9))
    def test_any_nonnegative_seq_accepted(self, seq: int) -> None:
        env = EventEnvelope.model_validate({**_base(), "seq": seq})
        assert env.seq == seq

    @given(
        family=st.sampled_from(sorted(EVENT_FAMILIES)),
        verb=st.sampled_from(["created", "updated", "paused", "refuted"]),
    )
    def test_any_family_verb_combination_accepted(self, family: str, verb: str) -> None:
        env = EventEnvelope.model_validate({**_base(), "type": f"{family}.{verb}"})
        assert env.type == f"{family}.{verb}"

    @given(delta_minutes=st.integers(min_value=-10**6, max_value=10**6))
    def test_past_and_future_utc_timestamps_normalized(self, delta_minutes: int) -> None:
        ts = now_utc() + timedelta(minutes=delta_minutes)
        env = EventEnvelope.model_validate({**_base(), "ts": ts})
        assert env.ts.tzinfo is not None

    @given(bad=st.sampled_from(["run", "RUN.CREATED", "run..created", "run.created.", "x.run"]))
    def test_malformed_types_rejected(self, bad: str) -> None:
        try:
            EventEnvelope.model_validate({**_base(), "type": bad})
        except ValidationError:
            return
        raise AssertionError(f"{bad!r} should have been rejected")

    def test_naive_timestamp_rejected(self) -> None:
        naive = now_utc().replace(tzinfo=None)
        try:
            EventEnvelope.model_validate({**_base(), "ts": naive})
        except ValidationError:
            return
        raise AssertionError("naive datetime should have been rejected")
