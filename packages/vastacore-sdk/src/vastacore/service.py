"""HTTP 接入服务：任何语言经 REST 接入 VastaCore（Story 8.3，FR-002/G1）。

- 组装根（AD-1）：服务端持 env 工厂 / tools / 契约模板，全部动作经
  AgentSession → execute_contracted（服务层不旁路唯一写通道，AD-2）；
- Bearer 令牌鉴权（401）；
- 崩溃安全：每事件即时落盘 SQLite；重启后 timeline/search 读存储而非
  会话内存，历史 run 仍可查；
- 并发：MVP 单写者——全局锁串行化 run 操作（多会话并发属 Stage 3）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from vasta_protocols.protocols import EnvironmentAdapter, ToolAdapter
from vasta_storage import SqliteStorage

from ._version import __version__
from .agent import AgentSession, ContractTemplate


class CreateRunBody(BaseModel):
    seed: int | None = None
    max_actions: int = 50


class ActBody(BaseModel):
    tool: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)
    goal: str | None = None


class ResetBody(BaseModel):
    seed: int | None = None


class VastaService:
    """会话与存储持有者（测试与 CLI 共用装配面）。"""

    def __init__(
        self,
        *,
        env_factory: Callable[[], EnvironmentAdapter],
        tools: list[ToolAdapter],
        contracts: dict[str, ContractTemplate],
        root: str | Path,
    ) -> None:
        self.env_factory = env_factory
        self.tools = tools
        self.contracts = contracts
        self.store = SqliteStorage(Path(root) / "store")  # 与 AgentSession 同规则
        self.sessions: dict[str, AgentSession] = {}
        self.lock = asyncio.Lock()

    def close(self) -> None:
        for session in self.sessions.values():
            session.close()
        self.sessions.clear()
        self.store.close()

    async def timeline_events(self, run_id: str) -> list[dict[str, Any]] | None:
        """读存储（非会话内存）——重启后仍可查历史 run。"""
        events = list(self.store.iter_run_events(run_id))
        return events or None


def create_app(
    *,
    env_factory: Callable[[], EnvironmentAdapter],
    tools: list[ToolAdapter] | None = None,
    contracts: dict[str, ContractTemplate] | None = None,
    root: str | Path = ".vasta/store",
    token: str,
) -> FastAPI:
    """装配 HTTP 服务（token 必填——无匿名面）。"""
    from vasta_storage import timeline as build_timeline

    service = VastaService(
        env_factory=env_factory, tools=tools or [], contracts=contracts or {},
        root=root,
    )
    app = FastAPI(title="VastaCore Service", version=__version__)
    app.state.service = service

    def require_token(request: Request) -> None:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="invalid token")

    def _session(run_id: str) -> AgentSession:
        session = service.sessions.get(run_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
        return session

    @app.post("/runs", status_code=201, dependencies=[Depends(require_token)])
    async def create_run(body: CreateRunBody) -> dict[str, str]:
        async with service.lock:
            session = await AgentSession.create(
                env=service.env_factory(),
                tools=list(service.tools),
                contracts=dict(service.contracts),
                root=root,
                seed=body.seed,
                budget={"max_actions": body.max_actions},
            )
        service.sessions[session.run_id] = session
        return {"run_id": session.run_id}

    @app.post("/runs/{run_id}/start", dependencies=[Depends(require_token)])
    async def start_run(run_id: str) -> dict[str, bool]:
        async with service.lock:
            try:
                await _session(run_id).start()
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

    @app.post("/runs/{run_id}/reset", dependencies=[Depends(require_token)])
    async def reset_run(run_id: str, body: ResetBody | None = None) -> dict[str, Any]:
        async with service.lock:
            try:
                obs = await _session(run_id).reset(seed=body.seed if body else None)
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"kind": obs.kind, "detail": obs.detail}

    @app.post("/runs/{run_id}/act", dependencies=[Depends(require_token)])
    async def act(run_id: str, body: ActBody) -> dict[str, Any]:
        from vasta_protocols.errors import VastaError
        from vasta_protocols.protocols import Action

        async with service.lock:
            session = _session(run_id)
            try:
                observations = await session.act(
                    Action(tool=body.tool, args=body.args), goal=body.goal
                )
            except VastaError as exc:
                raise HTTPException(status_code=400, detail=exc.message) from exc
        return {"observations": [
            {"kind": o.kind, "detail": o.detail} for o in observations
        ]}

    @app.post("/runs/{run_id}/complete", dependencies=[Depends(require_token)])
    async def complete_run(run_id: str) -> dict[str, bool]:
        async with service.lock:
            try:
                await _session(run_id).complete()
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

    @app.get("/runs/{run_id}/summary", dependencies=[Depends(require_token)])
    async def summary(run_id: str) -> dict[str, Any]:
        session = service.sessions.get(run_id)
        if session is not None:
            s = await session.summary()
            return s.model_dump()
        # 会话已死（服务重启）：从事件流推导终态
        events = await service.timeline_events(run_id)
        if events is None:
            raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
        last_run = next(
            (e.type for e in reversed(events) if e.type.startswith("run.")), None
        )
        state = {"run.completed": "completed", "run.failed": "failed"}.get(
            last_run or "", "started"
        )
        return {
            "run_id": run_id, "state": state, "events": len(events),
            "artifacts": 0, "goal_reached": False, "vastacore_version": __version__,
        }

    @app.get("/runs/{run_id}/timeline", dependencies=[Depends(require_token)])
    async def timeline(run_id: str) -> dict[str, Any]:
        events = await service.timeline_events(run_id)
        if events is None:
            raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
        tl = build_timeline(events)
        return {
            "run_id": tl.run_id,
            "total_events": tl.total_events,
            "max_depth": tl.max_depth,
            "families": tl.families_present,
            "entries": [
                {
                    "seq": e.seq, "type": e.type, "depth": e.depth,
                    "ts": e.ts, "summary": e.summary,
                    "external_change": e.external_change,
                }
                for e in tl.entries
            ],
        }

    @app.get("/evidence/search", dependencies=[Depends(require_token)])
    async def search(
        run_id: str | None = None,
        event_type: str | None = None,
        tool: str | None = None,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] | None = (
            {"tool": tool} if tool else None
        )
        hits = await service.store.search_events(
            "t-default", "p-default",
            run_id=run_id, event_type=event_type, payload_equals=payload,
        )
        return [
            {"seq": e.seq, "type": e.type, "ts": e.ts.isoformat(),
             "payload": e.payload}
            for e in hits
        ]

    return app


def serve(
    *,
    root: str | Path = ".vasta",
    token: str,
    host: str = "127.0.0.1",
    port: int = 8700,
) -> None:
    """`vasta serve` 入口：GridWorld 预设环境 + 令牌（生产换装配在 apps 层）。"""
    import uvicorn

    from vasta_adapters import GridWorldAdapter

    app = create_app(
        env_factory=GridWorldAdapter, tools=[], contracts={},
        root=root, token=token,
    )
    uvicorn.run(app, host=host, port=port)


__all__ = ["VastaService", "create_app", "serve"]
