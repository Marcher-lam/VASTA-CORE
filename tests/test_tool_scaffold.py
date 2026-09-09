"""Story 8.4：工具脚手架与协议测试（FR-081，G2，SM-5）。

生成即绿（从绿改起）；破坏清单构造期拒；契约模板骨架完整。
"""

from __future__ import annotations

import importlib.util
import sys

import pytest

from vasta_protocols.protocols import Action
from vastacore.agent import AgentSession
from vastacore.scaffold import (
    ScaffoldResult,
    generate_tool_project,
    run_tool_protocol_checks,
)


def load_tool_module(result: ScaffoldResult):
    """动态加载生成的 tool.py（不入 sys.path）。"""
    spec = importlib.util.spec_from_file_location(
        f"scaffolded_{result.tool_name}", result.tool_path
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def scaffolded(tmp_path):
    result = generate_tool_project("mark_order", tmp_path / "mark_order")
    yield result
    sys.modules.pop("scaffolded_mark_order", None)


class TestScaffold:
    def test_generates_three_files(self, scaffolded) -> None:
        assert scaffolded.tool_path.exists()
        assert scaffolded.template_path.exists()
        assert scaffolded.test_path.exists()
        assert scaffolded.tool_path.parent == scaffolded.root

    async def test_skeleton_is_green_out_of_the_box(self, scaffolded) -> None:
        """AC：生成→填实现→测试全绿。骨架开箱即绿（作者从绿改起）。"""
        module = load_tool_module(scaffolded)
        failures = await run_tool_protocol_checks(module.make_tool())
        assert failures == [], failures

    def test_contract_template_builds_complete_contract(self, scaffolded) -> None:
        """生成的契约模板骨架可直接构造完整契约（消摩擦点②）。"""
        ns: dict = {}
        exec(scaffolded.template_path.read_text(encoding="utf-8"), ns)  # noqa: S102
        contract = AgentSession.contract_from_template(
            ns["CONTRACT_TEMPLATE"],
            Action(tool="mark_order", args={"order_id": "A1"}),
            risk_default="R2",  # 生产路径由 act() 注入清单分级（AD-4）
        )
        from vasta_contracts import missing_segments

        assert missing_segments(contract) == []

    async def test_broken_manifest_rejected_at_construction(self, tmp_path) -> None:
        """AC：缺风险/幂等声明构造期拒绝（FR-032 复用）。"""
        from pydantic import ValidationError

        from vasta_protocols.protocols import ToolManifest

        with pytest.raises(ValidationError):
            ToolManifest(name="bad", version="1")  # 缺 risk/read_only/idempotent

    async def test_checker_flags_broken_idempotency(self, scaffolded) -> None:
        """改坏幂等（同键不回放）→ 检查器必须抓到（测试可能失败）。"""
        module = load_tool_module(scaffolded)

        class BrokenIdempotency(module.MarkOrderTool):
            async def execute(self, action, idempotency_key=None):
                from vasta_protocols.protocols import ToolResult

                return ToolResult(ok=True, detail={"n": id(self) % 97})

        failures = await run_tool_protocol_checks(BrokenIdempotency())
        assert any("幂等" in f for f in failures), failures

    def test_regenerate_refuses_overwrite(self, tmp_path) -> None:
        from vasta_protocols.errors import VastaError

        generate_tool_project("dup_tool", tmp_path / "d")
        with pytest.raises(VastaError) as excinfo:
            generate_tool_project("dup_tool", tmp_path / "d")
        assert excinfo.value.code == "scaffold.target_exists"

    def test_tool_name_validated(self, tmp_path) -> None:
        from vasta_protocols.errors import VastaError

        with pytest.raises(VastaError):
            generate_tool_project("bad name!", tmp_path / "x")


class TestProtocolChecker:
    async def test_checker_on_known_good_tool(self) -> None:
        """既有测试工具过检查器（交叉验证：检查器不假绿）。"""
        from .test_agent_sdk import SetStatusTool

        failures = await run_tool_protocol_checks(SetStatusTool())
        assert failures == [], failures

    async def test_gateway_roundtrip_in_checker(self, scaffolded) -> None:
        """检查器含网关注册+同键重放往返（AD-11）。"""
        module = load_tool_module(scaffolded)
        from vasta_runtime import ToolGateway

        tool = module.make_tool()
        gw = ToolGateway()
        gw.register(tool)
        assert gw.registered_tools() == ["mark_order"]
        r1 = await gw.execute(run_id="r", plan_step_id="s",
                              action=Action(tool="mark_order", args={"order_id": "A"}))
        r2 = await gw.execute(run_id="r", plan_step_id="s",
                              action=Action(tool="mark_order", args={"order_id": "A"}))
        assert r1.replayed is False and r2.replayed is True
