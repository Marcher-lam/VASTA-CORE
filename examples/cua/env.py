"""DesktopEnv：Calculator 沙盒的 EnvironmentAdapter（五协议）。

观察语义：
- observe() 返回 AX 事实（前台标志 + 显示屏值）——决策帧，不截图
  （截图证据由 ClickMarkTool 在动作链内产出，见 tools.py）；
- reset() = hard_reset（冷启动回出厂 "0"）——env.reset 语义对齐；
- execute() 故意不支持：本原型的状态改变型动作一律走 Tool Gateway
  六段链（AD-4 写动作唯一通道），环境直执行路径按设计拒绝。
"""

from __future__ import annotations

from vasta_protocols.protocols import (
    Action,
    EnvironmentStatus,
    Observation,
)

from .ax import AxError, frontmost_app, read_display
from .calib import hard_reset


class DesktopEnv:
    """Calculator 沙盒环境（P1：单应用、单窗口）。

    hard_on_reset=True：reset= 冷启动（pkill+删 SavedState+重开）。
    False：仅焦点内双 Esc 清零——调用方已管应用生命周期时用
    （实测坑：4 秒内双杀重开，AX 树处于重建流态，读屏会撞
    「无效的索引」）。
    """

    protocol_version = "0.1.0"

    def __init__(self, app: str = "Calculator",
                 display_path: tuple[int, ...] = (),
                 *, hard_on_reset: bool = True) -> None:
        self.app = app
        self.display_path = display_path
        self.hard_on_reset = hard_on_reset
        self._running = True

    def _display(self) -> str | None:
        if not self.display_path:
            return None
        try:
            return read_display(self.app, self.display_path)
        except AxError:
            return None

    async def reset(self, seed: int | None = None) -> Observation:
        if self.hard_on_reset:
            hard_reset(self.app)  # 冷启动：显示屏归零、回基本布局
        else:
            from .ax import ensure_frontmost, key_code  # noqa: PLC0415
            import time

            ensure_frontmost(self.app)
            key_code(53)
            time.sleep(0.2)
            key_code(53)
            time.sleep(0.25)
        self._running = True
        return Observation(
            kind="reset",
            detail={"app": self.app, "display": self._display(),
                    "frontmost": frontmost_app() == self.app},
        )

    async def observe(self) -> Observation:
        return Observation(
            kind="decision",
            detail={"app": self.app,
                    "frontmost": frontmost_app() == self.app,
                    "display": self._display()},
            available_actions=["click_mark"],
        )

    async def execute(self, action: Action) -> list[Observation]:
        raise AxError(
            f"环境直执行不支持（tool={action.tool}）——写动作必须经 "
            "Tool Gateway 六段链（AD-4）"
        )

    async def status(self) -> EnvironmentStatus:
        return EnvironmentStatus(
            running=self._running,
            detail={"app": self.app, "frontmost": frontmost_app()},
        )


__all__ = ["DesktopEnv"]
