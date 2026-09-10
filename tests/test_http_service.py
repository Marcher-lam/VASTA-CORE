"""Story 8.3：HTTP 接入服务（FR-002，G1）。

令牌鉴权 / Run 全生命周期 / 证据查询 / 崩溃安全（服务层不旁路 AD-2）。
测试复用 test_agent_sdk 的 TodoEnv/SetStatusTool 作为服务端预设。
"""

from __future__ import annotations

import pytest

from .test_agent_sdk import STATUS_CONTRACT, SetStatusTool, TodoEnv


def make_client(tmp_path, token="secret-token"):
    from fastapi.testclient import TestClient

    from vastacore.service import create_app

    app = create_app(
        env_factory=TodoEnv,
        tools=[SetStatusTool()],
        contracts={"set_status": STATUS_CONTRACT},
        root=tmp_path,
        token=token,
    )
    return TestClient(app), tmp_path / "store"


H = {"Authorization": "Bearer secret-token"}


@pytest.fixture
def client(tmp_path):
    c, root = make_client(tmp_path)
    yield c
    c.app.state.service.close()


def _new_run(c, seed=7) -> str:
    r = c.post("/runs", json={"seed": seed}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()["run_id"]


class TestAuth:
    def test_missing_or_wrong_token_401(self, client) -> None:
        assert client.get("/runs/x/summary").status_code == 401
        assert client.get(
            "/runs/x/summary", headers={"Authorization": "Bearer wrong"}
        ).status_code == 401

    def test_endpoints_reachable_with_token(self, client) -> None:
        run_id = _new_run(client)
        assert client.get(f"/runs/{run_id}/summary", headers=H).status_code == 200


class TestLifecycle:
    def test_full_run_over_http(self, client) -> None:
        """run 创建→start→reset→act（六段链）→complete→summary。"""
        run_id = _new_run(client)
        assert client.post(f"/runs/{run_id}/start", headers=H).status_code == 200
        assert client.post(f"/runs/{run_id}/reset", json={"seed": 7},
                           headers=H).status_code == 200
        act = client.post(
            f"/runs/{run_id}/act",
            json={"tool": "set_status", "args": {"status": "done"}},
            headers=H,
        )
        assert act.status_code == 200, act.text
        assert len(act.json()["observations"]) >= 1
        assert client.post(f"/runs/{run_id}/complete", headers=H).status_code == 200
        summary = client.get(f"/runs/{run_id}/summary", headers=H).json()
        assert summary["state"] == "completed"
        assert summary["events"] >= 8

    def test_act_writes_six_segment_events(self, client) -> None:
        """AD-2：服务层动作经 AgentSession→execute_contracted，六段落事件。"""
        run_id = _new_run(client)
        client.post(f"/runs/{run_id}/start", headers=H)
        client.post(f"/runs/{run_id}/reset", headers=H)
        client.post(f"/runs/{run_id}/act",
                    json={"tool": "set_status", "args": {"status": "done"}},
                    headers=H)
        tl = client.get(f"/runs/{run_id}/timeline", headers=H).json()
        types = [e["type"] for e in tl["entries"]]
        assert "action.contracted" in types
        assert "action.executed" in types
        assert "verification.passed" in types

    def test_registered_without_template_fails_closed_400(
        self, tmp_path
    ) -> None:
        """评审修复后的真守卫：注册网关但缺契约模板 → 精确 400 +
        contract_template_missing（原先 in (200,400) 恒真，零回归保护）。"""
        from fastapi.testclient import TestClient

        from vastacore.service import create_app

        from .test_agent_sdk import SetStatusTool, TodoEnv

        app = create_app(
            env_factory=TodoEnv, tools=[SetStatusTool()],
            contracts={},  # 注册了工具但无模板——fail-closed 目标场景
            root=tmp_path, token="secret-token",
        )
        with TestClient(app) as c:
            hh = {"Authorization": "Bearer secret-token"}
            run_id = c.post("/runs", json={"seed": 1}, headers=hh).json()["run_id"]
            c.post(f"/runs/{run_id}/start", headers=hh)
            c.post(f"/runs/{run_id}/reset", headers=hh)
            r = c.post(f"/runs/{run_id}/act",
                       json={"tool": "set_status", "args": {"status": "done"}},
                       headers=hh)
            assert r.status_code == 400, (r.status_code, r.text)
            assert "无契约模板" in r.json()["detail"] and "fail-closed" in r.json()["detail"]
            # 对照：未注册工具走观察路径（200）——两种路径区分明确
            r2 = c.post(f"/runs/{run_id}/act",
                        json={"tool": "unknown_tool", "args": {}}, headers=hh)
            assert r2.status_code == 200

    def test_unknown_run_404(self, client) -> None:
        assert client.post("/runs/nope/start", headers=H).status_code == 404
        assert client.get("/runs/nope/timeline", headers=H).status_code == 404


class TestEvidenceQuery:
    def test_timeline_full_coverage(self, client) -> None:
        run_id = _new_run(client)
        client.post(f"/runs/{run_id}/start", headers=H)
        client.post(f"/runs/{run_id}/reset", headers=H)
        tl = client.get(f"/runs/{run_id}/timeline", headers=H).json()
        assert tl["total_events"] == len(tl["entries"])  # covers_all_events
        assert tl["run_id"] == run_id

    def test_search_by_tool(self, client) -> None:
        run_id = _new_run(client)
        client.post(f"/runs/{run_id}/start", headers=H)
        client.post(f"/runs/{run_id}/reset", headers=H)
        client.post(f"/runs/{run_id}/act",
                    json={"tool": "set_status", "args": {"status": "done"}},
                    headers=H)
        hits = client.get("/evidence/search",
                          params={"run_id": run_id, "tool": "set_status"},
                          headers=H).json()
        assert len(hits) >= 2  # contracted + executed


class TestCrashSafety:
    def test_evidence_survives_service_dispose(self, tmp_path) -> None:
        """AC：服务崩溃不丢已落盘证据——dispose 后新进程读同根目录。"""
        from vasta_storage import SqliteStorage, timeline
        from vastacore.service import create_app

        app = create_app(
            env_factory=TodoEnv, tools=[SetStatusTool()],
            contracts={"set_status": STATUS_CONTRACT},
            root=tmp_path, token="t",
        )
        from fastapi.testclient import TestClient

        hh = {"Authorization": "Bearer t"}
        with TestClient(app) as c:
            run_id = c.post("/runs", json={"seed": 1}, headers=hh).json()["run_id"]
            c.post(f"/runs/{run_id}/start", headers=hh)
            c.post(f"/runs/{run_id}/reset", headers=hh)
            c.post(f"/runs/{run_id}/act",
                   json={"tool": "set_status", "args": {"status": "done"}},
                   headers=hh)
        # 服务已关（未 complete，模拟崩溃）——新开 store 直接读
        store = SqliteStorage(tmp_path / "store")
        events = list(store.iter_run_events(run_id))
        assert len(events) >= 6  # 证据完好
        assert timeline(events).covers_all_events
        store.close()

    def test_restart_serves_history_runs(self, tmp_path) -> None:
        """重启后对历史 run 的 timeline/search 仍可用（读存储非内存）。"""
        run_id = None
        c1, _ = make_client(tmp_path)
        with c1:
            run_id = _new_run(c1)
            c1.post(f"/runs/{run_id}/start", headers=H)
            c1.post(f"/runs/{run_id}/reset", headers=H)
        c2, _ = make_client(tmp_path)  # 同根目录重启
        with c2:
            tl = c2.get(f"/runs/{run_id}/timeline", headers=H)
            assert tl.status_code == 200
            assert tl.json()["total_events"] >= 3


class TestOpsEndpoints:
    """Story 9.12：运维基线端点（/healthz /readyz /metrics）。"""

    def test_healthz_liveness_anonymous(self, client) -> None:
        """AC：活性探针——匿名（K8s probe 场景），只回进程状态。"""
        r = client.get("/healthz")  # 无 token
        assert r.status_code == 200
        assert r.json()["status"] == "alive"

    def test_readyz_ready_when_store_alive(self, client) -> None:
        """AC：就绪探针——存储心跳通过即 ready。"""
        r = client.get("/readyz")
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

    def test_readyz_503_when_store_down(self, tmp_path) -> None:
        """存储故障 → 503 未就绪。"""
        c, _ = make_client(tmp_path)
        with c:
            c.app.state.service.store.close()  # 模拟存储故障
            r = c.get("/readyz")
            assert r.status_code == 503
            assert "not ready" in r.json()["detail"]

    def test_metrics_requires_token(self, client) -> None:
        """指标端点带 token（泄露内部数据——匿名拒）。"""
        assert client.get("/metrics").status_code == 401
        assert client.get("/metrics", headers=H).status_code == 200

    def test_metrics_snapshot_and_alerts(self, client) -> None:
        """指标快照 + 告警评估（基线规则内联）。"""
        r = client.get("/metrics", headers=H)
        body = r.json()
        assert set(body["metrics"]) >= {"error_rate", "queue_depth",
                                        "quota_throttled"}
        assert isinstance(body["alerts"], list)
