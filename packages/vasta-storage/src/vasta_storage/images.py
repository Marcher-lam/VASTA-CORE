"""图像证据回看工具（FR-014，Story 2.2）。

- inspect：原始字节原样返回（get_artifact 已做哈希校验）+ 解码元数据——
  "原分辨率恢复"即不重编码；
- crop / read_pixels：半开区间 box (left, top, right, bottom)，越界拒绝；
- diff：同尺寸校验 + 变更像素统计 + 变更包围盒 + 并排对齐 PNG；
- provenance：反查引用该证据的事件（run_id=回合、seq=帧号），输出可直接
  作为 Claim 的证据引用。

一切读取经 StorageAdapter 的哈希校验取回路径（AD-3/14 作用域可选）。
"""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from typing import Any

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError

from ._scope import validate_scope_pair

_GAP = 8  # 并排 Diff 的分隔条宽（像素）


@dataclass(frozen=True)
class Box:
    """半开区间区域 (left, top, right, bottom)。"""

    left: int
    top: int
    right: int
    bottom: int

    def validate_within(self, width: int, height: int) -> None:
        if not (0 <= self.left < self.right <= width and 0 <= self.top < self.bottom <= height):
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


class InspectResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    info: ImageInfo
    provenance: dict[str, Any] | None = None


class PixelReading(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: int
    y: int
    rgba: tuple[int, int, int, int]


class DiffResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha_a: str
    sha_b: str
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    changed_pixels: int = Field(ge=0)
    bounding_box: tuple[int, int, int, int] | None = None
    side_by_side_png: bytes = Field(repr=False)


class EvidenceImages:
    """挂接 SqliteStorage 的图像证据工具。"""

    def __init__(self, store: Any) -> None:  # SqliteStorage（避免循环导入用 Any）
        self.store = store

    # ---- 内部 ----
    async def _load(
        self, sha256: str, *, tenant_id: str | None, project_id: str | None
    ) -> tuple[bytes, Image.Image]:
        raw = await self.store.get_artifact(
            sha256, tenant_id=tenant_id, project_id=project_id
        )
        try:
            image = Image.open(io.BytesIO(raw))
            image.load()
        except Exception as exc:
            raise VastaError(
                code="image.not_decodable",
                message=f"artifact {sha256[:16]}… is not a decodable image: {exc}",
            ) from exc
        return raw, image

    @staticmethod
    def _info(sha256: str, image: Image.Image, size_bytes: int) -> ImageInfo:
        return ImageInfo(
            sha256=sha256,
            format=(image.format or "UNKNOWN"),
            width=image.width,
            height=image.height,
            mode=image.mode,
            size_bytes=size_bytes,
        )

    async def provenance(
        self, sha256: str, *, tenant_id: str | None = None, project_id: str | None = None
    ) -> dict[str, Any] | None:
        """反查引用该证据的事件：{run_id, seq, type}（回合/帧号引用）。"""
        validate_scope_pair(tenant_id, project_id)
        return await asyncio.to_thread(self._provenance_sync, sha256, tenant_id, project_id)

    def _provenance_sync(
        self, sha256: str, tenant_id: str | None, project_id: str | None
    ) -> dict[str, Any] | None:
        query = (
            "SELECT e.run_id, e.seq, e.type FROM events e,"
            " json_each(json_extract(e.data, '$.payload.artifact_refs')) ref"
            " WHERE ref.value=?"
        )
        params: list[Any] = [sha256]
        if tenant_id is not None and project_id is not None:
            query += " AND e.tenant_id=? AND e.project_id=?"
            params += [tenant_id, project_id]
        query += " ORDER BY e.ts, e.run_id, e.seq LIMIT 1"
        with self.store._lock:  # noqa: SLF001（组合内访问）
            row = self.store._conn.execute(query, params).fetchone()  # noqa: SLF001
        if row is None:
            return None
        return {"run_id": row[0], "seq": row[1], "type": row[2]}

    # ---- 公开工具 ----
    async def inspect(
        self, sha256: str, *, tenant_id: str | None = None, project_id: str | None = None
    ) -> tuple[InspectResult, bytes]:
        """原分辨率恢复：原始字节原样返回（不重编码）+ 元数据 + 出处。"""
        validate_scope_pair(tenant_id, project_id)
        raw, image = await self._load(sha256, tenant_id=tenant_id, project_id=project_id)
        provenance = await self.provenance(
            sha256, tenant_id=tenant_id, project_id=project_id
        )
        result = InspectResult(
            info=self._info(sha256, image, len(raw)), provenance=provenance
        )
        return result, raw

    async def crop(
        self,
        sha256: str,
        box: Box,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> bytes:
        """区域裁剪，输出 PNG（新派生物）。"""
        validate_scope_pair(tenant_id, project_id)
        _, image = await self._load(sha256, tenant_id=tenant_id, project_id=project_id)
        box.validate_within(image.width, image.height)
        cropped = image.crop((box.left, box.top, box.right, box.bottom))
        buffer = io.BytesIO()
        cropped.save(buffer, format="PNG")
        return buffer.getvalue()

    async def read_pixels(
        self,
        sha256: str,
        box: Box,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> list[PixelReading]:
        """指定区域逐像素精确颜色值（RGBA）。"""
        validate_scope_pair(tenant_id, project_id)
        _, image = await self._load(sha256, tenant_id=tenant_id, project_id=project_id)
        box.validate_within(image.width, image.height)
        rgba = image.convert("RGBA")
        readings: list[PixelReading] = []
        for y in range(box.top, box.bottom):
            for x in range(box.left, box.right):
                readings.append(PixelReading(x=x, y=y, rgba=rgba.getpixel((x, y))))
        return readings

    async def diff(
        self,
        sha_a: str,
        sha_b: str,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> DiffResult:
        """并排 Diff：同尺寸校验 + 变更统计 + A|gap|B 对齐 PNG。"""
        validate_scope_pair(tenant_id, project_id)
        _, img_a = await self._load(sha_a, tenant_id=tenant_id, project_id=project_id)
        _, img_b = await self._load(sha_b, tenant_id=tenant_id, project_id=project_id)
        if img_a.size != img_b.size:
            raise VastaError(
                code="image.size_mismatch",
                message=f"diff requires same size: {img_a.size} vs {img_b.size}",
            )
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
            "RGBA",
            (rgba_a.width * 2 + _GAP, rgba_a.height),
            (255, 255, 255, 0),
        )
        canvas.paste(rgba_a, (0, 0))
        canvas.paste(rgba_b, (rgba_a.width + _GAP, 0))
        buffer = io.BytesIO()
        canvas.save(buffer, format="PNG")
        return DiffResult(
            sha_a=sha_a,
            sha_b=sha_b,
            width=rgba_a.width,
            height=rgba_a.height,
            changed_pixels=changed_count,
            bounding_box=bounding,
            side_by_side_png=buffer.getvalue(),
        )


__all__ = [
    "Box",
    "DiffResult",
    "EvidenceImages",
    "ImageInfo",
    "InspectResult",
    "PixelReading",
]
