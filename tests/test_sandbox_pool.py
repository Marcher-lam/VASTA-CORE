"""Story 9.14：沙箱池生产化（AD-6 Stage 3，G6）。

后端选型（容器优先/子进程回退降级标注）；池并发上限；
命令构造（网络关闭/限额/seccomp allowlist）。
"""

from __future__ import annotations

import pytest

from vasta_model_lab.pool import (
    DEFAULT_SYSCALL_ALLOWLIST,
    PodmanBackend,
    SandboxPool,
    SubprocessBackend,
    build_podman_command,
)
from vasta_protocols.errors import VastaError


class FakeBackend:
    """可编程后端（available/degraded/结果可注入）。"""

    def __init__(self, *, name="fake", available=True, degraded=False,
                 result=None, slow=False):
        self.name = name
        self.available = available
        self.degraded = degraded
        self.result = result or {"ok": True}
        self.slow = slow
        self.calls: list[str] = []

    async def execute(self, code, payload):
        self.calls.append(code)
        if self.slow:
            import asyncio

            await asyncio.sleep(0.05)
        return dict(self.result)


class TestPodmanCommand:
    def test_network_disabled_and_limits_present(self, tmp_path) -> None:
        """AC：rootless 容器——网络恒关 + 内存/PID/CPU 限额 +
        seccomp 系统调用 allowlist（profile JSON 路径形态——评审修复
        F11 后的合法语法）。"""

        profile = tmp_path / "seccomp.json"
        profile.write_text("{}", encoding="utf-8")
        cmd = build_podman_command(
            "img:1", mem_mb=256, pids_limit=16, cpu_s=1,
            seccomp_profile=profile)
        assert "--network=none" in cmd
        assert "--memory=256m" in cmd
        assert "--pids-limit=16" in cmd
        assert "--cpus=1" in cmd
        seccomp = cmd[cmd.index("--security-opt") + 1]
        assert seccomp == f"seccomp={profile}"

    def test_seccomp_profile_is_valid_whitelist_json(self) -> None:
        """profile 为 ERRNO 默认拒 + 白名单放行的合法 JSON。"""
        import json

        from vasta_model_lab.pool import seccomp_profile_json

        data = json.loads(seccomp_profile_json(("read", "write")))
        assert data["defaultAction"] == "SCMP_ACT_ERRNO"
        assert data["syscalls"][0]["names"] == ["read", "write"]
        assert data["syscalls"][0]["action"] == "SCMP_ACT_ALLOW"

    def test_default_syscall_allowlist_minimal(self) -> None:
        """默认 allowlist 不含高危面（exec/fork/socket/connect 拒于
        容器层）但含 CPython 必需调用（评审修复 F11 补集）。"""
        dangerous = {"execve", "execveat", "fork", "vfork", "clone",
                     "socket", "connect", "bind", "listen", "accept"}
        assert not dangerous & set(DEFAULT_SYSCALL_ALLOWLIST)
        for needed in ("rt_sigreturn", "newfstatat", "getdents64",
                       "getcwd", "uname"):
            assert needed in DEFAULT_SYSCALL_ALLOWLIST

    def test_podman_backend_static_check_applies(self, tmp_path) -> None:
        """评审修复 F11：容器后端静态 allowlist 前置（越权 import 拒
        于命令构造前——与子进程后端口径统一）。"""
        backend = PodmanBackend()
        with pytest.raises(VastaError):
            backend._prepare("import subprocess\nsubprocess.run(['ls'])")

    def test_lab_wiring_model_via_pool(self) -> None:
        """评审修复 M5：模型执行全经池——PythonWorldModel 直接收池
        （run_sync 接口；本机回退子进程后端，语义与直用 executor 一致）。"""
        from tests.test_model_lab import grid_manifest
        from vasta_model_lab import PythonWorldModel, make_sandbox_pool

        manifest = grid_manifest("pooled")
        model = PythonWorldModel(
            manifest, "result = {'x': state['x'] + 1}",
            sandbox=make_sandbox_pool())
        out = model.transition({"x": 41}, {"tool": "step"})
        assert out["x"] == 42

    def test_runtime_without_image_is_unavailable(self) -> None:
        """可用性=二进制且镜像在本地：GitHub runner 预装 podman 但无
        vasta 镜像——不得选中容器后端（否则把 localhost 镜像名当
        registry 拉取而 connection refused——2026-11-06 CI 实测）。"""
        backend = PodmanBackend(image="localhost/vasta-surely-missing:9")
        assert backend.available is False  # 镜像缺失 → 池回退子进程


