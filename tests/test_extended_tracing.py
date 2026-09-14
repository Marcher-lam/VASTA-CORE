"""Story 12.3：扩展模型事件留痕（11.9 拆分裁决接线腿，G0）。"""

from __future__ import annotations

import pytest

from vasta_model_lab.extended_models import (
    CausalModel,
    CompositeModel,
    ConstraintModel,
    ProbabilisticWorldModel,
)
from vasta_model_lab.extended_tracing import (
    model_kind_of,
    register_extended_model,
    trace_extended_model_use,
    validate_extended_model,
)
from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


def events_of(store, event_type: str) -> list:
    return [e for e in store.iter_run_events("cognition")
            if e.type == event_type]


PROB = ProbabilisticWorldModel({"s": {"a": 0.5, "b": 0.5}}, seed=7)
CONSTRAINT = ConstraintModel(constraints=[lambda st: st.get("ok") is True])


class TestRegister:
    async def test_registered_traced_with_kind(self, store) -> None:
        """AC：创建扩展模型 → 模型类型入 world_model.registered。"""
        await register_extended_model(store, PROB, name="prob-1")
        events = events_of(store, "world_model.registered")
        assert events[-1].payload == {"kind": "probabilistic",
                                      "name": "prob-1"}

    def test_unknown_kind_rejected(self) -> None:
        with pytest.raises(VastaError) as e:
            model_kind_of(object())
        assert e.value.code == "model_lab.unknown_model_kind"


class TestValidate:
    async def test_constraint_feasible_passed(self, store) -> None:
        passed = await validate_extended_model(store, CONSTRAINT,
                                               name="c-1")
        assert passed
        events = events_of(store, "world_model.validated")
        assert events[-1].payload["kind"] == "constraint"
        assert events[-1].payload["passed"] is True

    async def test_causal_cycle_fails_validation(self, store) -> None:
        """因果依赖环 → validated passed=False（unresolved 细节）。"""
        cyclic = CausalModel(dependencies={"a": ["b"], "b": ["a"]})
        passed = await validate_extended_model(store, cyclic, name="x")
        assert not passed
        events = events_of(store, "world_model.validated")
        assert events[-1].payload["detail"]["unresolved"] == ["a", "b"]

    async def test_probabilistic_recheck(self, store) -> None:
        passed = await validate_extended_model(store, PROB, name="p-1")
        assert passed

    async def test_composite_shape(self, store) -> None:
        model = CompositeModel(component_rules=[{"go": {"set": {"x": 1}}}])
        assert await validate_extended_model(store, model, name="m-1")


class TestUse:
    async def test_use_phase_traced(self, store) -> None:
        """AC：使用相位入 world_model.used。"""
        await trace_extended_model_use(store, PROB, name="prob-1",
                                       phase="sampled")
        events = events_of(store, "world_model.used")
        assert events[-1].payload == {
            "kind": "probabilistic", "name": "prob-1",
            "phase": "sampled"}

    async def test_empty_phase_rejected(self, store) -> None:
        with pytest.raises(VastaError) as e:
            await trace_extended_model_use(store, PROB, name="p",
                                           phase="")
        assert e.value.code == "model_lab.bad_phase"


class TestCatalogClosedLoop:
    def test_catalog_zero_drift_with_new_types(self) -> None:
        """AC：新事件类型入目录（11.1 AST 守卫零漂移——registered/
        used 经包装发射面被扫描器捕获）。"""
        from pathlib import Path

        from vasta_protocols.catalog_gen import catalog_drift
        from vasta_protocols.schema_registry import _EVENT_CATALOG

        root = Path(__file__).resolve().parent.parent
        drift = catalog_drift(_EVENT_CATALOG, root=root)
        assert drift == {"missing": [], "extra": []}
        assert {"registered", "used", "validated"} \
            <= _EVENT_CATALOG["world_model"]
