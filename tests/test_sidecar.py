"""Story 8.15：Sidecar 接入形态（FR-002 第五形态，蓝图 §18.5-4）。

单会话 loopback 伴生：token 全端点强制（healthz 除外）、写动作经
HTTP 走同一六段链、timeline/summary 可查、优雅关停关会话；子进程
形态经 ready-file 握手起停。
"""

from __future__ import annotations

import socket

import pytest

from _sidecar_usermod import (  # noqa: F401（自包含惯例：夹具同款复用）
    STATUS_CONTRACT,
    SetStatusTool,
    TodoEnv,
)
from vasta_protocols.errors import VastaError
from vastacore.execution.sidecar import (
    SidecarClient,
    SidecarProcess,
    SidecarServer,
    SidecarSpec,
)


def _spec() -> SidecarSpec:
    return SidecarSpec(
        env=TodoEnv(), tools=[SetStatusTool()],
        contracts={"set_status": STATUS_CONTRACT}, seed=7,
    )


class TestInProcessSidecar:
    async def test_full_loopback_contract(self, tmp_path) -> None:
        """AC：Agent 侧纯 HTTP——观察/写动作（六段链）/时间线/摘要/关停。"""
        server = SidecarServer(_spec())
        base = server.start()
        try:
            client = SidecarClient(base, server.token)
            health = client.healthz()
            assert health["ok"] is True
            assert health["run_id"]

            obs = client.observe()
            assert obs["detail"]["status"] == "pending"  # reset(seed=7) 后初始态

            result = client.act("set_status", {"status": "done"})
            assert result["ok"] is True
            assert result["verdict"] == "passed"

            types = [e["type"] for e in client.timeline()]
            assert "action.contracted" in types
            assert "action.executed" in types
            assert "verification.passed" in types  # 六段链与 SDK 同证据口径

            assert client.summary()["state"] in {"started", "running", "completed"}
            client.shutdown()
        finally:
            server.stop(timeout_s=15)

    async def test_token_required_on_data_plane(self) -> None:
        """数据面端点无 token → 401（healthz 豁免——无敏感数据）。"""
        server = SidecarServer(_spec())
        base = server.start()
        try:
            outsider = SidecarClient(base, "wrong-token")
            with pytest.raises(VastaError) as excinfo:
                outsider.act("set_status", {"status": "done"})
            assert "401" in str(excinfo.value.message)
            with pytest.raises(VastaError) as excinfo2:
                outsider.timeline()
            assert "401" in str(excinfo2.value.message)
            assert SidecarClient(base, "wrong-token").healthz()["ok"] is True
        finally:
            server.stop(timeout_s=15)

    async def test_loopback_only_and_ephemeral_port(self) -> None:
        """绑定 127.0.0.1 + 随机端口（单伴生不暴露网络面）。"""
        server = SidecarServer(_spec())
        server.start()
        try:
            host = server._server.servers[0].sockets[0].getsockname()[0]  # noqa: SLF001
            assert host == "127.0.0.1"
            with socket.socket() as s:  # 端口确实在听：connect 成功
                s.settimeout(5)
                s.connect(("127.0.0.1", server.port or 0))
            with socket.socket() as s2, pytest.raises(OSError):  # 再 bind 必拒
                s2.bind(("127.0.0.1", server.port or 0))
        finally:
            server.stop(timeout_s=15)

    async def test_act_body_shape_enforced(self) -> None:
        """缺 tool 键 → 422（HTTP 面对动作形状 fail-closed）。"""
        server = SidecarServer(_spec())
        base = server.start()
        try:
            client = SidecarClient(base, server.token)
            with pytest.raises(VastaError) as excinfo:
                client._call("POST", "/act", {"args": {}})
            assert "422" in str(excinfo.value.message)
        finally:
            server.stop(timeout_s=15)


class TestSubprocessSidecar:
    def test_spawn_ready_handshake_and_shutdown(self, tmp_path) -> None:
        """AC：子进程形态——ready-file 握手 → act 六段链 → 优雅关停退 0。"""
        proc = SidecarProcess.spawn(
            module="tests._sidecar_usermod:build",
            root=tmp_path / "sidecar-store",
            timeout_s=60,
        )
        try:
            client = proc.client
            assert client.healthz()["ok"] is True
            assert proc.ready["port"] > 0

            result = client.act("set_status", {"status": "done"})
            assert result["verdict"] == "passed"
            types = [e["type"] for e in client.timeline()]
            assert "verification.passed" in types
        finally:
            proc.close(timeout_s=15)
        assert proc._process.returncode == 0  # noqa: SLF001（优雅退出码）

    def test_store_persists_under_root(self, tmp_path) -> None:
        """证据落 root/store（与 Agent 进程同部署的本地库）。"""
        proc = SidecarProcess.spawn(
            module="tests._sidecar_usermod:build",
            root=tmp_path / "sidecar-store",
            timeout_s=60,
        )
        try:
            proc.client.act("set_status", {"status": "done"})
        finally:
            proc.close(timeout_s=15)
        store_dir = tmp_path / "sidecar-store" / "store"
        assert (store_dir).exists()
        assert any(store_dir.rglob("*.db")) or any(store_dir.rglob("*.sqlite*"))
