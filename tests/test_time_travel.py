"""Story 8.7：版本回溯收口——派生物与记忆（FR-061，G4）。

as-of 重放取当时 Claim；派生物回链校验；查询只读零副作用。
"""

from __future__ import annotations

from datetime import UTC

import pytest

from vasta_cognition import Claim, CognitionService
from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.evidence.timetravel import claim_as_of, derived_recall


def make_claim(claim_id: str, **overrides) -> Claim:
    fields = dict(
        claim_id=claim_id, memory_type="hypothesis",
        statement=f"statement-{claim_id}", evidence=["sha:base"],
        confidence=0.7,
    )
    fields.update(overrides)
    return Claim.model_validate(fields)


@pytest.fixture
def cognition_store(tmp_path):
    store = SqliteStorage(tmp_path / "store")
    svc = CognitionService(store)
    yield store, svc
    store.close()


async def seeded_claims(store, svc):
    """演进一个 Claim：proposed → supported(v2) → accepted(v3)。"""
    await svc.propose(make_claim("c1"))
    await svc.support("c1", ["sha:extra"])
    await svc.accept("c1")
    return store


class TestClaimAsOf:
    async def test_mid_history_version_replayed(self, cognition_store) -> None:
        """AC：as-of 中途点取回当时版本（不是最新冒充）。"""
        store, svc = cognition_store
        await seeded_claims(store, svc)
        events = list(store.iter_run_events("cognition"))
        claim_events = [e for e in events if e.payload.get("claim_id") == "c1"]
        propose_seq = claim_events[0].seq
        support_seq = claim_events[1].seq

        at_propose = await claim_as_of(store, "c1", as_of_seq=propose_seq)
        assert at_propose.status == "proposed"
        assert at_propose.version == 1
        assert "sha:extra" not in at_propose.evidence  # 当时还没有

        at_support = await claim_as_of(store, "c1", as_of_seq=support_seq)
        assert at_support.status == "supported"
        assert at_support.version == 2
        assert "sha:extra" in at_support.evidence

        # 全量重放 = 当前态（与投影一致）
        latest = await claim_as_of(store, "c1", as_of_seq=10_000)
        assert latest.status == "accepted" and latest.version == 3

    async def test_not_yet_existing_rejected(self, cognition_store) -> None:
        """AC：该时点不存在 → 明确报错（不拿最新冒充当时）。"""
        store, svc = cognition_store
        await seeded_claims(store, svc)
        first_seq = next(e.seq for e in store.iter_run_events("cognition"))
        with pytest.raises(VastaError) as excinfo:
            await claim_as_of(store, "c1", as_of_seq=first_seq - 1)
        assert "not_found_at" in excinfo.value.code

    async def test_as_of_ts_supported(self, tmp_path) -> None:
        """ts 语义：构造明确分层的时点（相邻事件 ts 可区分）。"""
        from datetime import datetime, timedelta

        from vasta_protocols.envelope import EventEnvelope
        from vasta_protocols.ids import new_event_id

        store = SqliteStorage(tmp_path / "s")
        base = datetime(2026, 5, 1, tzinfo=UTC)
        parent = None
        for seq, (type_, payload) in enumerate((
            ("claim.proposed", {"claim_id": "t1", "memory_type": "hypothesis",
                                "statement": "s", "evidence": ["sha:1"],
                                "version": 1}),
            ("claim.supported", {"claim_id": "t1", "evidence": ["sha:2"]}),
            ("claim.accepted", {"claim_id": "t1"}),
        )):
            env = EventEnvelope.model_validate({
                "run_id": "cognition", "seq": seq, "type": type_,
                "parent_event_id": parent, "ts": base + timedelta(seconds=seq),
                "tenant_id": "t-default", "project_id": "p-default",
                "event_id": new_event_id(), "payload": payload,
            })
            await store.append_event(env)
            parent = env.event_id
        mid = base + timedelta(seconds=1, microseconds=500)
        claim = await claim_as_of(store, "t1", as_of_ts=mid)
        assert claim.status == "supported"  # 恰含前两事件
        early = base + timedelta(seconds=0, microseconds=500)
        assert (await claim_as_of(store, "t1", as_of_ts=early)).status == "proposed"
        store.close()

    async def test_unknown_claim_rejected(self, cognition_store) -> None:
        store, _ = cognition_store
        with pytest.raises(VastaError):
            await claim_as_of(store, "ghost", as_of_seq=99)


class TestDerivedRecall:
    async def test_recall_verifies_source_chain(self, tmp_path) -> None:
        """AC：派生物回链 + 源哈希校验（verified 三态）。"""
        store = SqliteStorage(tmp_path / "s")
        src = await store.save_artifact(b"source-bytes", mime="text/plain")
        derived = await store.save_derived(
            b"derived-bytes", source_sha256=src, transform="crop",
            params={"box": [1, 2, 3, 4]}, transformer_version="v1",
        )
        recall = await derived_recall(store, derived)
        assert recall.status == "verified"
        assert recall.source_sha256 == src
        assert recall.payload == b"derived-bytes"  # 当时内容原样取回
        store.close()

    async def test_recall_detects_tampered_source(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        src = await store.save_artifact(b"source-bytes", mime="text/plain")
        derived = await store.save_derived(
            b"derived-bytes", source_sha256=src, transform="crop",
            params={}, transformer_version="v1",
        )
        # 篡改源 blob
        blob = store.objects_dir / src[:2] / src  # noqa: SLF001
        blob.write_bytes(b"tampered!!")
        recall = await derived_recall(store, derived)
        assert recall.status in ("source_corrupted", "derived_corrupted")
        store.close()

    async def test_recall_unknown_sha_rejected(self, tmp_path) -> None:
        store = SqliteStorage(tmp_path / "s")
        with pytest.raises(VastaError):
            await derived_recall(store, "0" * 64)
        store.close()


class TestZeroSideEffect:
    async def test_queries_leave_no_trace(self, tmp_path) -> None:
        """AC：查询只读零副作用——事件数/工件数不变。"""
        store = SqliteStorage(tmp_path / "s")
        src = await store.save_artifact(b"src", mime="text/plain")
        derived = await store.save_derived(
            b"d", source_sha256=src, transform="t", params={},
            transformer_version="v1",
        )
        events_before = len(list(store.iter_run_events("cognition")))
        arts_before = len(await store.list_artifacts("t-default", "p-default"))

        await derived_recall(store, derived)

        events_after = len(list(store.iter_run_events("cognition")))
        arts_after = len(await store.list_artifacts("t-default", "p-default"))
        assert (events_before, arts_before) == (events_after, arts_after)
        store.close()

    async def test_claim_as_of_no_new_events(self, cognition_store) -> None:
        store, svc = cognition_store
        await seeded_claims(store, svc)
        before = len(list(store.iter_run_events("cognition")))
        await claim_as_of(store, "c1", as_of_seq=3)
        await claim_as_of(store, "c1", as_of_seq=1)
        after = len(list(store.iter_run_events("cognition")))
        assert before == after  # 只读
