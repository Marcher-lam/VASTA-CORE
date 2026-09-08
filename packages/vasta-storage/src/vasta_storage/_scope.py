"""作用域参数校验（AD-14）：tenant/project 必须成对；标签键白名单。"""

from __future__ import annotations

import re

from vasta_protocols.errors import VastaError

_KEY_RE = re.compile(r"^[A-Za-z0-9_]+$")


def validate_scope_pair(tenant_id: str | None, project_id: str | None) -> None:
    """作用域参数必须成对出现且非空白：半作用域/空串一律拒绝（fail-closed）。"""
    if (tenant_id is None) != (project_id is None):
        raise VastaError(
            code="scope.half_pair",
            message="tenant_id and project_id must be given together or both omitted",
        )
    if tenant_id is not None and (
        not tenant_id.strip() or not project_id.strip()  # type: ignore[union-attr]
    ):
        raise VastaError(
            code="scope.blank",
            message="tenant_id/project_id 不能为空白字符串",
        )


def validate_tag_key(key: str) -> str:
    """标签/载荷过滤键白名单：仅字母数字下划线（与检索侧一致，存查对称）。"""
    if not _KEY_RE.fullmatch(key):
        raise VastaError(
            code="search.bad_key",
            message=f"{key!r}: tag 键仅允许字母/数字/下划线（检索侧同规则）",
        )
    return key
