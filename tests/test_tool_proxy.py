"""Story 8.11：Tool Proxy（FR-002/蓝图 §31 Stage 2，G1）——既有工具零重写接入六段链。

通用包装（Playwright 为动机场景）；网关分类/幂等一次/超时/原始响应入 CAS。
"""

from __future__ import annotations

import asyncio

from vasta_protocols.protocols import Action
from vasta_runtime import ToolGateway
from vasta_storage import SqliteStorage
from vastacore import AgentSession
from vastacore.toolproxy import (
    browser_action_proxy,
    browser_read_proxy,
    proxy_tool,
)

# ---- 替身「既有工具」：团队已有的浏览器自动化函数 ----

class FakeBrowser:
    """替身浏览器（Playwright 接入时换真实 page）。"""

    def __init__(self) -> None:
        self.clicked: list[str] = []
        self.text = "Order A102 shipped"

    async def click(self, selector: str) -> dict:
        self.clicked.append(selector)
        return {"clicked": selector}

    async def get_text(self, selector: str = "#status") -> dict:
        return {"selector": selector, "text": self.text}


CLICK_CONTRACT = dict(
    goal="点击发货确认按钮",
    preconditions=["按钮可见"],
    prediction={"changes": ["clicked=confirm"],
                "invariants": ["其他元素不变"]},
    success_criteria=["click ack"],
    failure_criteria=["selector not found"],
    verify_with=["read_back"],
    timeout_ms=5000,
)


class TestProxyTool:
    async def test_registers_and_classifies_in_gateway(self) -> None:
        browser = FakeBrowser()
        tool = proxy_tool(
            "browser_click", browser.click, risk="R2",
            read_only=False, idempotent=False,
        )
        gateway = ToolGateway()
        gateway.register(tool)
        read_only, risk = gateway.classify("browser_click")
        assert read_only is False and risk == "R2"

    async def test_act_walks_six_segments_and_cas(self, tmp_path) -> None:
        """AC：经 Proxy 执行走网关通道，六段落事件 + 原始响应入 CAS。"""
        browser = FakeBrowser()
        session = await AgentSession.create(
            env=_BrowserEnv(),
            tools=[proxy_tool("browser_click", browser.click,
                              risk="R2", read_only=False, idempotent=True)],
            contracts={"browser_click": CLICK_CONTRACT},
            root=tmp_path, seed=1,
        )
        async with session:
            await session.start()
            await session.reset()
            observations = await session.act(
                Action(tool="browser_click", args={"selector": "#confirm"})
            )
            assert observations
            types = [e.type for e in session.events()]
            assert "action.contracted" in types
            assert "action.executed" in types
            # 原始响应入 CAS 可取回
            executed = [e for e in session.events()
                        if e.type == "action.executed"][-1]
            sha = executed.payload["result_ref"]
            store = SqliteStorage(tmp_path / "store")
            try:
                blob = await store.get_artifact(sha)
                assert b"clicked" in blob  # 替身浏览器的原始响应
            finally:
                store.close()

    async def test_idempotent_key_calls_fn_once(self) -> None:
        """AC：幂等——同键二次执行 fn 只跑一次（replayed=True）。"""
        browser = FakeBrowser()
        tool = proxy_tool("browser_click", browser.click,
                          risk="R2", read_only=False, idempotent=True)
        gateway = ToolGateway()
        gateway.register(tool)
        action = Action(tool="browser_click", args={"selector": "#a"})
        r1 = await gateway.execute(run_id="r", plan_step_id="s1", action=action)
        r2 = await gateway.execute(run_id="r", plan_step_id="s1", action=action)
        assert r1.replayed is False and r2.replayed is True
        assert len(browser.clicked) == 1  # 底层函数仅执行一次

    async def test_timeout_captures_error(self) -> None:
        """AC：超时——慢函数按协议路径落 adapter_error（不悬挂）。"""
        async def slow(selector: str) -> dict:
            await asyncio.sleep(0.5)
            return {"clicked": selector}

        tool = proxy_tool("slow_click", slow, risk="R2",
                          read_only=False, idempotent=False, timeout_ms=60)
        gateway = ToolGateway()
        gateway.register(tool)
        result = await gateway.execute(
            run_id="r", plan_step_id="s1",
            action=Action(tool="slow_click", args={"selector": "#x"}),
        )
        assert result.ok is False
        assert result.detail.get("phase") == "adapter_error"
        assert "timeout" in str(result.detail.get("error", "")).lower()


class TestBrowserPresets:
    async def test_action_preset_r2_write_non_idempotent(self) -> None:
        browser = FakeBrowser()
        tool = browser_action_proxy("click", browser.click)
        assert tool.manifest.risk == "R2"
        assert tool.manifest.read_only is False
        assert tool.manifest.idempotent is False  # 双击有副作用，不幂等

    async def test_read_preset_r1_readonly_idempotent(self) -> None:
        browser = FakeBrowser()
        tool = browser_read_proxy("get_text", browser.get_text)
        assert tool.manifest.risk == "R1"
        assert tool.manifest.read_only is True
        assert tool.manifest.idempotent is True

    async def test_read_tool_protocol_checks_green(self) -> None:
        """读预设过五面协议检查器（幂等缓存协议内置）。"""
        from vastacore.scaffold import run_tool_protocol_checks

        browser = FakeBrowser()
        tool = browser_read_proxy("get_text", browser.get_text)
        failures = await run_tool_protocol_checks(tool)
        assert failures == [], failures


class _BrowserEnv:
    """最小环境替身（Proxy 工具走网关，不经 env 执行）。"""

    protocol_version = "0.1.0"

    async def reset(self, seed=None):
        from vasta_protocols.protocols import Observation
        return Observation(kind="decision", detail={"page": "orders"})

    async def observe(self):
        from vasta_protocols.protocols import Observation
        return Observation(kind="decision", detail={"page": "orders"})

    async def execute(self, action):
        from vasta_protocols.protocols import Observation
        return [Observation(kind="transition", detail={}),
                Observation(kind="decision", detail={})]

    async def status(self):
        class S:
            running = True
        return S()
