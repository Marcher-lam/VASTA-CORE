"""EventEnvelope schema 契约（纯 schema，无需被测件）。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ..envelope import ENVELOPE_SCHEMA_VERSION, EVENT_FAMILIES, EventEnvelope
from ..ids import new_event_id, new_run_id, now_utc


def make_envelope(**overrides: object) -> EventEnvelope:
    base: dict[str, object] = {
        "run_id": new_run_id(),
        "seq": 0,
        "type": "run.created",
        "parent_event_id": None,
        "ts": now_utc(),
        "tenant_id": "t-default",
        "project_id": "p-default",
        "event_id": new_event_id(),
    }
    base.update(overrides)
    return EventEnvelope.model_validate(base)


class EventEnvelopeContract:
    """信封 schema 的最低契约；实现方可追加更严的测试。"""

    def test_seven_required_fields_present(self) -> None:
        env = make_envelope()
        for field in (
            "run_id",
            "seq",
            "type",
            "parent_event_id",
            "ts",
            "tenant_id",
            "project_id",
        ):
            assert hasattr(env, field)

    def test_schema_version_carried(self) -> None:
        assert make_envelope().schema_version == ENVELOPE_SCHEMA_VERSION

    def test_frozen_and_closed(self) -> None:
        env = make_envelope()
        with pytest.raises(ValidationError):
            env.seq = 1  # type: ignore[misc]
        with pytest.raises(ValidationError):
            EventEnvelope.model_validate(
                {**make_envelope().model_dump(), "rogue_field": 1}
            )

    def test_seq_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            make_envelope(seq=-1)

    def test_event_type_must_be_dotted(self) -> None:
        with pytest.raises(ValidationError):
            make_envelope(type="run_created")

    def test_event_family_closed_set(self) -> None:
        with pytest.raises(ValidationError):
            make_envelope(type="cosmos.bigbang")
        assert len(EVENT_FAMILIES) == 13

    def test_ts_requires_tzinfo(self) -> None:
        naive = now_utc().replace(tzinfo=None)
        with pytest.raises(ValidationError):
            make_envelope(ts=naive)
