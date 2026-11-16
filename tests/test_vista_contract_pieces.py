"""Story va-5（吸收方案 §七 序⑤）：契约层三件（VISTA contracts.py 摘取）。

- **D 构造期能力-效果矩阵**：ToolManifest risk ↔ read_only 一致性在
  构造期强制（VISTA capability-effect 矩阵同精神：声明与效果不符
  构造即炸，不等到运行期）。规则（蓝图 §12.4 语义）：read_only=True
  → risk ∈ {R0, R1}；read_only=False → risk ∈ {R2, R3, R4}。
- **E 评测器状态隔离**：VastaLabTask.public_view()——模型可见投影，
  隐藏规则/噪声/偏差注入/种子（评测器状态）结构性缺席（VISTA
  "Evaluator state is deliberately absent"）。
- **F derived 证据强制血缘**：Observation 派生观察必须声明
  derived_from（源工件引用），非派生不得声明（VISTA 原规则）。
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from vasta_eval.evaluation import VastaLabTask
from vasta_protocols.protocols.environment import Observation
from vasta_protocols.protocols.tool import ToolManifest


def _manifest(**kw: object) -> ToolManifest:
    base: dict[str, object] = {"name": "t.echo", "version": "0.1.0",
                               "risk": "R2", "read_only": False,
                               "idempotent": False}
    base.update(kw)
    return ToolManifest(**base)  # type: ignore[arg-type]


# ---- D：能力-效果矩阵（构造期 fail-closed） ----

def test_matrix_readonly_must_be_low_risk() -> None:
    with pytest.raises(ValidationError, match="R0|R1"):
        _manifest(risk="R2", read_only=True)


def test_matrix_mutating_must_be_elevated_risk() -> None:
    with pytest.raises(ValidationError, match="R2"):
        _manifest(risk="R0", read_only=False)


def test_matrix_compliant_shapes_pass() -> None:
    assert _manifest(risk="R1", read_only=True, idempotent=True).risk == "R1"
    assert _manifest(risk="R3", read_only=False).risk == "R3"


def test_matrix_rejects_readonly_r4() -> None:
    with pytest.raises(ValidationError):
        _manifest(risk="R4", read_only=True)


# ---- E：评测器状态隔离（public_view 投影） ----

def test_public_view_hides_evaluator_state() -> None:
    task = VastaLabTask(task_id="lab-1", hidden_rule="teleport", noise=0.3,
                        deviation_injection=True, seed=42)
    dumped = json.dumps(task.public_view())
    for secret in ("teleport", "0.3", "deviation_injection", '"seed"', "42"):
        assert secret not in dumped, f"评测器状态泄漏：{secret}"


def test_public_view_retains_agent_visible_fields() -> None:
    task = VastaLabTask(task_id="lab-1", grid_size=5, goal=(4, 4))
    view = task.public_view()
    assert view["task_id"] == "lab-1"
    assert view["grid_size"] == 5 and view["goal"] == [4, 4]


# ---- F：derived 证据强制 derived_from ----

def test_derived_observation_requires_sources() -> None:
    with pytest.raises(ValidationError, match="derived_from"):
        Observation(kind="decision", derived=True)


def test_derived_observation_with_sources_ok() -> None:
    obs = Observation(kind="decision", derived=True,
                      derived_from=["a" * 64], artifact_refs=["a" * 64])
    assert obs.derived and obs.derived_from == ["a" * 64]


def test_underived_observation_must_not_declare_sources() -> None:
    with pytest.raises(ValidationError, match="derived_from"):
        Observation(kind="decision", derived_from=["a" * 64])


def test_plain_observation_backward_compatible() -> None:
    obs = Observation(kind="decision")
    assert obs.derived is False and obs.derived_from == []
