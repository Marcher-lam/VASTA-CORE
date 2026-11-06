"""MinerU 文档解析集成（方案 B 的解析件）。

链路：PDF 原始字节（已在 CAS）→ POST /tasks（异步）→ 轮询 → md_content
→ figures 从服务落盘目录读取（output/<task_id>/<stem>/hybrid_auto/images/，
与 md 里 images/<sha>.jpg 引用精确对应——HTTP 响应本体不带图像字节）。

缓存：不做请求级缓存（ingest 侧按血缘查 mineru_md 已存在则整段跳过解析）。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .config import RagConfig

_IMG_REF = re.compile(r"!\[[^\]]*\]\(images/([^)\s]+)\)")


def _multipart(files: list[tuple[str, Path]], fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"----vastarag{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n"
            .encode())
    for _name, path in files:
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\";"
            f" filename=\"{path.name}\"\r\nContent-Type: application/pdf\r\n\r\n"
            .encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), boundary


def _request_json(method: str, url: str, body: bytes | None = None,
                  content_type: str | None = None, timeout: int = 120) -> dict:
    headers = {"Content-Type": content_type} if content_type else {}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def parse_pdf(cfg: RagConfig, pdf_path: Path
                    ) -> tuple[str, list[tuple[str, bytes]]]:
    """解析 PDF → (markdown, [(figure文件名, 字节), ...])。

    异步任务 + 落盘产物双通道：md 走 HTTP，figures 走 output 目录。
    """
    base = cfg.mineru_base_url.rstrip("/")
    stem = pdf_path.stem

    def _submit() -> str:
        body, boundary = _multipart([(pdf_path.name, pdf_path)],
                                    {"backend": "hybrid-engine", "return_md": "true"})
        resp = _request_json("POST", f"{base}/tasks", body,
                             f"multipart/form-data; boundary={boundary}", timeout=600)
        return resp["task_id"]

    task_id = await asyncio.to_thread(_submit)

    deadline = time.monotonic() + cfg.mineru_timeout_s
    while time.monotonic() < deadline:
        status = await asyncio.to_thread(
            _request_json, "GET", f"{base}/tasks/{task_id}")
        state = status.get("status")
        if state == "completed":
            break
        if state in ("failed", "error"):
            raise RuntimeError(f"MinerU 任务失败: {json.dumps(status, ensure_ascii=False)[:300]}")
        await asyncio.sleep(3.0)
    else:
        raise TimeoutError(f"MinerU 解析超时（>{cfg.mineru_timeout_s}s）: {pdf_path.name}")

    result = await asyncio.to_thread(
        _request_json, "GET", f"{base}/tasks/{task_id}/result")
    md = result["results"][stem]["md_content"]

    refs = _IMG_REF.findall(md)
    figures: list[tuple[str, bytes]] = []
    img_dir = cfg.mineru_output_dir / task_id / stem / "hybrid_auto" / "images"
    for name in refs:  # md 引用与服务落盘文件名精确一致
        f = img_dir / name
        if f.exists():
            figures.append((name, await asyncio.to_thread(f.read_bytes)))
    return md, figures


def strip_image_refs(md: str) -> tuple[str, list[str]]:
    """图像引用 → 短占位标记：'![](images/3799f….jpg)' → '[图: 3799f…]'。"""
    names: list[str] = []

    def _sub(m: re.Match[str]) -> str:
        name = m.group(1)
        names.append(name)
        return f"[图: {name[:8]}]"

    return _IMG_REF.sub(_sub, md), names
