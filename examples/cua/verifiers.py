"""AX 显示屏核验器：契约期望 vs AX 直读事实（INV-06：不依赖模型自评）。

期望 DSL（prediction.changes 内）：
- ``display=126``    —— 精确等值
- ``display_contains=42`` —— 包含子串

事实来源：evidence["result"]["detail"]["display_after"]（ClickMarkTool
的 AX 直读）。已知坑（2026-11 实测）：**求值后的结果 AX 渲染为中文
语音数字**（126 →「一百二十六」）——本核验器内置中文数字解析。
"""

from __future__ import annotations

from typing import Any

from vasta_protocols.protocols import Verification, VerifierManifest

_CN_DIGIT = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000}


def parse_cn_number(text: str) -> int | None:
    """中文数字 → 整数（支持到千位；「一百二十六」→126）。"""
    text = text.strip()
    if not text:
        return None
    if text.lstrip("-").isdigit():
        return int(text)
    total, section = 0, 0
    for ch in text:
        if ch in _CN_DIGIT:
            section = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            unit = _CN_UNIT[ch]
            section = (section or 1) * unit
            total += section
            section = 0
        elif ch == "点":  # 小数：后续忽略（demo 整数域）
            break
        else:
            return None
    return total + section


def _normalize(s: str | None) -> str:
    return (s or "").replace(" ", "").replace(",", "").strip()


class AxDisplayVerifier:
    """AX 显示屏核验（名称 ax_display；经 execute_contracted 注入）。"""

    protocol_version = "0.1.0"

    def __init__(self) -> None:
        self.manifest = VerifierManifest(name="ax_display", version="1.0",
                                         kind="state")

    async def verify(self, contract_ref: str,
                     evidence: dict[str, Any]) -> Verification:
        try:
            return self._check(evidence)
        except Exception as exc:  # 单器异常 → system_error，不断链
            return Verification(outcome="system_error",
                                detail={"error": f"{type(exc).__name__}: {exc}"})

    def _check(self, evidence: dict[str, Any]) -> Verification:
        result = evidence.get("result")
        detail = result.get("detail", {}) if isinstance(result, dict) else {}
        actual_raw = detail.get("display_after")
        if actual_raw is None:
            return Verification(outcome="inconclusive",
                                detail={"reason": "AX 显示屏读数缺失"})
        actual = _normalize(str(actual_raw))
        actual_num = parse_cn_number(actual)  # 中文语音渲染 → 数字

        expects = evidence.get("expected_changes") or []
        matched: list[dict[str, Any]] = []
        for change in expects:
            if not isinstance(change, str) or "=" not in change:
                continue
            key, want = change.split("=", 1)
            key, want = key.strip(), want.strip()
            if key == "display":
                ok = actual == want or (actual_num is not None
                                        and str(actual_num) == want)
                matched.append({"rule": change, "actual": actual,
                                "actual_num": actual_num, "ok": ok})
            elif key == "display_contains":
                ok = want in actual or (actual_num is not None
                                        and want in str(actual_num))
                matched.append({"rule": change, "actual": actual,
                                "actual_num": actual_num, "ok": ok})
        if not matched:
            return Verification(outcome="inconclusive",
                                detail={"reason": "无 display 期望规则"})
        if all(m["ok"] for m in matched):
            return Verification(outcome="pass", detail={"rules": matched})
        return Verification(outcome="deviation", detail={"rules": matched})


__all__ = ["AxDisplayVerifier", "parse_cn_number"]
