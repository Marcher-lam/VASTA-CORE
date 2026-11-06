"""Sidecar 接入形态（Story 8.15，FR-002 第五形态，蓝图 §18.5-4）。

与单个 Agent 进程同部署的本地伴生：Agent 侧任意语言、只说 HTTP；
sidecar 侧持有 AgentSession + 证据库，每个写动作走同一六段链。

与 ops.service（HTTP 服务形态，Story 8.3）的边界：
- service = 控制面：多会话、共享 token/RBAC、面向中心化部署；
- sidecar = 单伴生：单会话、loopback-only、启动即自动生成一次性
  token、生命周期与 Agent 进程同进退（spawn → ready → close）。

两种起法：
- 子进程（生产形态）：``python -m vastacore.execution.sidecar --module
  myagent:build --root .vasta-sidecar --ready-file <path>``——用户模块
  提供 ``build() -> SidecarSpec``；``SidecarProcess.spawn(...)`` 封装
  起停与就绪等待；
- 进程内线程（测试/嵌入）：``SidecarServer`` 在后台线程跑 uvicorn，
  同一 HTTP 契约。

客户端 ``SidecarClient`` 纯 stdlib（urllib）——Agent 侧无 Python 依赖，
其他语言照抄 HTTP 即可。
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import EnvironmentAdapter, ToolAdapter

from .agent import AgentSession, ContractTemplate

_VERIFICATION_TYPES = {
    "verification.passed": "passed",
    "verification.deviated": "deviated",
    "verification.inconclusive": "inconclusive",
    "verification.errored": "errored",
}


@dataclass
class SidecarSpec:
    """用户模块 ``build()`` 的返回：sidecar 侧的接入物。

    ``session_factory`` 优先（进程内形态完全自控装配）；否则由
    env/tools/contracts 经 ``AgentSession.create`` 装配（与 SDK 形态
    同一构造面）。
    """

    env: EnvironmentAdapter | None = None
    tools: list[ToolAdapter] = field(default_factory=list)
    contracts: dict[str, ContractTemplate] = field(default_factory=dict)
    seed: int | None = None
    run_id: str | None = None
    budget: dict[str, int] | None = None
    session_factory: Callable[[], Awaitable[AgentSession]] | None = None


def build_sidecar_app(spec: SidecarSpec, *, token: str) -> Any:
    """装配单会话最小面。

    - token 全端点强制（/healthz 除外——不含敏感数据）；
    - 生命周期：startup 装配会话（start+reset）→ shutdown 关会话；
      （端口不经此处暴露——子进程形态由 ``_main`` 预绑 socket 先写
      ready-file，父进程以 healthz 轮询确认会话就绪）；
    - 关停：POST /shutdown 置 server.should_exit（uvicorn 优雅退出）。
    """
    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        if spec.session_factory is not None:
            session = await spec.session_factory()
        else:
            if spec.env is None:
                raise VastaError(
                    code="sidecar.spec_empty",
                    message="SidecarSpec 需提供 env（或 session_factory）",
                )
            session = await AgentSession.create(
                env=spec.env, tools=list(spec.tools),
                contracts=dict(spec.contracts), root=app.state.root,
                seed=spec.seed, run_id=spec.run_id, budget=spec.budget,
            )
        await session.start()
        await session.reset(spec.seed)
        app.state.session = session
        yield
        session = getattr(app.state, "session", None)
        if session is not None:
            session.close()
            app.state.session = None

    app = FastAPI(title="VastaCore Sidecar", lifespan=_lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.root = ".vasta-sidecar"
    app.state.server = None
    app.state.session = None

    def require_token(request: Request) -> None:
        import hmac

        auth = request.headers.get("Authorization", "")
        if not hmac.compare_digest(auth, f"Bearer {token}"):
            raise HTTPException(status_code=401, detail="invalid token")

    guarded = Depends(require_token)

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        session: AgentSession | None = app.state.session
        return {"ok": session is not None,
                "run_id": session.run_id if session else None}

    @app.post("/observe", dependencies=[guarded])
    async def observe() -> dict[str, Any]:
        obs = await app.state.session.observe()
        return obs.model_dump(mode="json")

    @app.post("/act", dependencies=[guarded])
    async def act(body: dict[str, Any]) -> dict[str, Any]:
        if "tool" not in body:
            raise HTTPException(status_code=422, detail="body 缺 'tool' 键")
        from vasta_protocols.protocols import Action

        observations = await app.state.session.act(
            Action(tool=str(body["tool"]), args=dict(body.get("args") or {})),
            goal=body.get("goal"),
        )
        verdict = None
        for event in app.state.session.events():
            mapped = _VERIFICATION_TYPES.get(event.type)
            if mapped:
                verdict = mapped
        return {
            "ok": True,
            "verdict": verdict,
            "observations": [o.model_dump(mode="json") for o in observations],
        }

    @app.post("/complete", dependencies=[guarded])
    async def complete() -> dict[str, Any]:
        await app.state.session.complete()
        return {"ok": True, "state": app.state.session.state}

    @app.get("/summary", dependencies=[guarded])
    async def summary() -> dict[str, Any]:
        return (await app.state.session.summary()).model_dump(mode="json")

    @app.get("/timeline", dependencies=[guarded])
    async def timeline() -> list[dict[str, Any]]:
        return [
            {"seq": e.seq, "type": e.type, "payload": e.payload}
            for e in app.state.session.events()
        ]

    @app.post("/shutdown", dependencies=[guarded])
    async def shutdown() -> dict[str, Any]:
        server = app.state.server
        if server is not None:
            server.should_exit = True  # type: ignore[attr-defined]
        return {"ok": True}

    return app


class SidecarServer:
    """进程内线程形态（测试/嵌入）：后台线程跑 uvicorn，端口可随机。"""

    def __init__(self, spec: SidecarSpec, *, host: str = "127.0.0.1",
                 port: int = 0) -> None:
        import uvicorn

        self.token = secrets.token_urlsafe(24)
        self._root = Path(tempfile.mkdtemp(prefix="vasta-sidecar-"))
        app = build_sidecar_app(spec, token=self.token)
        app.state.root = self._root
        self._server: Any = uvicorn.Server(uvicorn.Config(
            app, host=host, port=port, log_level="warning", access_log=False))
        self._server.install_signal_handlers = lambda: None  # 非主线程禁信号
        app.state.server = self._server
        self._thread: threading.Thread | None = None
        self.port: int | None = None

    @property
    def base_url(self) -> str:
        if self.port is None:
            raise VastaError(code="sidecar.not_running", message="sidecar 未启动")
        return f"http://127.0.0.1:{self.port}"

    def start(self, *, timeout_s: float = 30.0) -> str:
        """后台线程起服务，轮询 healthz 至就绪，返回 base_url。"""
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._server.started and self._server.servers:
                self.port = self._server.servers[0].sockets[0].getsockname()[1]
                client = SidecarClient(self.base_url, self.token)
                try:
                    if client.healthz().get("ok"):
                        return self.base_url
                except VastaError:
                    pass  # 会话仍在装配（lifespan 未完成）——继续等
            if self._thread is not None and not self._thread.is_alive():
                break
            time.sleep(0.02)
        raise VastaError(code="sidecar.start_timeout",
                         message=f"sidecar {timeout_s}s 内未就绪")

    def stop(self, *, timeout_s: float = 10.0) -> None:
        self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
        self.port = None

    def __enter__(self) -> SidecarServer:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


class SidecarClient:
    """纯 stdlib HTTP 客户端（Agent 侧形态参考——任意语言照抄）。"""

    def __init__(self, base_url: str, token: str, *, timeout_s: float = 60.0) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout_s

    def _call(self, method: str, path: str,
              body: dict[str, Any] | None = None) -> Any:
        req = urllib.request.Request(
            f"{self._base}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self._token}",
                     "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise VastaError(
                code="sidecar.http_error",
                message=f"{method} {path} → {exc.code}: {detail[:300]}",
            ) from exc

    def healthz(self) -> dict[str, Any]:
        return self._call("GET", "/healthz")

    def observe(self) -> dict[str, Any]:
        return self._call("POST", "/observe", {})

    def act(self, tool: str, args: dict[str, Any] | None = None, *,
            goal: str | None = None) -> dict[str, Any]:
        return self._call("POST", "/act",
                          {"tool": tool, "args": args or {}, "goal": goal})

    def complete(self) -> dict[str, Any]:
        return self._call("POST", "/complete", {})

    def summary(self) -> dict[str, Any]:
        return self._call("GET", "/summary")

    def timeline(self) -> list[dict[str, Any]]:
        return self._call("GET", "/timeline")

    def shutdown(self) -> dict[str, Any]:
        return self._call("POST", "/shutdown", {})


class SidecarProcess:
    """子进程形态（生产）：spawn → ready-file 就绪握手 → close 同退。"""

    def __init__(self, process: subprocess.Popen, client: SidecarClient,
                 ready: dict[str, Any]) -> None:
        self._process = process
        self.client = client
        self.ready = ready

    @classmethod
    def spawn(
        cls,
        *,
        module: str,
        root: str | Path = ".vasta-sidecar",
        host: str = "127.0.0.1",
        port: int = 0,
        timeout_s: float = 60.0,
    ) -> SidecarProcess:
        """起子进程 sidecar 并等待就绪。

        ``module``：用户模块导入路径 ``pkg.mod:build`` → 调其 ``build()``
        得 SidecarSpec。
        """
        token = secrets.token_urlsafe(24)
        with tempfile.TemporaryDirectory(prefix="vasta-sidecar-ready-") as tmp:
            ready_file = Path(tmp) / "ready.json"
            cmd = [
                sys.executable, "-m", "vastacore.execution.sidecar",
                "--module", module,
                "--root", str(root),
                "--host", host,
                "--port", str(port),
                "--token", token,
                "--ready-file", str(ready_file),
            ]
            process = subprocess.Popen(  # noqa: S603
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                if ready_file.exists():
                    break
                if process.poll() is not None:
                    err = (process.stderr.read() or b"").decode(  # type: ignore[union-attr]
                        errors="replace")
                    raise VastaError(
                        code="sidecar.child_failed",
                        message=f"sidecar 子进程退出码 {process.returncode}: "
                                f"{err[-500:]}",
                    )
                time.sleep(0.05)
            else:
                process.kill()
                raise VastaError(code="sidecar.spawn_timeout",
                                 message=f"sidecar {timeout_s}s 内未写 ready-file")
            ready = json.loads(ready_file.read_text())
        client = SidecarClient(f"http://{host}:{ready['port']}", token)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                if client.healthz().get("ok"):
                    return cls(process, client, ready)
            except VastaError:
                time.sleep(0.05)
        process.kill()
        raise VastaError(code="sidecar.spawn_timeout", message="sidecar 未就绪")

    def close(self, *, timeout_s: float = 10.0) -> None:
        """优雅关停（/shutdown → 等进程退）；超时强杀。"""
        with contextlib.suppress(VastaError):
            self.client.shutdown()
        try:
            self._process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=timeout_s)

    def __enter__(self) -> SidecarProcess:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _write_ready_atomic(path: Path, payload: dict[str, Any]) -> None:
    """先写临时名再 rename——父进程存在性轮询不读到半截文件。"""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, path)


def _main(argv: list[str] | None = None) -> int:
    """``python -m vastacore.execution.sidecar`` 入口（子进程形态）。"""
    parser = argparse.ArgumentParser(prog="vastacore-sidecar")
    parser.add_argument("--module", required=True,
                        help="用户模块导入路径 pkg.mod:build（返回 SidecarSpec）")
    parser.add_argument("--root", default=".vasta-sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", required=True)
    parser.add_argument("--ready-file", required=True,
                        help="就绪握手文件：写 {port, pid} 后父进程方可访问")
    args = parser.parse_args(argv)

    mod_path, _, attr = args.module.partition(":")
    build = getattr(importlib.import_module(mod_path), attr or "build")
    import asyncio

    spec = asyncio.run(_resolve_spec(build))

    import socket as _socket

    import uvicorn

    # 预绑 socket：端口在 uvicorn 起动前即确定——先写 ready-file，
    # 父进程再以 healthz 轮询确认会话装配完成（时序安全）。
    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    sock.bind((args.host, args.port))
    sock.listen(8)
    _write_ready_atomic(Path(args.ready_file),
                        {"port": sock.getsockname()[1], "pid": os.getpid()})

    app = build_sidecar_app(spec, token=args.token)
    app.state.root = Path(args.root)
    server: Any = uvicorn.Server(uvicorn.Config(
        app, host=args.host, port=args.port, log_level="warning",
        access_log=False))
    app.state.server = server  # /shutdown 用
    server.run(sockets=[sock])
    return 0


async def _resolve_spec(
    build: Callable[[], SidecarSpec | Awaitable[SidecarSpec]],
) -> SidecarSpec:
    """build() 可同步可异步。"""
    spec = build()
    if not isinstance(spec, SidecarSpec):
        raise VastaError(
            code="sidecar.spec_shape",
            message=f"build() 须返回 SidecarSpec（得到 {type(spec).__name__}）",
        )
    return spec


if __name__ == "__main__":
    # ``python -m vastacore.execution.sidecar`` 会把本文件装成 __main__，
    # 而用户模块经 ``from vastacore.execution.sidecar import SidecarSpec``
    # 拿到的是正身实例——两份模块并存会让 isinstance 判定失效。
    # 转调正身模块的 _main，全部类身份在同一实例内闭合。
    from vastacore.execution.sidecar import _main as _canonical_main

    raise SystemExit(_canonical_main())
