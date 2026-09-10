"""Story 8.12：多模态按需派生（FR-015/016，G5）——要时才算，不默认全量。

零依赖 deriver（确定性）；派生经 save_derived 带血缘；幂等同址。
"""

from __future__ import annotations

import json

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.derive import (
    DeriverRegistry,
    default_registry,
    derive_on_demand,
)


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


async def put_text(store, text: str) -> str:
    return await store.save_artifact(text.encode("utf-8"), mime="text/plain")


class TestDeriveOnDemand:
    async def test_summary_derived_with_lineage(self, store) -> None:
        """AC：显式请求 → 派生物带血缘（verified）+ 参数可回读。"""
        src = await put_text(store, "第一句讲订单。第二句讲发货。第三句讲完成。")
        ref = await derive_on_demand(store, src, "text_summary",
                                     {"max_sentences": 1})
        assert ref.source_sha256 == src
        blob = await store.get_artifact(ref.derived_sha256)
        assert "。".encode() in blob  # 有句子产出
        # 血缘 verified + params 原样回读
        records = await store.lineage(ref.derived_sha256)
        assert records, "血缘必须登记（按需触发留痕）"
        params = records[0].params if hasattr(records[0], "params") \
            else records[0].get("params")
        assert params == {"max_sentences": 1}

    async def test_not_derived_by_default(self, store) -> None:
        """AC：不请求不派生——保存源零派生。"""
        before = len(await store.list_artifacts("t-default", "p-default"))
        await put_text(store, "一段不需要派生的文本。")
        after = len(await store.list_artifacts("t-default", "p-default"))
        assert after - before == 1  # 只有源，零派生

    async def test_idempotent_same_params_same_sha(self, store) -> None:
        src = await put_text(store, "同参数幂等测试文本。第二句。")
        r1 = await derive_on_demand(store, src, "text_summary",
                                    {"max_sentences": 1})
        r2 = await derive_on_demand(store, src, "text_summary",
                                    {"max_sentences": 1})
        assert r1.derived_sha256 == r2.derived_sha256  # CAS 同址
        records = await store.lineage(r1.derived_sha256)
        assert len(records) == 1  # 血缘幂等不重复登记

    async def test_different_params_different_derived(self, store) -> None:
        """异参数不误去重——两句摘要与一句摘要是不同派生物。"""
        src = await put_text(store, "甲句子。乙句子。丙句子。")
        r1 = await derive_on_demand(store, src, "text_summary",
                                    {"max_sentences": 1})
        r2 = await derive_on_demand(store, src, "text_summary",
                                    {"max_sentences": 2})
        assert r1.derived_sha256 != r2.derived_sha256

    async def test_unregistered_kind_fail_closed(self, store) -> None:
        src = await put_text(store, "text")
        with pytest.raises(VastaError) as excinfo:
            await derive_on_demand(store, src, "real_ocr", {})
        assert "未注册" in str(excinfo.value) or "unregistered" in str(
            excinfo.value
        ).lower()

    async def test_unknown_source_fail_fast(self, store) -> None:
        with pytest.raises(VastaError):
            await derive_on_demand(store, "0" * 64, "text_summary", {})


class TestDerivers:
    async def test_embedding_deterministic_fixed_dim(self, store) -> None:
        """确定性哈希向量：同输入同输出、维数固定、可比较。"""
        src = await put_text(store, "订单 已 发货 完成")
        r1 = await derive_on_demand(store, src, "text_embedding",
                                    {"dim": 64})
        r2 = await derive_on_demand(store, src, "text_embedding",
                                    {"dim": 64})
        assert r1.derived_sha256 == r2.derived_sha256
        vec = json.loads(await store.get_artifact(r1.derived_sha256))
        assert len(vec["vector"]) == 64
        # 近邻文本相似度更高（演示级语义代理）
        near = await put_text(store, "订单 已 发货 完成 签收")
        rn = await derive_on_demand(store, near, "text_embedding",
                                    {"dim": 64})
        far = await put_text(store, "天气 晴朗 适合 散步")
        rf = await derive_on_demand(store, far, "text_embedding",
                                    {"dim": 64})
        vn = json.loads(await store.get_artifact(rn.derived_sha256))["vector"]
        vf = json.loads(await store.get_artifact(rf.derived_sha256))["vector"]
        v0 = vec["vector"]

        def cosine(a, b):
            dot = sum(x * y for x, y in zip(a, b, strict=True))
            na = sum(x * x for x in a) ** 0.5
            nb = sum(x * x for x in b) ** 0.5
            return dot / (na * nb) if na and nb else 0.0

        assert cosine(v0, vn) > cosine(v0, vf)  # 近邻 > 无关

    async def test_text_extract_regex(self, store) -> None:
        src = await put_text(store, "订单 A102 状态 shipped 金额 99.5")
        ref = await derive_on_demand(store, src, "text_extract",
                                     {"fields": {"order_id": r"A\d+",
                                                 "status": r"shipped|pending"}})
        out = json.loads(await store.get_artifact(ref.derived_sha256))
        assert out["order_id"] == "A102"
        assert out["status"] == "shipped"

    async def test_media_window_slices_and_aligns(self, store) -> None:
        """AC：视频时间窗/音频对齐（清单形态）——窗口切片 + 对齐键保留。"""
        manifest = {
            "kind": "video",
            "duration_s": 120,
            "segments": [
                {"start": 0, "end": 30, "label": "intro",
                 "align": {"audio": "a-001"}},
                {"start": 30, "end": 70, "label": "order_demo",
                 "align": {"audio": "a-002"}},
                {"start": 70, "end": 120, "label": "outro",
                 "align": {"audio": "a-003"}},
            ],
        }
        src = await store.save_artifact(
            json.dumps(manifest).encode("utf-8"),
            mime="application/json",
        )
        ref = await derive_on_demand(store, src, "media_window",
                                     {"from_s": 20, "to_s": 80})
        window = json.loads(await store.get_artifact(ref.derived_sha256))
        labels = [s["label"] for s in window["segments"]]
        assert labels == ["intro", "order_demo", "outro"]  # 相交即入窗
        # 窗口边界裁剪
        assert window["segments"][0]["start"] == 20
        assert window["segments"][-1]["end"] == 80
        # 对齐键保留（音视频对齐可溯源）
        assert window["segments"][1]["align"] == {"audio": "a-002"}
        assert window["source_duration_s"] == 120


class TestRegistry:
    def test_default_registry_has_four_derivers(self) -> None:
        names = sorted(default_registry().kinds())
        assert names == ["media_window", "text_embedding", "text_extract",
                         "text_summary"]

    def test_custom_deriver_registerable(self) -> None:
        async def upper(payload: bytes, params: dict) -> bytes:
            return payload.upper()

        registry = DeriverRegistry()
        registry.register("upper", upper)
        assert "upper" in registry.kinds()
