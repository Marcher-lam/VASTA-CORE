"""工具脚手架与协议测试（Story 8.4，FR-081，SM-5 出门条件之二）。

`vasta tool init` 三件套：ToolAdapter 骨架（签名正确，消接入摩擦点③）、
契约模板骨架（七必填段，消摩擦点②）、一键协议测试（pytest 直接跑）。

骨架开箱即绿——作者从绿改起，而非从红猜起；协议检查器五面：
manifest 完整性 / 幂等重放 / dry-run / 读回 / 网关注册分类往返（AD-11）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from vasta_protocols.errors import VastaError
from vasta_protocols.protocols import Action, ToolAdapter, ToolResult


class ScaffoldResult(BaseModel):
    """脚手架产物位置。"""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    root: Path
    tool_path: Path
    template_path: Path
    test_path: Path


# ---- 程序化协议检查器（生成测试与平台测试共用）----

async def run_tool_protocol_checks(tool: ToolAdapter) -> list[str]:
    """五面协议检查；返回失败清单（空=全绿，可注册网关）。

    1. manifest 完整性（缺风险/幂等声明在构造期即拒——FR-032）
    2. 幂等重放：同 idempotency_key 二次调用 → replayed=True 且结果一致
    3. dry-run 形态（声明 supports_dry_run 时）
    4. 读回形态（声明 supports_read_back 时）
    5. 网关往返：注册 → 清单分类 → 同键二次执行 replayed=True（AD-11）
    """
    failures: list[str] = []
    manifest: Any
    try:
        manifest = tool.manifest
        assert manifest.name and manifest.version
        assert manifest.risk in {"R0", "R1", "R2", "R3", "R4"}
        assert isinstance(manifest.read_only, bool)
        assert isinstance(manifest.idempotent, bool)
    except Exception as exc:  # noqa: BLE001——构造期拒绝也算失败项
        return [f"清单完整性失败（FR-032 构造期拒绝）: {exc}"]

    action = Action(tool=manifest.name, args={})
    # dry-run 门先行（评审修复：与网关同序——先 dry_run 后 execute；且只在
    # 清单声明 supports_dry_run 时探测，声明了却未实现即失败）
    if manifest.supports_dry_run:
        try:
            dry = await tool.dry_run(action)
            if not isinstance(dry.allowed, bool):
                failures.append("dry-run 形态失败：allowed 应为 bool")
        except NotImplementedError:
            failures.append(
                "dry-run 失败：清单声明 supports_dry_run 但未实现 dry_run"
                "（网关路径会裸抛——正是要拦的协议违规）"
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"dry-run 协议失败: {exc}")

    first: ToolResult | None = None
    try:
        first = await tool.execute(action, idempotency_key="proto-check")
        second = await tool.execute(action, idempotency_key="proto-check")
        if second.replayed is not True:
            failures.append("幂等重放失败：同 idempotency_key 二次调用 replayed 应为 True")
        if second.detail != first.detail:
            failures.append("幂等重放失败：重放结果与首次不一致")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"execute 协议失败（签名须含 idempotency_key 关键字）: {exc}")
    # 注意：协议检查会真实执行工具两次（幂等键相同）——副作用工具请在
    # 干净环境跑检查（网关路径因同键重放只执行一次）

    if manifest.supports_read_back and first is not None:
        try:
            obs = await tool.read_back(action, first)
            if obs.kind not in {"decision", "transition", "terminal", "reset", "external"}:
                failures.append(f"读回形态失败：kind={obs.kind!r} 不在五类 Observation")
        except NotImplementedError:
            failures.append("读回失败：清单声明 supports_read_back 但未实现 read_back")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"读回协议失败: {exc}")

    try:
        from vasta_runtime import ToolGateway

        gateway = ToolGateway()
        gateway.register(tool)
        read_only, risk = gateway.classify(manifest.name)
        if read_only != manifest.read_only or risk != manifest.risk:
            failures.append("网关分类失败：清单分类与网关读取不一致")
        await gateway.execute(
            run_id="proto", plan_step_id="check", action=action
        )
        g2 = await gateway.execute(
            run_id="proto", plan_step_id="check", action=action
        )
        if g2.replayed is not True:
            failures.append("网关往返失败：同键二次执行未走幂等重放（AD-11）")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"网关注册/往返失败: {exc}")

    return failures


# ---- 生成模板 ----

_TOOL_TEMPLATE = '''"""{tool_name} 工具（vasta tool init 生成——从绿改起）。

