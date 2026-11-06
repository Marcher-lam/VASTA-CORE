"""click_mark 工具：编号标记 → AX 定点点击（六段链的执行段）。

清单强制分类（AD-4）：R2 / 非只读 / 非幂等（双击有副作用）。
证据语义：点击前后截图经 store 落 CAS（AD-3），ToolResult.artifact_ref
引用后截图；display_after 为 AX 直读事实——核验器的确定性输入。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from vasta_protocols.protocols import (
    Action,
    CompensationResult,
    DryRunResult,
    Observation,
    ToolManifest,
    ToolResult,
)

from .ax import click_at, click_element, read_display, screenshot_png

#: marks 表形态：mark(int) → {"path": [int…], "x_pt","y_pt","w_pt","h_pt", …}
MarksProvider = Callable[[], dict[int, dict]]


class ClickMarkTool:
    """点击当前标记表中指定编号的元素。"""

    protocol_version = "0.1.0"

    def __init__(self, app: str, marks: MarksProvider, store: Any,
                 display_path: tuple[int, ...], *,
                 tenant_id: str, project_id: str,
                 settle_s: float = 0.35,
                 capture_screens: bool = True) -> None:
        self.manifest = ToolManifest(
            name="click_mark", version="1.0",
            risk="R2", read_only=False, idempotent=False,
            compensable=False, supports_dry_run=True, supports_read_back=True,
            side_effects=[f"点击 {app} 窗口内被标记的 UI 元素"],
        )
        self._app = app
        self._marks = marks
        self._store = store
        self._display_path = display_path
        self._tenant = tenant_id
        self._project = project_id
        self._settle = settle_s
        self._capture = capture_screens

    # ---- 证据 ----

    async def _save_shot(self, tag: str) -> str | None:
        if not self._capture or self._store is None:
            return None
        png = screenshot_png()
        return await self._store.save_artifact(
            png, mime="image/png", source=f"cua.tool.screenshot.{tag}",
            tenant_id=self._tenant, project_id=self._project,
        )

    def _display(self) -> str | None:
        try:
            return read_display(self._app, self._display_path)
        except Exception:
            return None

    # ---- ToolAdapter 协议 ----

    async def dry_run(self, action: Action) -> DryRunResult:
        mark = action.args.get("mark")
        if not isinstance(mark, int) or mark not in self._marks():
            return DryRunResult(allowed=False,
                                reason=f"标记 {mark!r} 不在当前标记表")
        return DryRunResult(allowed=True)

    async def execute(self, action: Action, idempotency_key=None) -> ToolResult:
        mark = action.args.get("mark")
        entry = self._marks().get(mark)  # dry_run 已保证存在
        path = tuple(entry["path"])
        display_before = self._display()
        await self._save_shot("before")
        clicked = click_element(self._app, path)
        if not clicked:  # AX 元素点击失败 → 坐标兜底（CGEvent）
            cx = entry["x_pt"] + entry["w_pt"] / 2
            cy = entry["y_pt"] + entry["h_pt"] / 2
            clicked = click_at(cx, cy)
        time.sleep(self._settle)
        # 读屏竞态（实测坑：= 求值渲染慢于 0.35s——FR-037 记过一次
        # environment_delay 偏差）：轮询至显示变化或有界超时
        display_after = self._display()
        waited = 0.0
        while (display_after == display_before and waited < 1.5):
            time.sleep(0.25)
            waited += 0.25
            display_after = self._display()
        after_sha = await self._save_shot("after")
        return ToolResult(
            ok=clicked,
            artifact_ref=after_sha,
            detail={"mark": mark, "path": list(path),
                    "display_before": display_before,
                    "display_after": display_after},
        )

    async def read_back(self, action: Action, result: ToolResult) -> Observation:
        return Observation(
            kind="decision",
            detail={"display": result.detail.get("display_after"),
                    "mark": result.detail.get("mark")},
        )

    async def compensate(self, execution_detail: dict) -> CompensationResult:
        # 点击不可逆；恢复策略 = 任务级 AC 归零（Stage 3 补偿协议预留）
        return CompensationResult(
            ok=False,
            detail={"note": "点击不可补偿——恢复由 AC 归零协议承担"},
        )

    # read_back 协议形状双轨：protocols.read_back(action) 与网关
    # (action, result) 并存（学 toolproxy.py / from_zero.py 形态）


__all__ = ["ClickMarkTool", "MarksProvider"]
