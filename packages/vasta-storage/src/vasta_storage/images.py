"""图像证据回看工具（FR-014，Story 2.2；Epic 2 评审修复版）。

- inspect：原始字节原样返回（get_artifact 已做哈希校验）+ 解码元数据——
  "原分辨率恢复"即不重编码；
- crop / read_pixels：半开区间 box (left, top, right, bottom)，坐标必须
  int，越界拒绝；read_pixels 有扫描像素上限；
- diff：同尺寸校验 + 变更像素统计 + 变更包围盒 + 并排对齐 PNG；
- provenance：反查引用该证据的事件（run_id=回合、seq=帧号），返回类型化
  EvidenceReference（limit 可调，默认首条），可直接作为 Claim 的证据引用；
- 全部解码与像素计算经 asyncio.to_thread（AD-10）；解码有面积上限；
- crop/diff 可选 persist_derived=True：输出 PNG 经 store.save_derived 登记
  血缘（transform=image.crop / image.diff），派生帧可回链源帧（Story 2.3 打通），
  需要显式作用域。
"""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError

from ._scope import validate_scope_pair

if TYPE_CHECKING:
    from .sqlite_store import SqliteStorage

_GAP = 8  # 并排 Diff 的分隔条宽（像素）
#: 解码面积上限（防解压炸弹级大帧失控）。
_MAX_PIXELS = 890_000
#: 逐像素扫描上限（read_pixels 区域 / diff 帧面积）。
_MAX_SCAN_PIXELS = 890_000
_IMAGES_VERSION = "vasta-storage.images/0.1"


@dataclass(frozen=True)
class Box:
    """半开区间区域 (left, top, right, bottom)；坐标必须为 int。"""

    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self) -> None:
        if not all(
            isinstance(v, int) and not isinstance(v, bool)
            for v in (self.left, self.top, self.right, self.bottom)
        ):
            raise VastaError(code="image.box_not_int", message="box 坐标必须为 int")

    @property
    def area(self) -> int:
        return max(self.right - self.left, 0) * max(self.bottom - self.top, 0)

    def validate_within(self, width: int, height: int) -> None:
        if not (
            0 <= self.left < self.right <= width and 0 <= self.top < self.bottom <= height
        ):
            raise VastaError(
                code="image.box_out_of_bounds",
                message=(
                    f"box ({self.left},{self.top},{self.right},{self.bottom})"
                    f" outside image {width}x{height} (half-open intervals)"
                ),
            )

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


class ImageInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha256: str
    format: str
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    mode: str
    size_bytes: int = Field(ge=0)


