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
import sys
from collections.abc import Callable
from typing import Any, Protocol

from vasta_protocols.errors import VastaError

#: 生产档默认系统调用 allowlist（容器 seccomp 白名单——最小集）。
DEFAULT_SYSCALL_ALLOWLIST: tuple[str, ...] = (
    "read", "write", "open", "close", "fstat", "lseek", "mmap",
    "mprotect", "munmap", "brk", "rt_sigaction", "rt_sigprocmask",
    "ioctl", "pread64", "pwrite64", "readv", "writev", "access",
    "exit", "exit_group", "getpid", "gettid", "futex", "nanosleep",
    "clock_gettime", "getrandom",
)

#: 基线系统调用集（seccomp default 允许面之外显式追加）。
BaseEmitter = Callable[[str, dict[str, Any]], Any]


def build_podman_command(
    image: str, *,
    mem_mb: int, pids_limit: int, cpu_s: int,
    syscall_allowlist: tuple[str, ...],
) -> list[str]:
    """rootless 容器命令构造（纯函数——可测；网络恒关闭）。"""
    return [
        "podman", "run", "--rm", "--network=none",
        f"--memory={mem_mb}m", f"--pids-limit={pids_limit}",
        f"--cpus={cpu_s}",
        # seccomp：仅放行 allowlist（Docker/Podman 兼容 JSON 经 stdin 传
        # 亦可；命令行安全档取 default+allowlist 交集语义由运行时承载）
        "--security-opt",
        "seccomp=allowlist:" + ",".join(syscall_allowlist),
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
        syscall_allowlist: tuple[str, ...] = DEFAULT_SYSCALL_ALLOWLIST,
        runtime: str = "podman",
    ) -> None:
        if shutil.which(runtime) is None and sys.platform == "win32":
            # Windows 开发档：显式不可用（池会回退子进程并留痕降级）
            self._available = False
        else:
            self._available = shutil.which(runtime) is not None
        self.name = "podman"
        self.degraded = False
        self.image = image
        self.mem_mb = mem_mb
        self.pids_limit = pids_limit
        self.cpu_s = cpu_s
        self.syscall_allowlist = tuple(syscall_allowlist)
        self.runtime = runtime

    @property
    def available(self) -> bool:
        return self._available

    def command(self) -> list[str]:
        return build_podman_command(
            self.image, mem_mb=self.mem_mb, pids_limit=self.pids_limit,
            cpu_s=self.cpu_s, syscall_allowlist=self.syscall_allowlist)

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
        cmd = [*self.command(), "python3", "-c", code]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:  # noqa: BLE001——容器启动故障统一包装
            raise VastaError(
                code="sandbox.spawn_failed",
                message=f"容器启动失败：{exc}",
            ) from exc
        out, err = await proc.communicate()
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


__all__ = ["DEFAULT_SYSCALL_ALLOWLIST", "PodmanBackend", "SandboxBackend",
           "SandboxPool", "SubprocessBackend", "build_podman_command"]
