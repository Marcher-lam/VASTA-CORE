"""沙箱执行器（Story 6.2，AD-6/15）——受限子进程 + 超时留痕。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from vasta_protocols.errors import VastaError

from .python_model import _static_check

#: 事件发射钩子：(event_type, payload) -> Awaitable[None]（AD-15 留痕）。
EventEmitter = Callable[[str, dict[str, Any]], Awaitable[None]]



_SANDBOX_WRAPPER = '''
import json, sys, math, itertools, collections
try:
    import resource
    def _lower(res, value):
        # 降限尽力而为、按资源独立：Linux 全额生效；darwin 内核对
        # RLIMIT_AS 的 setrlimit 直接 EINVAL（不支持地址空间限额）、且
        # hard 不得一步降到 soft 之下（先降 soft 再降 hard）；Windows 走
        # ImportError。失败面由真实墙钟超时兜底（AD-6 记录边界）。
        _soft, _hard = resource.getrlimit(res)
        try:
            if _soft == resource.RLIM_INFINITY or _soft > value:
                resource.setrlimit(res, (value, _hard))
            resource.setrlimit(res, (value, value))
        except (ValueError, OSError):
            pass
    def _as_growth_cap(mem_bytes):
        # RLIMIT_AS 限的是**虚拟地址空间总量**，而 CPython 启动足迹
        # （x86_64 Linux VmSize 约 200-320MB，RSS 仅 ~20MB）远超业务
        # 内存预算——按预算直接设总上限会在真 x86_64 上杀死解释器
        # 启动（GitHub Actions 实测六连红）。改为**增长量上限**：
        # 上限 = 当前 VmSize 基线 + 预算——超预算的分配增长仍被杀
        # （mem_mb 语义不变），解释器在任何 Linux 架构可启动。
        # 无 /proc/self/status（非 Linux）→ None → 不设 AS 卡（墙钟兜底）。
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmSize:"):
                        return int(line.split()[1]) * 1024 + mem_bytes
        except (OSError, ValueError, IndexError):
            pass
        return None
    _lower(resource.RLIMIT_CPU, __CPU_S__)
    _as_cap = _as_growth_cap(__MEM_BYTES__)
    if _as_cap is not None:
        _lower(resource.RLIMIT_AS, _as_cap)
except ImportError:
    pass  # Windows 无 resource——CPU/内存限额由超时墙钟兜底（AD-6 记录边界）
data = json.loads(sys.stdin.read())
state, action = data["state"], data["action"]
__BODY__
sys.stdout.write(json.dumps({"ok": True, "result": result if "result" in dir() else None}))
'''


def _sandbox_env() -> dict[str, str]:
    """最小化子进程环境（供给点实现，见 _bookkeeping_stub）。"""
    from ._bookkeeping_stub import sandbox_subprocess_env

    return sandbox_subprocess_env()


class SandboxExecutor:
    """受限子进程沙箱：CPU/内存限额、无网络（MVP）、超时墙钟、最小环境。

    AD-15：超时用真实墙钟（wait_for / subprocess timeout），触发时经
    emitter 落 system.timeout 事件（由调用方注入存储路径）。
    AD-6：MVP 子进程非生产边界（rootless 容器 Stage 3）。"""

    def __init__(
        self,
        *,
        timeout_s: float = 5.0,
        cpu_s: int = 2,
        mem_mb: int = 128,
        emitter: EventEmitter | None = None,
    ) -> None:
        self.timeout_s = timeout_s
        self.cpu_s = cpu_s
        self.mem_mb = mem_mb
        self.emitter = emitter

    def _wrap(self, code: str) -> str:
        _static_check(code)  # 评审修复：子进程路径同样前置静态检查
        return (
            _SANDBOX_WRAPPER
            .replace("__CPU_S__", str(self.cpu_s))
            .replace("__MEM_BYTES__", str(self.mem_mb * 1024 * 1024))
            .replace("__BODY__", code)
        )

    async def _emit_timeout(self, code: str) -> None:
        if self.emitter is not None:
            with contextlib.suppress(Exception):  # 留痕失败不掩盖超时本体
                await self.emitter(
                    "system.timeout",
                    {"source": "sandbox", "timeout_s": self.timeout_s,
                     "code_head": code[:120]},
                )

    async def _emit_incident(self, payload: dict[str, Any]) -> None:
        """越权/异常留痕（AC-06「失败且有审计」；留痕失败不掩盖本体）。"""
        if self.emitter is not None:
            with contextlib.suppress(Exception):
                await self.emitter("incident.opened", payload)

    async def run(self, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            wrapped = self._wrap(code)  # 静态检查在此拒绝越权代码
        except VastaError as exc:
            await self._emit_incident(
                {"source": "sandbox", "reason": exc.code, "code_head": code[:120]}
            )
            raise
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", wrapped,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_sandbox_env(),
            )
        except Exception as exc:
            raise VastaError(
                code="sandbox.spawn_failed",
                message=f"沙箱子进程启动失败: {exc}",
            ) from exc
        try:
            stdin_data = json.dumps(payload).encode("utf-8")
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_data), timeout=self.timeout_s
            )
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()  # 评审修复：回收进程，防僵尸
            await self._emit_timeout(code)
            raise VastaError(
                code="sandbox.timeout",
                message=f"沙箱执行超时（>{self.timeout_s}s，真实墙钟）",
            ) from exc
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace")[-300:]
            raise VastaError(
                code="sandbox.execution_failed",
                message=f"沙箱进程退出码 {proc.returncode}: {err}",
            )
        try:
            return json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise VastaError(
                code="sandbox.bad_output",
                message=f"沙箱输出不可解析: {exc}",
            ) from exc

    def run_sync(self, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        """同步沙箱路径（供同步 transition 钩子；与 run 同一包装/限额/检查）。"""
        wrapped = self._wrap(code)
        try:
            proc = subprocess.run(  # noqa: S603
                [sys.executable, "-c", wrapped],
                input=json.dumps(payload).encode("utf-8"),
                capture_output=True,
                timeout=self.timeout_s,
                env=_sandbox_env(),
            )
        except subprocess.TimeoutExpired as exc:
            raise VastaError(
                code="sandbox.timeout",
                message=f"沙箱执行超时（>{self.timeout_s}s，真实墙钟）",
            ) from exc
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace")[-300:]
            raise VastaError(
                code="sandbox.execution_failed",
                message=f"沙箱进程退出码 {proc.returncode}: {err}",
            )
        try:
            return json.loads(proc.stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise VastaError(
                code="sandbox.bad_output",
                message=f"沙箱输出不可解析: {exc}",
            ) from exc