class EvidenceReference(BaseModel):
    """帧号/回合号引用（可直接入 Claim.evidence）。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    seq: int
    type: str


class InspectResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    info: ImageInfo
    provenance: EvidenceReference | None = None


class CropResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    png: bytes = Field(repr=False)
    provenance: EvidenceReference | None = None
    derived_sha256: str | None = None


class PixelReading(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: int
    y: int
    rgba: tuple[int, int, int, int]


class ReadPixelsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    readings: list[PixelReading]
    provenance: EvidenceReference | None = None


class DiffResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha_a: str
    sha_b: str
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    changed_pixels: int = Field(ge=0)
    bounding_box: tuple[int, int, int, int] | None = None
    side_by_side_png: bytes = Field(repr=False)
    provenance_a: EvidenceReference | None = None
    provenance_b: EvidenceReference | None = None
    derived_sha256: str | None = None


def _open_image(raw: bytes, sha: str) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except UnidentifiedImageError as exc:
        raise VastaError(
            code="image.not_decodable",
            message=f"artifact {sha[:16]}… is not a decodable image: {exc}",
        ) from exc
    except Exception as exc:  # 解压限制/内存等不冒充格式问题
        raise VastaError(
            code="image.decode_failed",
            message=f"decoding {sha[:16]}… failed: {type(exc).__name__}: {exc}",
        ) from exc
    if image.width * image.height > _MAX_PIXELS:
        raise VastaError(
            code="image.too_large",
            message=f"{image.width}x{image.height} exceeds decode limit {_MAX_PIXELS}",
        )
    return image


def _crop_sync(image: Image.Image, box: Box) -> bytes:
    cropped = image.crop((box.left, box.top, box.right, box.bottom))
    buffer = io.BytesIO()
    cropped.save(buffer, format="PNG")
    return buffer.getvalue()


def _read_pixels_sync(
    image: Image.Image, box: Box
) -> list[tuple[int, int, tuple[int, int, int, int]]]:
    rgba = image.convert("RGBA")
    out = []
    for y in range(box.top, box.bottom):
        for x in range(box.left, box.right):
            out.append((x, y, rgba.getpixel((x, y))))
    return out


def _diff_sync(
    img_a: Image.Image, img_b: Image.Image
) -> tuple[int, tuple[int, int, int, int] | None, bytes]:
    rgba_a = img_a.convert("RGBA")
    rgba_b = img_b.convert("RGBA")
    changed_count = 0
    min_x = min_y = None
    max_x = max_y = None
    for y in range(rgba_a.height):
        for x in range(rgba_a.width):
            if rgba_a.getpixel((x, y)) != rgba_b.getpixel((x, y)):
                changed_count += 1
                if min_x is None or x < min_x:
                    min_x = x
                if min_y is None or y < min_y:
                    min_y = y
                if max_x is None or x > max_x:
                    max_x = x
                if max_y is None or y > max_y:
                    max_y = y
    bounding = (
        None
        if changed_count == 0
        else (min_x, min_y, max_x + 1, max_y + 1)  # 半开区间，与 Box 一致
    )
    canvas = Image.new(
        "RGBA", (rgba_a.width * 2 + _GAP, rgba_a.height), (255, 255, 255, 0)
    )
    canvas.paste(rgba_a, (0, 0))
    canvas.paste(rgba_b, (rgba_a.width + _GAP, 0))
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return changed_count, bounding, buffer.getvalue()


class EvidenceImages:
    """挂接 SqliteStorage 的图像证据工具。"""

    def __init__(self, store: SqliteStorage) -> None:
        self.store = store

    # ---- 内部 ----
    async def _load(
        self, sha256: str, *, tenant_id: str | None, project_id: str | None
    ) -> tuple[bytes, Image.Image]:
        raw = await self.store.get_artifact(
            sha256, tenant_id=tenant_id, project_id=project_id
        )
        image = await asyncio.to_thread(_open_image, raw, sha256)
        return raw, image

    async def provenance(
        self,
        sha256: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        limit: int = 1,
    ) -> list[EvidenceReference]:
        """反查引用该证据的事件（帧=seq，回合=run_id）；limit>1 取多引用。"""
        validate_scope_pair(tenant_id, project_id)
        if limit <= 0:
            raise VastaError(code="search.bad_limit", message="limit 必须为正整数")
        rows = await asyncio.to_thread(
            self._provenance_sync, sha256, tenant_id, project_id, limit
        )
        return [EvidenceReference(run_id=r[0], seq=r[1], type=r[2]) for r in rows]

    def _provenance_sync(
        self, sha256: str, tenant_id: str | None, project_id: str | None, limit: int
    ) -> list[tuple[str, int, str]]:
        query = (
            "SELECT e.run_id, e.seq, e.type FROM events e,"
            " json_each(json_extract(e.data, '$.payload.artifact_refs')) ref"
            " WHERE ref.value=?"
        )
        params: list[Any] = [sha256]
        if tenant_id is not None and project_id is not None:
            query += " AND e.tenant_id=? AND e.project_id=?"
            params += [tenant_id, project_id]
        query += " ORDER BY e.ts, e.run_id, e.seq LIMIT ?"
        params.append(limit)
        with self.store._lock:  # noqa: SLF001 （组合内访问）
            return self.store._conn.execute(query, params).fetchall()  # noqa: SLF001

    async def _first_reference(
        self, sha: str, tenant_id: str | None, project_id: str | None
    ) -> EvidenceReference | None:
        refs = await self.provenance(sha, tenant_id=tenant_id, project_id=project_id)
        return refs[0] if refs else None

    async def _persist_derived(
        self,
        png: bytes,
        *,
        source_sha: str,
        transform: str,
        params: dict[str, Any],
        tenant_id: str,
        project_id: str,
    ) -> str:
        return await self.store.save_derived(
            png,
            source_sha256=source_sha,
            transform=transform,
            params=params,
            transformer_version=_IMAGES_VERSION,
            tenant_id=tenant_id,
            project_id=project_id,
        )

    # ---- 公开工具 ----
    async def inspect(
        self, sha256: str, *, tenant_id: str | None = None, project_id: str | None = None
    ) -> tuple[InspectResult, bytes]:
        """原分辨率恢复：原始字节原样返回（不重编码）+ 元数据 + 出处。"""
        validate_scope_pair(tenant_id, project_id)
        raw, image = await self._load(sha256, tenant_id=tenant_id, project_id=project_id)
        provenance = await self._first_reference(
            sha256, tenant_id, project_id
        )
        result = InspectResult(
            info=ImageInfo(
                sha256=sha256,
                format=(image.format or "UNKNOWN"),
                width=image.width,
                height=image.height,
                mode=image.mode,
                size_bytes=len(raw),
            ),
            provenance=provenance,
        )
        return result, raw

    async def crop(
        self,
        sha256: str,
        box: Box,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        persist_derived: bool = False,
    ) -> CropResult:
        """区域裁剪（PNG 输出，携带出处；可选登记血缘）。"""
        validate_scope_pair(tenant_id, project_id)
        _, image = await self._load(sha256, tenant_id=tenant_id, project_id=project_id)
        box.validate_within(image.width, image.height)
        png = await asyncio.to_thread(_crop_sync, image, box)
        provenance = await self._first_reference(sha256, tenant_id, project_id)
        derived_sha: str | None = None
        if persist_derived:
            if tenant_id is None or project_id is None:
                raise VastaError(
                    code="scope.required",
                    message="persist_derived 需要显式作用域（tenant+project）",
                )
            derived_sha = await self._persist_derived(
                png,
                source_sha=sha256,
                transform="image.crop",
                params={"box": [box.left, box.top, box.right, box.bottom]},
                tenant_id=tenant_id,
                project_id=project_id,
            )
        return CropResult(png=png, provenance=provenance, derived_sha256=derived_sha)

    async def read_pixels(
        self,
        sha256: str,
        box: Box,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> ReadPixelsResult:
        """指定区域逐像素精确颜色值（RGBA）；扫描面积有上限。"""
        validate_scope_pair(tenant_id, project_id)
        _, image = await self._load(sha256, tenant_id=tenant_id, project_id=project_id)
        box.validate_within(image.width, image.height)
        if box.area > _MAX_SCAN_PIXELS:
            raise VastaError(
                code="image.too_large",
                message=f"read_pixels 区域 {box.area} 像素超过上限 {_MAX_SCAN_PIXELS}",
            )
        raw_readings = await asyncio.to_thread(_read_pixels_sync, image, box)
        readings = [PixelReading(x=x, y=y, rgba=rgba) for x, y, rgba in raw_readings]
        provenance = await self._first_reference(sha256, tenant_id, project_id)
        return ReadPixelsResult(readings=readings, provenance=provenance)

    async def diff(
        self,
        sha_a: str,
        sha_b: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        persist_derived: bool = False,
    ) -> DiffResult:
        """并排 Diff：同尺寸校验 + 变更统计 + A|gap|B 对齐 PNG（携带双出处）。"""
        validate_scope_pair(tenant_id, project_id)
        _, img_a = await self._load(sha_a, tenant_id=tenant_id, project_id=project_id)
        _, img_b = await self._load(sha_b, tenant_id=tenant_id, project_id=project_id)
        if img_a.size != img_b.size:
            raise VastaError(
                code="image.size_mismatch",
                message=f"diff requires same size: {img_a.size} vs {img_b.size}",
            )
        if img_a.width * img_a.height > _MAX_SCAN_PIXELS:
            raise VastaError(
                code="image.too_large",
                message=f"diff 帧面积超过扫描上限 {_MAX_SCAN_PIXELS}",
            )
        changed, bounding, png = await asyncio.to_thread(_diff_sync, img_a, img_b)
        prov_a = await self._first_reference(sha_a, tenant_id, project_id)
        prov_b = await self._first_reference(sha_b, tenant_id, project_id)
        derived_sha: str | None = None
        if persist_derived:
            if tenant_id is None or project_id is None:
                raise VastaError(
                    code="scope.required",
                    message="persist_derived 需要显式作用域（tenant+project）",
                )
            derived_sha = await self._persist_derived(
                png,
                source_sha=sha_a,
                transform="image.diff",
                params={"sha_a": sha_a, "sha_b": sha_b},
                tenant_id=tenant_id,
                project_id=project_id,
            )
        return DiffResult(
            sha_a=sha_a,
            sha_b=sha_b,
            width=img_a.width,
            height=img_a.height,
            changed_pixels=changed,
            bounding_box=bounding,
            side_by_side_png=png,
            provenance_a=prov_a,
            provenance_b=prov_b,
            derived_sha256=derived_sha,
        )


__all__ = [
    "Box",
    "CropResult",
    "DiffResult",
    "EvidenceImages",
    "EvidenceReference",
    "ImageInfo",
    "InspectResult",
    "PixelReading",
    "ReadPixelsResult",
]
