"""AgentSession：外部 Agent 开发者的高层接入 SDK（Story 8.1，FR-002/SM-5）。

设计约束：
- AD-1 组装根：本模块在 vastacore-sdk，允许组装网关/策略/存储；核心包不感知；
- 写动作六段链唯一通道 execute_contracted（AD-4）——SDK 不旁路；
- fail-closed（AD-12）：网关注册工具无契约模板 → 拒执行（不降级裸跑）；
- 同 seed 字节级复现：normalized_stream() 归一化 run_id/时间戳/事件 id 后
  逐字节可比（quickstart e2e 同口径）。

最小接入面（README 快速上手）::

    session = await AgentSession.create(
        env=my_env, tools=[my_tool],
        contracts={"my_tool": {...}}, root=".vasta", seed=42,
    )
    async with session:
        await session.start()
        await session.reset()
        await session.act(Action(tool="my_tool", args={...}))
"""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_contracts import ActionContract, missing_segments
from vasta_protocols.errors import VastaError
from vasta_protocols.ids import new_run_id
from vasta_protocols.protocols import (
    Action,
    EnvironmentAdapter,
    Observation,
    ToolAdapter,
)
from vasta_runtime import Budget, RunContext, RunEngine
from vasta_runtime.gateway import ToolGateway
from vasta_storage import SqliteStorage

from ._version import __version__

#: 契约模板：必填段齐全的普通字典（args/tool 由每次调用覆写）。
ContractTemplate = dict[str, Any]


