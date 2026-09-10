"""S3BlobStore（Story 9.1，Team 档——任意 S3 兼容对象存储）。

- boto3 **可选 extra**（pyproject [project.optional-dependencies].s3）：
  延迟导入；**客户端可注入**（bucket_owner 协议：put_object/get_object/
  head_object/delete_object）——测试用内存 Fake 零服务覆盖；
- 键布局：``{prefix}/{sha[:2]}/{sha}``（分桶）；元数据携带
  tenant/project/mime/source/classification/retention（AD-9）；
- 字节全局去重（AD-14）：head 命中即同址返回；租户可达性由对象元数据
  标签承载（同 sha 跨租户各写一条元数据映射在 PG 侧——本 Store 只管
  字节与元数据，作用域判定走 artifact_scope）；
- 取回哈希校验（FR-011）：损坏检出 artifact.corrupted。
"""

from __future__ import annotations

import hashlib
from typing import Any

from vasta_protocols.errors import VastaError


class S3BlobStore:
    """S3 兼容工件后端（save/get 契约与 StorageAdapter 工件面一致）。"""

    def __init__(
        self,
        bucket: str,
        *,
        client: Any | None = None,
        prefix: str = "vasta/artifacts",
        endpoint_url: str | None = None,
        region: str | None = None,
    ) -> None:
        if client is None:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover——驱动门控
                raise VastaError(
                    code="s3.driver_missing",
                    message="S3BlobStore 需要 s3 可选 extra"
                            "（uv sync --extra s3 安装 boto3），或注入 client",
                ) from exc
            kwargs: dict[str, Any] = {}
            if endpoint_url:
                kwargs["endpoint_url"] = endpoint_url
            if region:
                kwargs["region_name"] = region
            client = boto3.client("s3", **kwargs)
        self._client = client
        self._bucket = bucket
        self._prefix = prefix.strip("/")

    def _key(self, sha: str) -> str:
        return f"{self._prefix}/{sha[:2]}/{sha}"

    @staticmethod
    def _is_not_found(exc: Exception) -> bool:
        """「对象确实不存在」判定——仅限明确的 404/NoSuchKey/KeyError
        （fake 形态）；其余（403/限流/5xx/凭证）一律视为存储故障。"""
        if isinstance(exc, KeyError):
            return True  # 内存 fake 的 not-found 形态
        if type(exc).__name__ == "ClientError":  # botocore（不硬依赖导入）
            text = str(exc).upper()
            return "404" in text or "NOSUCHKEY" in text
        return False

    async def save_artifact(
        self,
        payload: bytes,
        *,
        mime: str | None = None,
        source: str | None = None,
        classification: str | None = None,
        retention: str | None = None,
        tenant_id: str = "t-default",
        project_id: str = "p-default",
    ) -> str:
        sha = hashlib.sha256(payload).hexdigest()
        key = self._key(sha)
        # 字节全局去重（AD-14）：head 命中即同址（不重写字节）
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return sha
        except Exception as exc:  # noqa: BLE001
            if not self._is_not_found(exc):
                # 评审修复：head 瞬态/权限故障不再吞为「不存在」
                # （曾任何 head 异常都触发全量重传——写放大 + dedup 失效）
                raise VastaError(
                    code="s3.head_failed",
                    message=f"head {key} 失败（非 404——不重传，故障上抛）"
                            f"：{exc}",
                ) from exc
        metadata = {
            "tenant_id": tenant_id, "project_id": project_id,
            "sha256": sha,
        }
        for name, value in (("mime", mime), ("source", source),
                            ("classification", classification),
                            ("retention", retention)):
            if value:
                metadata[name] = str(value)
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=payload,
            ContentType=mime or "application/octet-stream",
            Metadata=metadata,
        )
        return sha

    async def get_artifact(
        self, sha256: str,
        *, tenant_id: str | None = None, project_id: str | None = None,
    ) -> bytes:
        try:
            response = self._client.get_object(
                Bucket=self._bucket, Key=self._key(sha256)
            )
        except Exception as exc:  # noqa: BLE001
            if self._is_not_found(exc):
                raise VastaError(
                    code="artifact.not_found",
                    message=f"artifact {sha256[:16]}… 不存在（{exc}）",
                ) from exc
            # 评审修复：瞬态错误（限流/5xx/凭证）不再误报 not_found
            # ——删除证明/审计语义不被网络抖动污染
            raise VastaError(
                code="s3.get_failed",
                message=(f"artifact {sha256[:16]}… 取回失败"
                         f"（非 404——存储故障，不代表已删除）：{exc}"),
            ) from exc
        payload = response["Body"].read()
        if hashlib.sha256(payload).hexdigest() != sha256:
            raise VastaError(
                code="artifact.corrupted",
                message=f"artifact {sha256[:16]}… 哈希校验失败（S3 对象损坏）",
            )
        return payload


__all__ = ["S3BlobStore"]
