"""Story 9.13：Domain Studio 初版（FR-028，G5——UJ-2）。

认知图浏览/证据下钻/影响分析预览（只读）；专家审核/标注经 HTTP 走
事件留痕 + 批准流（UI 零旁路 AD-2）。
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vasta_cognition.cognition import Claim, CognitionService
from vasta_protocols.sequencer import EventSequencer
from vasta_storage import SqliteStorage
from vastacore.studio import mount_studio

H = {"Authorization": "Bearer tok-studio"}


@pytest.fixture
def client(tmp_path):
    store = SqliteStorage(tmp_path / "s")
    # 种子（先于 mount——cognition 投影在构造期固化）：
    # 两条同 scope 主张（触发冲突检测）+ 一条下游 + 一个源 Run
    async def _seed() -> None:
        await EventSequencer(store, "run-src").emit(
            "run.created", {"budget": {}})
        cog = CognitionService(store)
        await cog.propose(Claim(
            claim_id="c1", memory_type="guide",
            statement="订单超时自动取消", scope={"region": "prod"},
            confidence=0.8, run_id="run-src",
            evidence=["run-src:0"]))  # 证据链路（accept 前置——FR-021）
        await cog.propose(Claim(
            claim_id="c2", memory_type="guide",
            statement="订单超时不取消", scope={"region": "prod"}))
        await cog.propose(Claim(
            claim_id="c3", memory_type="working", statement="下游主张",
            scope={}, depends_on=["c1"]))

    import asyncio

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        _seed())
    app = FastAPI()
    mount_studio(app, store=store, token="tok-studio")
    with TestClient(app) as c:
        yield c, store
    store.close()


class TestReadOnly:
    def test_page_requires_token(self, client) -> None:
        c, _ = client
        assert c.get("/studio/").status_code == 401
        r = c.get("/studio/", headers=H)
        assert r.status_code == 200
        assert "Domain Studio" in r.text  # 自包含 HTML

    def test_claims_listing_with_dependency_counts(self, client) -> None:
        """认知图浏览：主张清单含依赖/被依赖计数。"""
        c, _ = client
        rows = c.get("/studio/api/claims", headers=H).json()
        by_id = {r["claim_id"]: r for r in rows}
        assert by_id["c1"]["downstream"] == 1  # c3 依赖 c1
        assert by_id["c3"]["depends_on"] == 1
        assert by_id["c1"]["run_id"] == "run-src"

    def test_claim_detail_downstream(self, client) -> None:
        c, _ = client
        detail = c.get("/studio/api/claims/c1", headers=H).json()
        assert detail["claim"]["claim_id"] == "c1"
        assert detail["downstream"] == ["c3"]

    def test_unknown_claim_404(self, client) -> None:
        c, _ = client
        assert c.get("/studio/api/claims/ghost", headers=H).status_code == 404

    def test_conflicts_listing(self, client) -> None:
        """冲突清单（cognition 流重放 conflict_detected）。"""
        c, _ = client
        conflicts = c.get("/studio/api/conflicts", headers=H).json()
        assert len(conflicts) == 1
        assert set(conflicts[0]["claim_ids"]) == {"c1", "c2"}


class TestEvidenceDrill:
    def test_timeline_with_artifact_counts(self, client) -> None:
        c, _ = client
        tl = c.get("/studio/api/runs/run-src/timeline", headers=H).json()
        assert tl["total_events"] >= 1
        assert tl["events"][0]["type"] == "run.created"

    def test_timeline_unknown_404(self, client) -> None:
        c, _ = client
        assert c.get(
            "/studio/api/runs/run-x/timeline", headers=H).status_code == 404

    def test_repro_download_is_jsonl(self, client) -> None:
        """复现包下载（Epic 4 导出复用——逐行可解析）。"""
        c, _ = client
        r = c.get("/studio/api/runs/run-src/repro", headers=H)
        assert r.status_code == 200
        assert "jsonl" in r.headers["content-disposition"]
        first = json.loads(r.text.splitlines()[0])
        assert first["type"] == "run.created"

    def test_repro_unknown_404(self, client) -> None:
        c, _ = client
        assert c.get(
            "/studio/api/runs/run-x/repro", headers=H).status_code == 404


class TestImpactPreview:
    def test_impact_includes_downstream(self, client) -> None:
        """影响分析入口：环境升级受影响清单预览（含依赖传播，只读）。"""
        c, store = client
        before = len(list(store.iter_run_events("cognition")))
        r = c.get("/studio/api/impact", headers=H,
                  params={"k": "region", "v": "prod"}).json()
        ids = {x["claim_id"] for x in r["claims"]}
        assert ids == {"c1", "c2", "c3"}  # c3 经 depends_on 传播
        # 预览零副作用（ cognition 流无新事件）
        assert len(list(store.iter_run_events("cognition"))) == before

    def test_impact_empty_scope(self, client) -> None:
        c, _ = client
        r = c.get("/studio/api/impact", headers=H,
                  params={"k": "region", "v": "dev"}).json()
        assert r["count"] == 0


class TestExpertWrites:
    """写操作：事件留痕 + 批准流（UI 零旁路——全部断言事件流）。"""

    def test_review_approve_accepts_with_approval(self, client) -> None:
        c, store = client
        r = c.post("/studio/api/claims/c1/review", headers=H, json={
            "decision": "approve", "approver": "expert@corp",
            "reason": "领域规则确认"}).json()
        assert r["status"] == "accepted"
        assert r["approval_id"].startswith("apr-claim.review-")
        # 批准五要素入流（9.5 复用）
        approvals = [e for e in store.iter_run_events("approvals")
                     if e.type == "action.approval_record"]
        assert approvals[-1].payload["approver"] == "expert@corp"
        assert approvals[-1].payload["args"]["decision"] == "approve"
        # cognition 判定入流
        accepted = [e for e in store.iter_run_events("cognition")
                    if e.type == "claim.accepted"]
        assert accepted[-1].payload["claim_id"] == "c1"

    def test_review_reject_disputes(self, client) -> None:
        c, store = client
        r = c.post("/studio/api/claims/c2/review", headers=H, json={
            "decision": "reject", "approver": "expert@corp",
            "reason": "与实际业务不符"}).json()
        assert r["status"] == "disputed"
        disputed = [e for e in store.iter_run_events("cognition")
                    if e.type == "claim.disputed"]
        assert "domain-expert:expert@corp" in \
            disputed[-1].payload["counterevidence"][0]

    def test_review_terminal_claim_409_but_approval_traced(
            self, client) -> None:
        """终态主张拒审（状态机守卫）——但批准已留痕（审计真实）。"""
        c, store = client
        c.post("/studio/api/claims/c2/review", headers=H, json={
            "decision": "approve", "approver": "e", "reason": "r"})
        # c2 现为 disputed（活跃）——先经 cognition 推翻到终态
        import asyncio

        cog = CognitionService(store)
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            cog.refute("c2", ["test"]))
        r = c.post("/studio/api/claims/c2/review", headers=H, json={
            "decision": "approve", "approver": "e", "reason": "r"})
        assert r.status_code == 409
        approvals = [e for e in store.iter_run_events("approvals")
                     if e.type == "action.approval_record"]
        assert approvals[-1].payload["args"]["claim_id"] == "c2"

    def test_review_bad_body_400(self, client) -> None:
        c, _ = client
        assert c.post("/studio/api/claims/c1/review", headers=H, json={
            "decision": "maybe", "approver": "e"}).status_code == 400

    def test_annotate_leaves_trace(self, client) -> None:
        c, store = client
        r = c.post("/studio/api/claims/c3/annotate", headers=H, json={
            "note": "此主张仅在订单量>1000 时观察过",
            "annotator": "expert@corp"}).json()
        assert r["annotated"] is True
        events = [e for e in store.iter_run_events("cognition")
                  if e.type == "claim.annotated"]
        assert events[-1].payload["note"].startswith("此主张")

    def test_annotate_requires_fields(self, client) -> None:
        c, _ = client
        assert c.post("/studio/api/claims/c3/annotate", headers=H,
                      json={"note": ""}).status_code == 400
