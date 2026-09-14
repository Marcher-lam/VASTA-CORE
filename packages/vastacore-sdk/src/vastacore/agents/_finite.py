"""数值守卫共享 helper（Story 12.2，Epic 11 复盘 F4/item-26，G0）。

Epic 11 评审修复曾把 ``math.isfinite`` 入口守卫散布 4 模块 7 处——
NaN/inf 对全部比较判失效的家族根因（边界猎手跨模块模式①）各写各的。
本模块收口为单一守卫：非有限（或可选地负值）即拒（fail-closed）。
"""

from __future__ import annotations

import math

from vasta_protocols.errors import VastaError


def require_finite(
    value: float, *, field: str, code: str,
    message: str = "", non_negative: bool = False,
) -> float:
    """要求数值为有限（可选非负）——否则 VastaError 拒。

    ``non_negative=True`` 时同时拒负值（负权重/负预算使闸门方向
    反转或敞口洗白）。巨整（``10**400`` 一类——float 转换溢出）同
    样拒（VastaError 而非裸 OverflowError）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VastaError(
            code=code,
            message=message or f"{field}={value!r} 须为数值",
        )
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False  # 巨整超 float 域——按非有限拒
    if not finite or (non_negative and value < 0):
        raise VastaError(
            code=code,
            message=message or (
                f"{field}={value!r} 须为{'非负' if non_negative else ''}"
                "有限数（NaN/inf 使全部比较判失效）"),
        )
    return value


__all__ = ["require_finite"]
