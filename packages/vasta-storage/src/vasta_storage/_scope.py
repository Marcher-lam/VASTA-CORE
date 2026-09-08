"""作用域参数校验（AD-14）：tenant/project 必须成对。"""

from __future__ import annotations

from vasta_protocols.errors import VastaError


def validate_scope_pair(tenant_id: str | None, project_id: str | None) -> None:
    """作用域参数必须成对出现：半作用域调用一律拒绝（fail-closed，AD-14）。"""
    if (tenant_id is None) != (project_id is None):
        raise VastaError(
            code="scope.half_pair",
            message="tenant_id and project_id must be given together or both omitted",
        )