协议要点（改坏任何一条，test_protocol.py 会红）：
- execute 签名必须是 (self, action, idempotency_key=None)——关键字协议；
- 同 idempotency_key 二次调用必须返回原结果 + replayed=True（AD-11）；
- 清单缺 risk/read_only/idempotent 在构造期即拒（FR-032）。
"""

from __future__ import annotations

from vasta_protocols.protocols import (
    Action,
    DryRunResult,
    Observation,
    ToolAdapter,
    ToolManifest,
    ToolResult,
)


class {class_name}(ToolAdapter):
    protocol_version = "0.1.0"
    # TODO: 按真实风险/能力调整（risk: R0 只读 ~ R4 不可逆高危）
    manifest = ToolManifest(
        name="{tool_name}",
        version="0.1.0",
        risk="R2",
        read_only=False,
        idempotent=True,
        supports_dry_run=True,
        supports_read_back=True,
    )

    def __init__(self) -> None:
        self._results: dict[str, ToolResult] = {{}}  # 幂等缓存（协议要求）

    async def execute(self, action: Action, idempotency_key=None) -> ToolResult:
        """真实业务逻辑放这里（保留幂等缓存协议）。"""
        if idempotency_key in self._results:
            return self._results[idempotency_key].model_copy(update={{"replayed": True}})
        # TODO: 替换为真实副作用；结果是原始响应（会入 CAS 留证据）
        result = ToolResult(ok=True, detail={{"echo": action.args, "done": True}})
        self._results[idempotency_key] = result
        return result

    async def dry_run(self, action: Action) -> DryRunResult:
        # TODO: 前置校验（会执行则 True）
        return DryRunResult(allowed=True)

    async def read_back(self, action: Action, result: ToolResult) -> Observation:
        # TODO: 读回真实状态（核验器用它比对预期变化）
        return Observation(kind="decision", detail=dict(result.detail))

    async def compensate(self, action: Action, result: ToolResult) -> ToolResult:
        # TODO: 补偿逻辑（FR-038 Stage 3 激活；先占位回成功）
        return ToolResult(ok=True, detail={{"compensated": True}})


def make_tool() -> {class_name}:
    return {class_name}()
'''

_TEMPLATE_TEMPLATE = '''"""{tool_name} 契约模板（七必填段骨架——填业务语义即完整契约）。

接入：AgentSession.create(contracts={{"{tool_name}": CONTRACT_TEMPLATE}})
"""

CONTRACT_TEMPLATE = {{
    "goal": "TODO: 本次动作的业务目标",
    "preconditions": ["TODO: 前置条件（如 订单存在且已付款）"],
    "prediction": {{
        "changes": ["{tool_name}.status=done"],  # TODO: 预期变化（核验按值子串匹配）
        "invariants": ["TODO: 什么必须不变（如 其他订单不变）"],
    }},
    "success_criteria": ["TODO: 成功判据（如 read-back status=done）"],
    "failure_criteria": ["TODO: 失败判据（如 重复副作用）"],
    "verify_with": ["read_back"],
    "timeout_ms": 5000,
    # risk 留空 → 自动取清单分级（AD-4：清单强制，自声明无效）
}}
'''

_TEST_TEMPLATE = '''"""{tool_name} 协议测试（vasta tool init 生成）——pytest 直接跑：

    pytest test_protocol.py -q

全绿（输出空失败清单）= 过五协议契约，可注册网关上架。
"""

from __future__ import annotations

import asyncio

from tool import make_tool
from vastacore.scaffold import run_tool_protocol_checks


def test_protocol_green() -> None:
    failures = asyncio.run(run_tool_protocol_checks(make_tool()))
    assert failures == [], failures
'''


def generate_tool_project(name: str, target: str | Path) -> ScaffoldResult:
    """生成工具项目三件套（拒绝覆盖已有目录）。"""
    if not name.isidentifier():
        raise VastaError(
            code="scaffold.bad_name",
            message=f"工具名 {name!r} 必须是合法 Python 标识符（snake_case）",
        )
    root = Path(target)
    if root.exists() and any(root.iterdir()):
        raise VastaError(
            code="scaffold.target_exists",
            message=f"目标目录非空: {root}（脚手架拒绝覆盖）",
        )
    root.mkdir(parents=True, exist_ok=True)
    class_name = "".join(part.capitalize() for part in name.split("_")) + "Tool"
    tool_path = root / "tool.py"
    template_path = root / "contract_template.py"
    test_path = root / "test_protocol.py"
    tool_path.write_text(
        _TOOL_TEMPLATE.format(tool_name=name, class_name=class_name),
        encoding="utf-8",
    )
    template_path.write_text(
        _TEMPLATE_TEMPLATE.format(tool_name=name), encoding="utf-8"
    )
    test_path.write_text(_TEST_TEMPLATE.format(tool_name=name), encoding="utf-8")
    return ScaffoldResult(
        tool_name=name, root=root, tool_path=tool_path,
        template_path=template_path, test_path=test_path,
    )


__all__ = ["ScaffoldResult", "generate_tool_project", "run_tool_protocol_checks"]
