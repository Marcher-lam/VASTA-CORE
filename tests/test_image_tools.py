"""Story 2.2：图像证据回看工具（FR-014）。"""

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


class TestInspect:
    async def test_original_bytes_and_metadata(self, store, images) -> None:
        raw = make_png({(0, 0): (10, 20, 30)})
        sha = await store.save_artifact(raw, mime="image/png",
                                        source="observation.capture", tenant_id=T, project_id=P)
        result, restored = await images.inspect(sha, tenant_id=T, project_id=P)

        assert restored == raw  # 原分辨率恢复：字节原样（不重编码）
        assert result.info.width == 4 and result.info.height == 4
        assert result.info.mode == "RGB"
        assert result.info.format == "PNG"
        assert result.info.sha256 == sha

    async def test_provenance_run_and_frame_reference(self, store, images) -> None:
        """AC：输出带帧号与回合号引用（可直接作 Claim 证据）。"""
        from vasta_protocols.envelope import EventEnvelope
        from vasta_protocols.ids import new_event_id, now_utc

        raw = make_png({(0, 0): (1, 2, 3)})
        sha = await store.save_artifact(
            raw, mime="image/png", source="observation.capture",
            tenant_id=T, project_id=P,
        )
        # 生产路径：观察事件引用该图像证据（seq=帧号，run_id=回合）
        await store.append_event(
            EventEnvelope.model_validate(
                {
                    "run_id": "run-img",
                    "seq": 3,
                    "type": "observation.decision",
                    "ts": now_utc(),
                    "tenant_id": T,
                    "project_id": P,
                    "event_id": new_event_id(),
                    "payload": {"artifact_refs": [sha], "kind": "decision"},
                }
            )
        )
        result, _ = await images.inspect(sha, tenant_id=T, project_id=P)
        assert result.provenance == {
            "run_id": "run-img",
            "seq": 3,
            "type": "observation.decision",
        }
        # 该引用形态可直接进入新 Claim 的 evidence 字段
        prov = await images.provenance(sha, tenant_id=T, project_id=P)
        assert prov is not None and prov["run_id"] == "run-img"
        # 他作用域反查不可见
        assert await images.provenance(sha, tenant_id="t-other", project_id=P) is None

    async def test_non_image_rejected(self, store, images) -> None:
        sha = await store.save_artifact(b"plain text, not an image", tenant_id=T, project_id=P)
        with pytest.raises(VastaError) as excinfo:
            await images.inspect(sha, tenant_id=T, project_id=P)
        assert excinfo.value.code == "image.not_decodable"

    async def test_cross_scope_unreachable(self, store, images) -> None:
        raw = make_png({})
        sha = await store.save_artifact(raw, tenant_id=T, project_id=P)
        with pytest.raises(VastaError):
            await images.inspect(sha, tenant_id="t-other", project_id=P)


class TestCropAndPixels:
    async def test_crop_region(self, store, images) -> None:
        raw = make_png({(2, 2): (200, 100, 50)})
        sha = await store.save_artifact(raw, tenant_id=T, project_id=P)
        cropped_png = await images.crop(sha, Box(2, 2, 3, 3), tenant_id=T, project_id=P)
        cropped = Image.open(io.BytesIO(cropped_png))
        assert cropped.size == (1, 1)
        assert cropped.getpixel((0, 0)) == (200, 100, 50)

    async def test_read_pixels_exact_values(self, store, images) -> None:
        raw = make_png({(1, 1): (255, 0, 0), (1, 2): (0, 0, 255)})
        sha = await store.save_artifact(raw, tenant_id=T, project_id=P)
        readings = await images.read_pixels(
            sha, Box(1, 1, 2, 3), tenant_id=T, project_id=P
        )
        by_pos = {(r.x, r.y): r.rgba for r in readings}
        assert by_pos[(1, 1)] == (255, 0, 0, 255)  # 精确颜色值（含 alpha）
        assert by_pos[(1, 2)] == (0, 0, 255, 255)

    async def test_box_out_of_bounds_rejected(self, store, images) -> None:
        sha = await store.save_artifact(make_png({}), tenant_id=T, project_id=P)
        with pytest.raises(VastaError) as excinfo:
            await images.crop(sha, Box(0, 0, 99, 99), tenant_id=T, project_id=P)
        assert excinfo.value.code == "image.box_out_of_bounds"
        # 半开区间：right=width 合法
        ok = await images.crop(sha, Box(0, 0, 4, 4), tenant_id=T, project_id=P)
        assert Image.open(io.BytesIO(ok)).size == (4, 4)

    async def test_half_scope_rejected(self, store, images) -> None:
        sha = await store.save_artifact(make_png({}), tenant_id=T, project_id=P)
        with pytest.raises(VastaError):
            await images.crop(sha, Box(0, 0, 1, 1), tenant_id=T)  # type: ignore[arg-type]


class TestDiff:
    async def test_side_by_side_and_stats(self, store, images) -> None:
        base = make_png({(1, 1): (255, 0, 0)})
        changed = make_png({(1, 1): (255, 0, 0), (2, 2): (0, 255, 0)})
        sha_a = await store.save_artifact(base, tenant_id=T, project_id=P)
        sha_b = await store.save_artifact(changed, tenant_id=T, project_id=P)

        result = await images.diff(sha_a, sha_b, tenant_id=T, project_id=P)
        assert result.changed_pixels == 1
        assert result.bounding_box == (2, 2, 3, 3)
        side = Image.open(io.BytesIO(result.side_by_side_png))
        assert side.size == (4 * 2 + 8, 4)  # A|gap|B 并排对齐
        # 左半 = A，右半 = B（同源区域对齐）
        left = side.crop((0, 0, 4, 4)).convert("RGB")
        right = side.crop((12, 0, 16, 4)).convert("RGB")
        assert left.getpixel((2, 2)) == (0, 0, 0)
        assert right.getpixel((2, 2)) == (0, 255, 0)

    async def test_identical_images_zero_diff(self, store, images) -> None:
        sha = await store.save_artifact(make_png({(0, 0): (9, 9, 9)}), tenant_id=T, project_id=P)
        result = await images.diff(sha, sha, tenant_id=T, project_id=P)
        assert result.changed_pixels == 0
        assert result.bounding_box is None

    async def test_size_mismatch_rejected(self, store, images) -> None:
        sha_a = await store.save_artifact(make_png({}), tenant_id=T, project_id=P)
        other = make_png({}, width=8, height=4)
        sha_b = await store.save_artifact(other, tenant_id=T, project_id=P)
        with pytest.raises(VastaError) as excinfo:
            await images.diff(sha_a, sha_b, tenant_id=T, project_id=P)
        assert excinfo.value.code == "image.size_mismatch"
