"""Story 2.2：图像证据回看工具（FR-014；Epic 2 评审修复版 API）。"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from vasta_protocols.errors import VastaError
from vasta_storage import Box, EvidenceImages, SqliteStorage

T, P = "t-img", "p-img"


def make_png(pixels: dict[tuple[int, int], tuple[int, int, int]], width=4, height=4) -> bytes:
    """确定性生成小图：默认全黑，指定坐标着色。"""
    image = Image.new("RGB", (width, height), (0, 0, 0))
    for (x, y), color in pixels.items():
        image.putpixel((x, y), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
async def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()


@pytest.fixture
def images(store) -> EvidenceImages:
    return EvidenceImages(store)


async def save_image(store: SqliteStorage, raw: bytes) -> str:
    return await store.save_artifact(
        raw, mime="image/png", source="observation.capture", tenant_id=T, project_id=P
    )


async def reference_event(store: SqliteStorage, sha: str, *, run_id="run-img", seq=3):
    from vasta_protocols.envelope import EventEnvelope
    from vasta_protocols.ids import new_event_id, now_utc

    await store.append_event(
        EventEnvelope.model_validate(
            {
                "run_id": run_id,
                "seq": seq,
                "type": "observation.decision",
                "ts": now_utc(),
                "tenant_id": T,
                "project_id": P,
                "event_id": new_event_id(),
                "payload": {"artifact_refs": [sha], "kind": "decision"},
            }
        )
    )


class TestInspect:
    async def test_original_bytes_and_metadata(self, store, images) -> None:
        raw = make_png({(0, 0): (10, 20, 30)})
        sha = await save_image(store, raw)
        result, restored = await images.inspect(sha, tenant_id=T, project_id=P)

        assert restored == raw  # 原分辨率恢复：字节原样（不重编码）
        assert result.info.width == 4 and result.info.height == 4
        assert result.info.mode == "RGB"
        assert result.info.format == "PNG"
        assert result.info.sha256 == sha

    async def test_provenance_typed_reference_and_limit(self, store, images) -> None:
        """出处为类型化 EvidenceReference；limit 可取多引用。"""
        sha = await save_image(store, make_png({}))
        await reference_event(store, sha, seq=3)
        await reference_event(store, sha, seq=7)

        refs = await images.provenance(sha, tenant_id=T, project_id=P)
        assert len(refs) == 1 and refs[0].seq == 3  # 默认首条（最早）
        refs_all = await images.provenance(sha, tenant_id=T, project_id=P, limit=5)
        assert [r.seq for r in refs_all] == [3, 7]  # 多引用不静默丢弃

        result, _ = await images.inspect(sha, tenant_id=T, project_id=P)
        assert result.provenance is not None
        assert result.provenance.run_id == "run-img" and result.provenance.seq == 3

    async def test_non_image_rejected(self, store, images) -> None:
        sha = await store.save_artifact(b"plain text, not an image", tenant_id=T, project_id=P)
        with pytest.raises(VastaError) as excinfo:
            await images.inspect(sha, tenant_id=T, project_id=P)
        assert excinfo.value.code == "image.not_decodable"

    async def test_cross_scope_unreachable(self, store, images) -> None:
        sha = await save_image(store, make_png({}))
        with pytest.raises(VastaError):
            await images.inspect(sha, tenant_id="t-other", project_id=P)


class TestCropAndPixels:
    async def test_crop_returns_result_with_provenance(self, store, images) -> None:
        raw = make_png({(2, 2): (200, 100, 50)})
        sha = await save_image(store, raw)
        await reference_event(store, sha, seq=5)

        result = await images.crop(sha, Box(2, 2, 3, 3), tenant_id=T, project_id=P)
        cropped = Image.open(io.BytesIO(result.png))
        assert cropped.size == (1, 1)
        assert cropped.getpixel((0, 0)) == (200, 100, 50)
        assert result.provenance is not None and result.provenance.seq == 5  # AC：输出带引用
        assert result.derived_sha256 is None  # 默认不登记

    async def test_crop_persist_derived_registers_lineage(self, store, images) -> None:
        """与 Story 2.3 打通：派生 PNG 可回链源帧。"""
        sha = await save_image(store, make_png({(1, 1): (9, 9, 9)}))
        result = await images.crop(
            sha, Box(0, 0, 2, 2), tenant_id=T, project_id=P, persist_derived=True
        )
        assert result.derived_sha256 is not None
        verification = await store.verify_lineage(
            result.derived_sha256, tenant_id=T, project_id=P
        )
        assert verification.all_verified
        rec = verification.records[0].record
        assert rec.transform == "image.crop"
        assert rec.params == {"box": [0, 0, 2, 2]}

    async def test_persist_requires_scope(self, store, images) -> None:
        sha = await save_image(store, make_png({}))
        with pytest.raises(VastaError) as excinfo:
            await images.crop(sha, Box(0, 0, 1, 1), persist_derived=True)
        assert excinfo.value.code == "scope.required"

    async def test_read_pixels_exact_values(self, store, images) -> None:
        raw = make_png({(1, 1): (255, 0, 0), (1, 2): (0, 0, 255)})
        sha = await save_image(store, raw)
        result = await images.read_pixels(sha, Box(1, 1, 2, 3), tenant_id=T, project_id=P)
        by_pos = {(r.x, r.y): r.rgba for r in result.readings}
        assert by_pos[(1, 1)] == (255, 0, 0, 255)  # 精确颜色值（含 alpha）
        assert by_pos[(1, 2)] == (0, 0, 255, 255)
        assert result.provenance is None  # 无引用事件时显式为 None

    async def test_box_out_of_bounds_rejected(self, store, images) -> None:
        sha = await save_image(store, make_png({}))
        with pytest.raises(VastaError) as excinfo:
            await images.crop(sha, Box(0, 0, 99, 99), tenant_id=T, project_id=P)
        assert excinfo.value.code == "image.box_out_of_bounds"
        ok = await images.crop(sha, Box(0, 0, 4, 4), tenant_id=T, project_id=P)
        assert Image.open(io.BytesIO(ok.png)).size == (4, 4)

    async def test_box_must_be_int(self, store, images) -> None:
        sha = await save_image(store, make_png({}))
        with pytest.raises(VastaError) as excinfo:
            await images.crop(sha, Box(0.5, 0, 2, 2), tenant_id=T, project_id=P)  # type: ignore[arg-type]
        assert excinfo.value.code == "image.box_not_int"

    async def test_half_scope_rejected(self, store, images) -> None:
        sha = await save_image(store, make_png({}))
        with pytest.raises(VastaError):
            await images.crop(sha, Box(0, 0, 1, 1), tenant_id=T)  # type: ignore[arg-type]

    async def test_blank_scope_rejected(self, store, images) -> None:
        sha = await save_image(store, make_png({}))
        with pytest.raises(VastaError) as excinfo:
            await images.crop(sha, Box(0, 0, 1, 1), tenant_id="", project_id=P)
        assert excinfo.value.code == "scope.blank"


class TestDiff:
    async def test_side_by_side_stats_and_dual_provenance(self, store, images) -> None:
        base = make_png({(1, 1): (255, 0, 0)})
        changed = make_png({(1, 1): (255, 0, 0), (2, 2): (0, 255, 0)})
        sha_a = await save_image(store, base)
        sha_b = await save_image(store, changed)
        await reference_event(store, sha_a, run_id="run-a", seq=1)
        await reference_event(store, sha_b, run_id="run-b", seq=2)

        result = await images.diff(sha_a, sha_b, tenant_id=T, project_id=P)
        assert result.changed_pixels == 1
        assert result.bounding_box == (2, 2, 3, 3)
        side = Image.open(io.BytesIO(result.side_by_side_png))
        assert side.size == (4 * 2 + 8, 4)
        left = side.crop((0, 0, 4, 4)).convert("RGB")
        right = side.crop((12, 0, 16, 4)).convert("RGB")
        assert left.getpixel((2, 2)) == (0, 0, 0)
        assert right.getpixel((2, 2)) == (0, 255, 0)
        # AC：输出带帧号/回合号引用（双出处，Story 2.2 评审修复）
        assert result.provenance_a is not None and result.provenance_a.run_id == "run-a"
        assert result.provenance_b is not None and result.provenance_b.run_id == "run-b"

    async def test_diff_persist_derived(self, store, images) -> None:
        sha_a = await save_image(store, make_png({}))
        sha_b = await save_image(store, make_png({(0, 0): (1, 1, 1)}))
        result = await images.diff(
            sha_a, sha_b, tenant_id=T, project_id=P, persist_derived=True
        )
        verification = await store.verify_lineage(
            result.derived_sha256, tenant_id=T, project_id=P  # type: ignore[arg-type]
        )
        assert verification.all_verified
        assert verification.records[0].record.transform == "image.diff"

    async def test_identical_images_zero_diff(self, store, images) -> None:
        sha = await save_image(store, make_png({(0, 0): (9, 9, 9)}))
        result = await images.diff(sha, sha, tenant_id=T, project_id=P)
        assert result.changed_pixels == 0
        assert result.bounding_box is None

    async def test_size_mismatch_rejected(self, store, images) -> None:
        sha_a = await save_image(store, make_png({}))
        sha_b = await save_image(store, make_png({}, width=8, height=4))
        with pytest.raises(VastaError) as excinfo:
            await images.diff(sha_a, sha_b, tenant_id=T, project_id=P)
        assert excinfo.value.code == "image.size_mismatch"


class TestLimits:
    async def test_read_pixels_area_capped(self, store, images, monkeypatch) -> None:
        import vasta_storage.images as images_module

        monkeypatch.setattr(images_module, "_MAX_SCAN_PIXELS", 4)
        sha = await save_image(store, make_png({}))
        # 16 像素帧解码不受影响；扫描上限压到 4：整帧读取被拒，小区域仍可
        with pytest.raises(VastaError) as excinfo:
            await images.read_pixels(sha, Box(0, 0, 4, 4), tenant_id=T, project_id=P)
        assert excinfo.value.code == "image.too_large"
        ok = await images.read_pixels(sha, Box(0, 0, 2, 2), tenant_id=T, project_id=P)
        assert len(ok.readings) == 4