class TestBackendSelection:
    async def test_prefers_container_over_subprocess(self) -> None:
        """选型：容器优先（非降级——无留痕事件）。"""
        events: list[tuple[str, dict]] = []

        async def emitter(type_, payload):
            events.append((type_, payload))

        pool = SandboxPool(
            backends=[FakeBackend(name="podman", degraded=False),
                      FakeBackend(name="subprocess", degraded=True)],
            emitter=emitter)
        assert pool.backend.name == "podman"
        await pool.run("code", {})
        assert events == []  # 正常选型零噪声

    async def test_unavailable_container_falls_back_degraded(self) -> None:
        """AC：Windows 开发档回退子进程并标注（incident.opened 留痕）。"""
        events: list[tuple[str, dict]] = []

        async def emitter(type_, payload):
            events.append((type_, payload))

        pool = SandboxPool(
            backends=[FakeBackend(name="podman", available=False),
                      FakeBackend(name="subprocess", degraded=True)],
            emitter=emitter)
        assert pool.backend.name == "subprocess"
        await pool.run("code", {})
        assert len(events) == 1
        assert events[0][0] == "incident.opened"
        assert events[0][1]["kind"] == "sandbox_degraded"
        # 标注只发一次（懒发——后续执行不重复）
        await pool.run("code2", {})
        assert len(events) == 1

    async def test_no_backend_rejected(self) -> None:
        with pytest.raises(VastaError) as excinfo:
            SandboxPool(backends=[FakeBackend(available=False)])
        assert excinfo.value.code == "sandbox.no_backend"

    async def test_podman_backend_unavailable_on_windows(self) -> None:
        """PodmanBackend 探测：运行时缺失 → available=False（池回退）。"""
        backend = PodmanBackend(runtime="definitely-not-a-runtime")
        assert backend.available is False


class TestPoolConcurrency:
    async def test_pool_exhaustion_rejected(self) -> None:
        """AC：池并发上限——超限显式拒（排队属 Stage 4）。"""
        import asyncio

        pool = SandboxPool(
            backends=[FakeBackend(slow=True)], max_size=2)

        async def job():
            return await pool.run("c", {})

        results = await asyncio.gather(
            job(), job(),  # 占满 2
            job(),  # 第 3 个 → 拒
            return_exceptions=True)
        errors = [r for r in results if isinstance(r, VastaError)]
        assert len(errors) == 1
        assert errors[0].code == "sandbox.pool_exhausted"

    async def test_slot_released_after_run(self) -> None:
        pool = SandboxPool(backends=[FakeBackend()], max_size=1)
        await pool.run("a", {})
        await pool.run("b", {})  # 槽位已归还

    async def test_bad_pool_size_rejected(self) -> None:
        with pytest.raises(VastaError):
            SandboxPool(backends=[FakeBackend()], max_size=0)


class TestSubprocessBackend:
    async def test_delegates_to_executor_semantics(self) -> None:
        """子进程回退沿用既有 SandboxExecutor 语义（静态模块 allowlist
        前置——越权代码在此拒绝）。"""
        backend = SubprocessBackend(timeout_s=2)
        assert backend.degraded is True
        with pytest.raises(VastaError):
            await backend.execute(
                "import subprocess\nsubprocess.run(['ls'])", {})

    async def test_allowed_code_executes(self) -> None:
        backend = SubprocessBackend(timeout_s=10)
        # 模型协议形态（与 test_model_lab 同款——result = 表达式，
        # payload 携 state/action）
        result = await backend.execute(
            "result = {'doubled': state['x'] * 2}",
            {"state": {"x": 21}, "action": {}})
        assert result["result"]["doubled"] == 42