class SessionSummary(BaseModel):
    """会话摘要（回放与验收口径同 quickstart）。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    state: str
    events: int = Field(ge=0)
    artifacts: int = Field(ge=0)
    goal_reached: bool = False
    vastacore_version: str = __version__


class AgentSession:
    """把外部 Agent 循环挂进 RunEngine 的最小 SDK 面。

    - tools 注册进 ToolGateway（清单强制分类，AD-4）；
    - act()：注册工具 → 从契约模板构造 ActionContract → execute_contracted
      （六段链自动走，开发者不手工编排核验）；未注册/显式 use_gateway=False
      → env.step 观察路径；
    - 存储默认 SQLite（.vasta/store），同 seed 跨根目录字节级复现。
    """

    def __init__(
        self,
        engine: RunEngine,
        store: SqliteStorage,
        gateway: ToolGateway,
        contracts: dict[str, ContractTemplate],
        run_id: str,
    ) -> None:
        self._engine = engine
        self._store = store
        self._gateway = gateway
        self._contracts = dict(contracts)
        self._run_id = run_id
        self._closed = False

    # ---- 组装 ----
    @classmethod
    async def create(
        cls,
        *,
        env: EnvironmentAdapter,
        tools: list[ToolAdapter] | None = None,
        contracts: dict[str, ContractTemplate] | None = None,
        root: str | Path = ".vasta",
        seed: int | None = None,
        run_id: str | None = None,
        budget: dict[str, int] | None = None,
        max_actions: int = 50,
    ) -> AgentSession:
        """从零装配一个可回放会话（外部团队接入的主入口）。"""
        store_root = Path(root) / "store"
        store = SqliteStorage(store_root)
        gateway = ToolGateway()
        for tool in tools or []:
            gateway.register(tool)
        effective_run_id = run_id or new_run_id()
        context = RunContext.create(run_id=effective_run_id, seed=seed)
        try:
            engine = await RunEngine.create(
                env=env,
                store=store,
                budget=Budget(max_actions=(budget or {}).get("max_actions", max_actions)),
                run_context=context,
                capture_observations=True,  # 观察先落盘（AD-3）
                tool_gateway=gateway,
            )
        except Exception:
            store.close()
            raise
        return cls(engine, store, gateway, contracts or {}, effective_run_id)

    # ---- 生命周期（RunEngine 透传）----
    async def start(self) -> None:
        await self._engine.start()

    async def reset(self, seed: int | None = None) -> Observation:
        return await self._engine.reset(seed=seed)

    async def observe(self) -> Observation:
        return await self._engine.observe()

    async def step(self, action: Action) -> list[Observation]:
        """纯观察路径（无契约/无网关）：环境直执行。"""
        return await self._engine.step(action)

    async def complete(self) -> None:
        await self._engine.complete()

    @property
    def state(self) -> str:
        return self._engine.state.value

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def episode_ended(self) -> bool:
        return self._engine.episode_ended

    # ---- 动作（六段链透明化）----
    @staticmethod
    def contract_from_template(
        template: ContractTemplate,
        action: Action,
        *,
        goal: str | None = None,
        risk_default: str | None = None,
    ) -> ActionContract:
        """模板 + 调用实参 → 完整契约（缺必填段在构造期即拒）。

        risk：模板未写时取 risk_default（act() 路径注入网关清单的风险
        分级——AD-4 清单强制，调用方自声明无效）；两者皆无则拒绝。"""
        fields: dict[str, Any] = dict(template)
        fields["tool"] = action.tool
        fields["args"] = dict(action.args)
        if goal is not None:
            fields["goal"] = goal
        if "risk" not in fields or not fields["risk"]:
            if risk_default is None:
                raise VastaError(
                    code="sdk.contract_risk_missing",
                    message="契约模板未声明 risk 且无清单分级可取（AD-4）",
                )
            fields["risk"] = risk_default
        contract = ActionContract.model_validate(fields)
        missing = missing_segments(contract)
        if missing:
            from vasta_contracts import ContractIncompleteError

            raise ContractIncompleteError(missing)
        return contract

    async def act(
        self,
        action: Action,
        *,
        goal: str | None = None,
        use_gateway: bool = True,
    ) -> list[Observation]:
        """执行一个动作。

        - 工具已注册网关且 use_gateway=True（默认）：契约模板构造 →
          execute_contracted 六段链（写动作核验自动走）；
        - 未注册或显式 use_gateway=False：env.step 观察路径。
        - 注册工具缺模板：fail-closed 拒执行（AD-12）。"""
        registered = action.tool in self._gateway.registered_tools()
        if use_gateway and registered:
            template = self._contracts.get(action.tool)
            if template is None:
                raise VastaError(
                    code="sdk.contract_template_missing",
                    message=(
                        f"工具 {action.tool!r} 已注册网关但无契约模板——"
                        "写动作不裸跑（fail-closed）；请在 AgentSession.create("
                        "contracts=...) 提供模板"
                    ),
                )
            # AD-4：风险分级取自清单（模板自声明 risk 时以模板为准）
            _, manifest_risk = self._gateway.classify(action.tool)
            contract = self.contract_from_template(
                template, action, goal=goal, risk_default=manifest_risk
            )
            return await self._engine.execute_contracted(contract)
        return await self._engine.step(action)

    # ---- 查询与证据 ----
    def events(self) -> list[Any]:
        """本 Run 全部事件（同步迭代副本）。"""
        return list(self._store.iter_run_events(self._run_id))

    def normalized_stream(self) -> str:
        """归一化事件流（run_id/ts/event_id/parent 抹除）——字节级复现对照。"""
        rows = []
        for e in self.events():
            rows.append(
                {
                    "seq": e.seq,
                    "type": e.type,
                    "payload": e.payload,
                }
            )
        return json.dumps(rows, ensure_ascii=False, sort_keys=True)

    async def summary(self) -> SessionSummary:
        events = self.events()
        artifacts = 0 if self._closed else len(
            await self._store.list_artifacts(
                self._engine.context.tenant_id,
                self._engine.context.project_id,
            )
        )
        return SessionSummary(
            run_id=self._run_id,
            state=self.state,
            events=len(events),
            artifacts=artifacts,
            goal_reached=self.episode_ended,
        )

    # ---- 句柄 ----
    @property
    def store_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """幂等关闭存储句柄。"""
        if not self._closed:
            self._store.close()
            self._closed = True

    async def __aenter__(self) -> AgentSession:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


__all__ = ["AgentSession", "ContractTemplate", "SessionSummary"]
