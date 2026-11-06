"""Sidecar 子进程形态测试的用户侧接入模块（Story 8.15 测试夹具）。

模拟「外部团队」：只提供一个 build() -> SidecarSpec，不带任何
服务端装配知识。被 ``tests/test_sidecar.py`` 以
``--module tests._sidecar_usermod:build`` 起子进程 sidecar。
"""

from __future__ import annotations

from vasta_protocols.protocols import (
    DryRunResult,
    EnvironmentAdapter,
    Observation,
    ToolAdapter,
    ToolManifest,
    ToolResult,
)
from vastacore.execution.sidecar import SidecarSpec


class TodoEnv(EnvironmentAdapter):
    protocol_version = "0.1.0"

    def __init__(self) -> None:
        self.status = "pending"

    async def reset(self, seed=None):
        self.status = "pending"
        return Observation(kind="decision", detail={"status": self.status},
                           available_actions=["read_status", "set_status"])

    async def observe(self):
        return Observation(kind="decision", detail={"status": self.status})

    async def execute(self, action):
        if action.tool == "set_status":
            self.status = action.args.get("status", "done")
        return [
            Observation(kind="transition", detail={"status": self.status}),
            Observation(kind="decision", detail={"status": self.status}),
        ]

    async def status(self):
        class S:
            running = True
        return S()


class SetStatusTool(ToolAdapter):
    protocol_version = "0.1.0"
    manifest = ToolManifest(
        name="set_status", version="1.0", risk="R2",
        read_only=False, idempotent=True, supports_read_back=True,
    )

    def __init__(self) -> None:
        self._results: dict[str, ToolResult] = {}

    async def execute(self, action, idempotency_key=None):
        if idempotency_key in self._results:
            return self._results[idempotency_key].model_copy(update={"replayed": True})
        result = ToolResult(ok=True, detail={"status": action.args.get("status")})
        self._results[idempotency_key] = result
        return result

    async def dry_run(self, action):
        return DryRunResult(allowed=True)

    async def read_back(self, action, result):
        return Observation(kind="decision", detail={"status": result.detail["status"]})

    async def compensate(self, action, result):
        return ToolResult(ok=True, detail={"compensated": True})


STATUS_CONTRACT = dict(
    tool="set_status",
    goal="标记待办为完成",
    preconditions=["status=pending"],
    prediction={"changes": ["status=done"], "invariants": ["item count unchanged"]},
    success_criteria=["read-back status=done"],
    failure_criteria=["status unchanged"],
    verify_with=["read_back"],
    timeout_ms=5000,
)


def build() -> SidecarSpec:
    """外部团队唯一交付物：接入物清单（sidecar 侧负责一切装配）。"""
    return SidecarSpec(
        env=TodoEnv(),
        tools=[SetStatusTool()],
        contracts={"set_status": STATUS_CONTRACT},
        seed=7,
    )
