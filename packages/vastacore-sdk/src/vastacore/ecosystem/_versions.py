"""版本语义共享 helper（Story 12 评审修复 VER-1——盲审 M1/边界 8-1/8-2/L5）。

注册表 latest 解析与兼容矩阵共用同一版本语义：

- 点分数字解析（``parse_version``）——非法形态（预发布后缀、空段）
  抛 VastaError（契约异常信封），两侧同口径；
- 比较前**右补零对齐**（``1.0.0 == 1.0``——裸元组比较三问三错）；
- registry latest 用数值序（此前字典序使 1.9.0 战胜 1.10.0）。
"""

from __future__ import annotations

import re

from vasta_protocols.errors import VastaError

_VERSION = re.compile(r"^\d+(?:\.\d+)*$")


def parse_version(version: str, *, field: str = "version",
                  code: str = "trust.bad_version") -> tuple[int, ...]:
    """点分数字版本 → 整数元组；非法形态即拒（VastaError）。"""
    if not isinstance(version, str) or not _VERSION.match(version.strip()):
        raise VastaError(
            code=code,
            message=(f"{field}={version!r} 须为点分数字版本"
                     "（如 1.10.0——预发布后缀不支持）"),
        )
    return tuple(int(p) for p in version.strip().split("."))


def compare_versions(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    """右补零对齐后比较（1.0.0 ≡ 1.0）。"""
    width = max(len(a), len(b))
    pa = a + (0,) * (width - len(a))
    pb = b + (0,) * (width - len(b))
    return (pa > pb) - (pa < pb)


__all__ = ["compare_versions", "parse_version"]
