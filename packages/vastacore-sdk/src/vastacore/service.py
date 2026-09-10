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
from contextlib import asynccontextmanager
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
    max_actions: int = Field(default=50, ge=1)


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
        # 运维指标计数（Story 9.12：/metrics 数据面——错误计数由 act 路径维护）
        self.metrics_counters = {"errors": 0, "actions": 0}

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
    # 评审修复：docs/openapi 匿名面关闭（纯 API 服务）；
    # token 比较改常数时间（原先普通 != 有时序侧信道）
    app = FastAPI(title="VastaCore Service", version=__version__,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = service

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        yield
        service.close()  # 评审修复：shutdown 关闭全部会话与服务 store

    app.router.lifespan_context = _lifespan

    def require_token(request: Request) -> None:
        import hmac as _hmac

        auth = request.headers.get("Authorization", "")
        if not _hmac.compare_digest(auth, f"Bearer {token}"):
            raise HTTPException(status_code=401, detail="invalid token")

    def _session(run_id: str) -> AgentSession:
        session = service.sessions.get(run_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
        return session

    # ---- 运维基线端点（Story 9.12，FR-076）----
    # /healthz（活性）与 /readyz（就绪）**匿名**：K8s probe 场景，只回
    # 进程/依赖状态、零业务数据（数据面端点仍全部 token 保护）；/metrics
    # 携带指标与告警——带 token。
    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "alive"}  # 活性：进程在即活（无依赖判定）

    @app.get("/readyz")
    async def readyz() -> dict[str, Any]:
        try:  # 就绪：存储心跳（元数据面点查）
            service.store.last_event_info("__readyz_probe__")
        except Exception as exc:  # noqa: BLE001——依赖故障即未就绪
            raise HTTPException(
                status_code=503, detail=f"store not ready: {exc}") from exc
        return {"status": "ready", "sessions": len(service.sessions)}

    @app.get("/metrics", dependencies=[Depends(require_token)])
    async def metrics() -> dict[str, Any]:
        from .ops import MetricsSnapshot, evaluate_alerts

        counters = service.metrics_counters
        total = counters["errors"] + counters["actions"]
        snapshot = MetricsSnapshot(  # 评审修复 M4：分母含错误数（占比口径）
            error_rate=round(counters["errors"] / total, 6) if total else 0.0,
            queue_depth=len(service.sessions),
            quota_throttled=_quota_throttle_count(service.store),
            sessions_active=len(service.sessions),
        )
        return {
            "metrics": snapshot.model_dump(),
            "alerts": [a.model_dump() for a in evaluate_alerts(snapshot)],
        }

    def _quota_throttle_count(store: Any) -> int:
        """配额触顶计数（quotas 系统流的 run.throttled 事件数）。"""
        try:
            return sum(
                1 for e in store.iter_run_events("quotas")
                if e.type == "run.throttled")
        except Exception:  # noqa: BLE001——指标面不因单源缺失失败
            return 0

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
            from vasta_protocols.errors import VastaError

            try:
                await _session(run_id).start()
            except HTTPException:
                raise
            except VastaError as exc:
                raise HTTPException(status_code=400, detail=exc.message) from exc
            # 其余异常放行为 500（评审修复：服务端缺陷不再伪装成客户端 400）
        return {"ok": True}

    @app.post("/runs/{run_id}/reset", dependencies=[Depends(require_token)])
    async def reset_run(run_id: str, body: ResetBody | None = None) -> dict[str, Any]:
        async with service.lock:
            from vasta_protocols.errors import VastaError

            try:
                obs = await _session(run_id).reset(seed=body.seed if body else None)
            except HTTPException:
                raise
            except VastaError as exc:
                raise HTTPException(status_code=400, detail=exc.message) from exc
            # 其余异常放行为 500（评审修复：服务端缺陷不再伪装成客户端 400）
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
                service.metrics_counters["errors"] += 1  # /metrics 错误率面
                raise HTTPException(status_code=400, detail=exc.message) from exc
            service.metrics_counters["actions"] += 1
        return {"observations": [
            {"kind": o.kind, "detail": o.detail} for o in observations
        ]}

    @app.post("/runs/{run_id}/complete", dependencies=[Depends(require_token)])
    async def complete_run(run_id: str) -> dict[str, bool]:
        async with service.lock:
            from vasta_protocols.errors import VastaError

            session = _session(run_id)
            try:
                await session.complete()
            except HTTPException:
                raise
            except VastaError as exc:
                raise HTTPException(status_code=400, detail=exc.message) from exc
            # 其余异常放行为 500（评审修复：服务端缺陷不再伪装成客户端 400）
            # 会话回收（评审修复：句柄/连接无界累积）——summary 走事件推导
            session.close()
            service.sessions.pop(run_id, None)
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
        state = {
            "run.created": "created", "run.started": "started",
            "run.paused": "paused", "run.cancelled": "cancelled",
            "run.completed": "completed", "run.failed": "failed",
        }.get(last_run or "", "unknown")
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
