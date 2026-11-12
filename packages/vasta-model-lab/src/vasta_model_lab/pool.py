"""沙箱池生产化（Story 9.14，AD-6 Stage 3 升级点，G6）。

- 后端抽象（SandboxBackend）：rootless 容器（Podman 类——网络关闭/
  内存/PID 限额/seccomp 系统调用 allowlist）为主，**受限子进程为
  Windows 开发档回退**（显式降级——sandbox.backend_selected 事件
  标注 degraded，AD-6「MVP 子进程非生产边界」的诚实延续）；
- SandboxPool：构造期后端选型（首个可用者）+ 池并发上限
  （max_size——超限拒 sandbox.pool_exhausted）+ 选型/降级留痕；
- 模块 allowlist：静态检查沿 ALLOWED_IMPORTS（既有）；系统调用
  allowlist：容器后端配置（seccomp profile 参数——注入测试断言
  传参；真实执行需容器运行时，开发档自动回退子进程）。
"""

from __future__ import annotations

import contextlib
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from vasta_protocols.errors import VastaError

#: 生产档默认系统调用 allowlist（容器 seccomp 白名单——最小集 +
#: CPython 运行必需：评审修复 F11 补 newfstatat/statx/getdents64/
#: getcwd/uname/rt_sigreturn——原缺集连 python3 启动/IO 都不可完成）。
DEFAULT_SYSCALL_ALLOWLIST: tuple[str, ...] = (
    "read", "write", "open", "close", "fstat", "lseek", "mmap",
    "mprotect", "munmap", "brk", "rt_sigaction", "rt_sigprocmask",
    "rt_sigreturn",
    "ioctl", "pread64", "pwrite64", "readv", "writev", "access",
    "newfstatat", "statx", "getdents64", "getcwd", "uname",
    "exit", "exit_group", "getpid", "gettid", "futex", "nanosleep",
    "clock_gettime", "getrandom", "dup", "dup2", "pipe",
)

#: 基线系统调用集（seccomp default 允许面之外显式追加）。
BaseEmitter = Callable[[str, dict[str, Any]], Any]


def seccomp_profile_json(syscall_allowlist: tuple[str, ...]) -> str:
    """seccomp profile JSON（评审修复 F11：``seccomp=allowlist:...``
    非法语法——Podman/Docker 只接受 profile JSON 路径；白名单模式
    defaultAction=ERRNO + names 白名单）。"""
    import json

    return json.dumps({
        "defaultAction": "SCMP_ACT_ERRNO",
        "architectures": ["SCMP_ARCH_X86_64", "SCMP_ARCH_X86"],
        "syscalls": [{
            "names": sorted(syscall_allowlist),
            "action": "SCMP_ACT_ALLOW",
        }],
    })


def build_podman_command(
    image: str, *,
    mem_mb: int, pids_limit: int, cpu_s: int,
    seccomp_profile: Path,
) -> list[str]:
    """rootless 容器命令构造（纯函数——可测；网络恒关闭；
    seccomp 为 profile JSON 路径——F11）。"""
    return [
        "podman", "run", "--rm", "--network=none",
        f"--memory={mem_mb}m", f"--pids-limit={pids_limit}",
        f"--cpus={cpu_s}",
        "--security-opt", f"seccomp={seccomp_profile}",
        image,
    ]


class SandboxBackend(Protocol):
    """沙箱后端协议（name/execute；实现自证资源边界）。"""

    name: str
    degraded: bool  # True=开发档回退（非生产边界）

    async def execute(
        self, code: str, payload: dict[str, Any],
    ) -> dict[str, Any]: ...


