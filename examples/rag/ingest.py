"""摄入管道：原始字节无损入 CAS → 确定性切块 / VLM caption → 云 embedding。

派生链（血缘即索引结构，见 index.py）：
  文本: doc --rag_chunk--> chunk --rag_embedding--> 向量
  图像: doc --rag_caption--> caption --rag_embedding--> 向量

幂等语义（继承 save_derived）：同 (载荷, 源, transform, params) 重跑直接跳过；
语料布局变化（chunk 序号漂移）会产生 lineage.conflict——按「已摄入过」跳过，
旧序号继续生效；要彻底重来就换 RAG_STORE_ROOT。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage

from .cloud import CloudClient
from .config import RagConfig, iter_corpus
from .events import new_sequencer
from .figparse import parse_pdf, strip_image_refs

_MIME = {".md": "text/markdown", ".markdown": "text/markdown", ".txt": "text/plain",
         ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".pdf": "application/pdf"}

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

CAPTION_SYSTEM = "你是客观的图像描述员，只描述图中可见内容。"
CAPTION_PROMPT = (
    "用不超过三句话客观描述这张架构图：包含哪些方框/角色、箭头方向、"
    "以及箭头上标注的文字。不要推测图中不存在的内容。")


@dataclass
class Chunk:
    text: str
    heading: str


def chunk_markdown(text: str, path: str, max_chars: int) -> list[Chunk]:
    """确定性切块：按标题分节、按空行分段、贪心打包；超长段落硬切。

    每个 chunk 自带面包屑前缀 [path › 标题路径]——自描述且利于 embedding。
    """
    stack: list[str] = []
    buf: list[str] = []
    flat: list[tuple[str, str]] = []  # (heading_path, paragraph)

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            flat.append((" › ".join(s for s in stack if s), body))
        buf.clear()

    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            flush()
            level, title = len(m.group(1)), m.group(2).strip()
            stack[:] = stack[: level - 1]
            stack.append(title)
        elif line.strip() == "":
            flush()
        else:
            buf.append(line.rstrip())
    flush()

    chunks: list[Chunk] = []
    for heading, para in flat:
        breadcrumb = f"[{path}{' › ' + heading if heading else ''}]"
        while len(para) > max_chars:  # 超长段落硬切（长文可能无空行）
            chunks.append(Chunk(text=f"{breadcrumb}\n\n{para[:max_chars]}",
                                heading=heading))
            para = para[max_chars:]
        chunks.append(Chunk(text=f"{breadcrumb}\n\n{para}", heading=heading))
    return chunks


async def _existing_pdf_parse(store: SqliteStorage, cfg: RagConfig, rel: str,
                              pdf_sha: str) -> tuple[str | None, list[tuple[str, bytes]]]:
    """血缘驱动的解析缓存：pdf 已有 mineru_md 派生 → 直接读回 md 与 figures。"""
    hits = await store.search_by_entity(
        "rag_doc", rel, tenant_id=cfg.tenant_id, project_id=cfg.project_id,
        include_derived=True)
    md_text: str | None = None
    figures: list[tuple[str, bytes]] = []
    for hit in hits:
        if hit.get("kind") != "derived":
            continue
        recs = await store.lineage(str(hit["ref"]), tenant_id=cfg.tenant_id,
                                   project_id=cfg.project_id)
        rec = recs[0] if recs else None
        if rec is None or rec.source_sha256 != pdf_sha:
            continue
        if rec.transform == "mineru_md":
            raw = await store.get_artifact(str(hit["ref"]), tenant_id=cfg.tenant_id,
                                           project_id=cfg.project_id)
            md_text = raw.decode("utf-8", errors="replace")
        elif rec.transform == "mineru_figure":
            raw = await store.get_artifact(str(hit["ref"]), tenant_id=cfg.tenant_id,
                                           project_id=cfg.project_id)
            figures.append((str(rec.params.get("figure", "?")), raw))
    return md_text, figures


async def _ingest_pdf(store: SqliteStorage, cfg: RagConfig, cloud: CloudClient,
                      seq: Any, sha: str, rel: str, abspath: Path,
                      to_embed: list[tuple[str, str]],
                      counts: dict[str, int]) -> None:
    """PDF：MinerU 解析 → md/figures 各自成派生 → figure 走 caption 链 → md 切块。

    血缘四层：pdf → mineru_figure → rag_caption → rag_embedding
             pdf → mineru_md → rag_chunk → rag_embedding
    """
    md, figures = await _existing_pdf_parse(store, cfg, rel, sha)
    if md is None:
        md, figures = await parse_pdf(cfg, abspath)
        await _save_derived_quiet(
            store, md.encode("utf-8"), source_sha256=sha, transform="mineru_md",
            params={"path": rel, "backend": "hybrid-engine"},
            transformer_version="mineru/3.4.4", cfg=cfg, mime="text/markdown")
    await seq.emit("artifact.registered",
                   {"sha256": sha, "path": rel, "kind": "pdf",
                    "figures": len(figures), "md_chars": len(md)})
    counts["pdf_figs"] = counts.get("pdf_figs", 0) + len(figures)

    for name, fig_bytes in figures:
        fig_sha = hashlib.sha256(fig_bytes).hexdigest()  # 内容寻址：冲突跳过也可链
        await _save_derived_quiet(
            store, fig_bytes, source_sha256=sha, transform="mineru_figure",
            params={"path": rel, "figure": name}, transformer_version="mineru/3.4.4",
            cfg=cfg, mime="image/jpeg")
        resp = await cloud.generate(
            CAPTION_SYSTEM, CAPTION_PROMPT, images=[(fig_bytes, "image/jpeg")],
            max_tokens=1500)
        caption = resp["content"]
        cap_sha = hashlib.sha256(caption.encode("utf-8")).hexdigest()
        await _save_derived_quiet(
            store, caption.encode("utf-8"), source_sha256=fig_sha,
            transform="rag_caption", params={"path": rel, "figure": name[:24]},
            transformer_version=cfg.vlm_model, cfg=cfg)
        counts["captions"] += 1
        to_embed.append((cap_sha, caption))

    md_text, _names = strip_image_refs(md)
    chunks = chunk_markdown(md_text, rel, cfg.chunk_chars)
    for i, chunk in enumerate(chunks):
        csha = await _save_derived_quiet(
            store, chunk.text.encode("utf-8"), source_sha256=sha,
            transform="rag_chunk",
            params={"path": rel, "index": i, "total": len(chunks),
                    "heading": chunk.heading},
            transformer_version=cfg.version, cfg=cfg)
        if csha is None:
            continue
        counts["chunks"] += 1
        to_embed.append((csha, chunk.text))


async def _save_derived_quiet(store: SqliteStorage, payload: bytes, *,
                              source_sha256: str, transform: str,
                              params: dict[str, Any], transformer_version: str,
                              cfg: RagConfig, mime: str | None = "text/plain"
                              ) -> str | None:
    """save_derived 包装：lineage.conflict（布局漂移的重复登记）静默跳过。"""
    try:
        return await store.save_derived(
            payload, source_sha256=source_sha256, transform=transform,
            params=params, transformer_version=transformer_version, mime=mime,
            tenant_id=cfg.tenant_id, project_id=cfg.project_id)
    except VastaError as exc:
        if getattr(exc, "code", "") == "lineage.conflict":
            return None
        raise


async def ingest(cfg: RagConfig,
                 corpus: tuple[str, ...] | None = None) -> dict[str, Any]:
    store = SqliteStorage(cfg.store_dir)
    cloud = CloudClient(cfg, store=store)
    files = iter_corpus(corpus or cfg.corpus)
    if not files:
        raise RuntimeError("语料为空：检查 corpus 路径")

    manifest = hashlib.sha256(
        "\n".join(rel for rel, _, _ in files).encode("utf-8")).hexdigest()[:8]
    seq = new_sequencer(store, f"rag-ingest-{manifest}", cfg)
    env = await seq.emit("run.created",
                         {"corpus_files": len(files), "version": cfg.version})
    run_id = env.run_id

    to_embed: list[tuple[str, str]] = []  # (chunk/caption sha, 待嵌入文本)
    counts = {"docs": 0, "text_docs": 0, "image_docs": 0, "pdf_docs": 0,
              "chunks": 0, "captions": 0, "embeddings": 0}

    for rel, abspath, kind in files:
        payload = await asyncio.to_thread(abspath.read_bytes)
        mime = _MIME.get(abspath.suffix.lower())
        sha = await store.save_artifact(
            payload, mime=mime, source="rag.corpus",
            tags={"rag_kind": "image" if kind == "image" else "doc"},
            entities={"rag_doc": rel},
            tenant_id=cfg.tenant_id, project_id=cfg.project_id)
        await seq.emit("artifact.registered",
                       {"sha256": sha, "path": rel, "kind": kind})
        counts["docs"] += 1

        if kind == "pdf":
            counts["pdf_docs"] = counts.get("pdf_docs", 0) + 1
            await _ingest_pdf(store, cfg, cloud, seq, sha, rel, abspath,
                              to_embed, counts)
        elif kind == "text":
            counts["text_docs"] += 1
            text = payload.decode("utf-8", errors="replace")
            chunks = chunk_markdown(text, rel, cfg.chunk_chars)
            for i, chunk in enumerate(chunks):
                csha = await _save_derived_quiet(
                    store, chunk.text.encode("utf-8"), source_sha256=sha,
                    transform="rag_chunk",
                    params={"path": rel, "index": i, "total": len(chunks),
                            "heading": chunk.heading},
                    transformer_version=cfg.version, cfg=cfg)
                if csha is None:
                    continue  # 布局漂移：旧登记继续生效
                counts["chunks"] += 1
                to_embed.append((csha, chunk.text))
        else:
            counts["image_docs"] += 1
            resp = await cloud.generate(
                CAPTION_SYSTEM, CAPTION_PROMPT,
                images=[(payload, mime or "image/png")], max_tokens=1500)
            cap_sha = await _save_derived_quiet(
                store, resp["content"].encode("utf-8"), source_sha256=sha,
                transform="rag_caption", params={"path": rel},
                transformer_version=cfg.vlm_model, cfg=cfg)
            if cap_sha is None:
                continue
            counts["captions"] += 1
            to_embed.append((cap_sha, resp["content"]))

    # 批量 embedding（nomic 768 维、已归一化）
    texts = [t for _, t in to_embed]
    for start in range(0, len(texts), 16):
        batch = texts[start:start + 16]
        vectors = await cloud.embed(batch)
        for (src_sha, _), vec in zip(to_embed[start:start + 16], vectors,
                                     strict=True):
            payload = json.dumps(
                {"vector": vec, "dim": len(vec), "method": cfg.embed_model},
                ensure_ascii=False, sort_keys=True).encode("utf-8")
            esha = await _save_derived_quiet(
                store, payload, source_sha256=src_sha,
                transform="rag_embedding",
                params={"model": cfg.embed_model, "dim": len(vec)},
                transformer_version=cfg.embed_model, cfg=cfg,
                mime="application/json")
            if esha is not None:
                counts["embeddings"] += 1

    await seq.emit("run.completed", counts)
    return {"run_id": run_id, **counts}
