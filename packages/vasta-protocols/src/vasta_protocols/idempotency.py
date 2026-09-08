"""幂等键唯一派生函数（AD-11，Story 3.2 评审修复：入 protocols）。

键 = run_id:plan_step_id:tool:canonical_args_hash——禁止各单元自定。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _stringify_keys(value: Any) -> Any:
    """递归把非字符串 dict 键转为字符串——sort_keys 对混合键会 TypeError。"""
    if isinstance(value, dict):
        return {str(k): _stringify_keys(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stringify_keys(v) for v in value]
    return value


def canonical_args(args: dict[str, Any]) -> str:
    """键序无关的参数规范化 JSON（混合键先字符串化）。"""
    return json.dumps(
        _stringify_keys(args or {}), sort_keys=True, separators=(",", ":"), default=repr
    )


def canonical_args_hash(args: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_args(args).encode("utf-8")).hexdigest()


def idempotency_key(
    run_id: str, plan_step_id: str, tool: str, args: dict[str, Any]
) -> str:
    """AD-11 唯一确定函数：幂等键派生。"""
    return f"{run_id}:{plan_step_id}:{tool}:{canonical_args_hash(args)}"


__all__ = ["canonical_args", "canonical_args_hash", "idempotency_key"]