class PodmanBackend:
    """rootless 容器后端（Podman 类——生产边界）。

    命令构造经 ``build_podman_command``（纯函数可测）；真实执行需
    容器运行时（构造期探测，缺失即抛 sandbox.backend_unavailable
    ——由池选型回退，不静默降级）。"""

    def __init__(
        self, *,
        image: str = "localhost/vasta-sandbox:latest",
        mem_mb: int = 128, pids_limit: int = 32, cpu_s: int = 2,
        timeout_s: float = 5.0,
        syscall_allowlist: tuple[str, ...] = DEFAULT_SYSCALL_ALLOWLIST,
        runtime: str = "podman",
    ) -> None:
        # 可用性=运行时二进制 **且** 镜像在本地（GitHub runner 预装
        # podman 但无 vasta 镜像——只探二进制会选中容器后端后把
        # localhost 镜像名当远端 registry 拉取而 connection refused，
        # 2026-11-06 CI 实测）。探测失败面统一 unavailable（池回退
        # 子进程并留痕降级——设计语义不变）。
        self._available = self._probe(runtime, image)
        self.name = "podman"
        self.degraded = False
        self.image = image
        self.mem_mb = mem_mb
        self.pids_limit = pids_limit
        self.cpu_s = cpu_s
        self.timeout_s = timeout_s
        self.syscall_allowlist = tuple(syscall_allowlist)
        self.runtime = runtime

    @staticmethod
    def _probe(runtime: str, image: str) -> bool:
        """运行时 + 镜像双探测（探测即执行一次快速子命令，失败/超时
        /无二进制一律 unavailable——fail-safe 不阻塞池装配）。"""
        import subprocess

        if shutil.which(runtime) is None:
            return False
        probe_cmd = (
            [runtime, "image", "exists", image] if runtime == "podman"
            else [runtime, "image", "inspect", image]
        )
        try:
            proc = subprocess.run(  # noqa: S603
                probe_cmd, capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0

    @property
    def available(self) -> bool:
        return self._available

    def command(self) -> list[str]:
        """命令构造（seccomp profile 写临时文件传路径——F11）。"""
        import tempfile

        profile = Path(tempfile.gettempdir()) / "vasta-seccomp.json"
        profile.write_text(
            seccomp_profile_json(self.syscall_allowlist), encoding="utf-8")
        return build_podman_command(
            self.image, mem_mb=self.mem_mb, pids_limit=self.pids_limit,
            cpu_s=self.cpu_s, seccomp_profile=profile)

    def _prepare(self, code: str) -> list[str]:
        """静态 allowlist 前置（评审修复 F11：容器后端曾跳过——与
        子进程后端口径统一，越权 import 在命令构造前即拒）。"""
        from .sandbox import _static_check

        _static_check(code)
        return [*self.command(), "python3", "-c", code]

    async def execute(
        self, code: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        import asyncio
        import json

        if not self._available:
            raise VastaError(
                code="sandbox.backend_unavailable",
                message="podman 运行时不可用（构造期应已回退——池选型错误）",
            )
        cmd = self._prepare(code)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,  # 评审修复 F11：payload 注入
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:  # noqa: BLE001 ——容器启动故障统一包装
            raise VastaError(
                code="sandbox.spawn_failed",
                message=f"容器启动失败：{exc}",
            ) from exc
        try:  # 评审修复 F11：超时墙钟——挂死容器 kill 回收（槽位不泄漏）
            out, err = await asyncio.wait_for(
                proc.communicate(
                    input=json.dumps(payload).encode("utf-8")),
                timeout=self.timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise VastaError(
                code="sandbox.timeout",
                message=f"容器执行超时（>{self.timeout_s}s，真实墙钟）",
            ) from None
        if proc.returncode != 0:
            raise VastaError(
                code="sandbox.execution_failed",
                message=f"容器内执行失败：{err.decode(errors='replace')[:200]}",
            )
        try:
            return dict(json.loads(out.decode("utf-8")))
        except (ValueError, UnicodeDecodeError) as exc:
            raise VastaError(
                code="sandbox.bad_output",
                message=f"容器输出非 JSON：{exc}",
            ) from exc

    def execute_sync(
        self, code: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        """同步路径（Lab 同步 transition 钩子——SandboxPool.run_sync 转发）。"""
        import json
        import subprocess

        cmd = self._prepare(code)
        try:
            proc = subprocess.run(  # noqa: S603
                cmd, input=json.dumps(payload).encode("utf-8"),
                capture_output=True, timeout=self.timeout_s)
        except subprocess.TimeoutExpired as exc:
            raise VastaError(
                code="sandbox.timeout",
                message=f"容器执行超时（>{self.timeout_s}s）",
            ) from exc
        if proc.returncode != 0:
            raise VastaError(
                code="sandbox.execution_failed",
                message=proc.stderr.decode(errors="replace")[-200:],
            )
        return dict(json.loads(proc.stdout.decode("utf-8")))


class SubprocessBackend:
    """受限子进程回退（Windows 开发档——**非生产边界**，降级标注）。

    语义与既有 SandboxExecutor 一致（CPU/内存/超时/最小环境/静态
    模块 allowlist）；`degraded=True` 由池在选型时留痕。"""

    def __init__(self, **executor_kwargs: Any) -> None:
        from .sandbox import SandboxExecutor

        self.name = "subprocess"
        self.degraded = True
        self._executor = SandboxExecutor(**executor_kwargs)

    async def execute(
        self, code: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._executor.run(code, payload)


class SandboxPool:
    """沙箱池：后端选型（容器优先/子进程回退）+ 并发上限 + 选型留痕。

    模型执行**全经池**（Lab 装配面）：run() 内 acquire/release 计数，
    超过 max_size 拒（sandbox.pool_exhausted——排队属 Stage 4）。"""

    def __init__(
        self, *,
        backends: list[Any] | None = None,
        max_size: int = 4,
        emitter: BaseEmitter | None = None,
    ) -> None:
        if max_size < 1:
            raise VastaError(
                code="sandbox.bad_pool_size",
                message=f"max_size 须 ≥1（得到 {max_size}）",
            )
        candidates = backends if backends is not None else [
            PodmanBackend(), SubprocessBackend()]
        selected: Any | None = None
        for backend in candidates:
            if not getattr(backend, "available", True):
                continue  # 显式不可用（如 Windows 无 podman）→ 下一个
            selected = backend
            break
        if selected is None:
            raise VastaError(
                code="sandbox.no_backend",
                message="全部沙箱后端不可用（容器缺失且未提供回退）",
            )
        self.backend = selected
        self.max_size = max_size
        self.emitter = emitter
        self.in_use = 0
        self._announced = False  # 降级标注懒发（构造期无事件循环）

    async def _emit_selected(self) -> None:
        """选型留痕：**仅降级时**（AD-6「子进程非生产边界」诚实标注——
        正常容器选型无事件，避免噪声；事件族走 incident——与沙箱越权/
        熔断开闸同形态，AD-5 13 族封闭集内）。"""
        if self.emitter is None or not self.backend.degraded:
            return
        with contextlib.suppress(Exception):  # 留痕失败不掩盖选型
            maybe = self.emitter("incident.opened", {
                "kind": "sandbox_degraded",
                "backend": self.backend.name,
                "note": "rootless 容器不可用——回退受限子进程"
                        "（开发档，非生产边界）",
            })
            import asyncio as _aio

            if _aio.iscoroutine(maybe):
                await maybe

    def run_sync(self, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        """同步执行（Lab 同步 transition 钩子接线——评审修复 M5：
        ``PythonWorldModel(sandbox=池)`` 即「模型执行全经池」）。"""
        execute_sync = getattr(self.backend, "execute_sync", None)
        if callable(execute_sync):
            return execute_sync(code, payload)
        # 后端无同步面（测试替身）——退 async run（新循环；生产后端
        # 均有同步面）
        import asyncio

        return asyncio.run(self.run(code, payload))

    async def run(self, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        """经池执行（模块 allowlist 由后端静态检查承载；系统调用
        allowlist 由容器后端 seccomp 配置承载）。"""
        if not self._announced:
            self._announced = True
            await self._emit_selected()  # 首次执行时降级标注一次
        if self.in_use >= self.max_size:
            raise VastaError(
                code="sandbox.pool_exhausted",
                message=f"沙箱池满（{self.in_use}/{self.max_size}）"
                        "——排队属 Stage 4，当前显式拒",
            )
        self.in_use += 1
        try:
            return await self.backend.execute(code, payload)
        finally:
            self.in_use -= 1


def make_sandbox_pool(**pool_kwargs: Any) -> SandboxPool:
    """Lab 装配面默认池（评审修复 M5：模型执行全经池的接线入口——
    ``PythonWorldModel(..., sandbox=make_sandbox_pool())``；容器优先/
    开发档回退/并发上限/降级留痕一次到位）。"""
    return SandboxPool(**pool_kwargs)


__all__ = ["DEFAULT_SYSCALL_ALLOWLIST", "PodmanBackend", "SandboxBackend",
           "SandboxPool", "SubprocessBackend", "build_podman_command",
           "make_sandbox_pool", "seccomp_profile_json"]
