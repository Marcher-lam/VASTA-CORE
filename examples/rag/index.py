"""向量索引：从派生链重建（零新表），纯 Python 余弦 + 窗口合并。

索引结构 = derived_assets 血缘两跳：
  rag_embedding --lineage--> chunk/caption --lineage--> doc
重建全部走现有公开 API（search_artifacts + lineage + get_artifact）。
nomic 向量已 L2 归一化 → 余弦退化为点积。

图文对齐（第 2 层「身份对齐」）：
  fig_by_prefix  占位标记 [图: xxxxxxxx] → 图像条目（caption params.figure）
  chunks_by_fig  figure 前缀 → 引用它的文本条目（运行时扫 chunk 文本标记）
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .config import RagConfig

FIG_MARKER = re.compile(r"\[图: ([0-9a-f]+)\]")


@dataclass
class Entry:
    vec: list[float]
    kind: str          # "text" | "image"
    chunk_sha: str     # chunk 或 caption 的 sha
    doc_sha: str       # 直接源（图像 caption 时 = figure/picture 工件 sha）
    root_doc_sha: str  # 根源文档（PDF figure → pdf sha；独立图像 → 自身）
    path: str
    index: int
    text: str
    fig_ref: str = ""  # PDF figure 名（MinerU 命名；caption params.figure）


@dataclass
class Candidate:
    kind: str
    path: str
    doc_sha: str
    root_doc_sha: str = ""
    fig_prefix: str = ""  # 图像候选的 figure 名前缀（占位标记可反查）
    chunk_shas: list[str] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)
    sim: float = 0.0
    text: str = ""


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class RagIndex:
    def __init__(self, entries: list[Entry]) -> None:
        self.entries = sorted(entries, key=lambda e: (e.path, e.index))
        self.by_path: dict[str, list[Entry]] = {}
        for e in self.entries:
            self.by_path.setdefault(e.path, []).append(e)
        # 路径 → 根源文档 sha（eval gold 匹配用；图像条目已解析到 root）
        self.doc_by_path: dict[str, str] = {
            p: next((e.root_doc_sha for e in es if e.kind == "text"), es[0].root_doc_sha)
            for p, es in self.by_path.items()}
        # 图文身份对齐：占位标记前缀 ↔ 图像条目；figure ↔ 引用它的文本条目
        self.fig_by_prefix: dict[str, Entry] = {
            e.fig_ref[:8]: e for e in self.entries
            if e.kind == "image" and e.fig_ref}
        self.chunks_by_fig: dict[str, list[Entry]] = {}
        for e in self.entries:
            if e.kind != "text":
                continue
            for m in FIG_MARKER.finditer(e.text):
                self.chunks_by_fig.setdefault(m.group(1)[:8], []).append(e)

    def resolve_figure(self, prefix: str) -> Entry | None:
        return self.fig_by_prefix.get(prefix[:8])

    def context_chunks(self, fig_prefix: str, limit: int = 2) -> list[Entry]:
        """引用某 figure 的文本条目（按 index 序）——给图像候选配文字上下文。"""
        chunks = self.chunks_by_fig.get(fig_prefix[:8], [])
        return sorted(chunks, key=lambda e: (e.path, e.index))[:limit]

    @classmethod
    async def build(cls, store: Any, cfg: RagConfig) -> RagIndex:
        rows = await store.search_artifacts(
            cfg.tenant_id, cfg.project_id, source="derived.rag_embedding")
        entries: list[Entry] = []
        for row in rows:
            emb_sha = str(row["sha256"])
            recs = await store.lineage(emb_sha, tenant_id=cfg.tenant_id,
                                       project_id=cfg.project_id)
            rec = next((r for r in recs if r.transform == "rag_embedding"), None)
            if rec is None or rec.transformer_version != cfg.embed_model:
                continue  # 只索引当前 embedding 模型代（防混维）
            parents = await store.lineage(rec.source_sha256, tenant_id=cfg.tenant_id,
                                          project_id=cfg.project_id)
            parent = parents[0] if parents else None
            if parent is None:
                continue
            try:
                text = (await store.get_artifact(
                    rec.source_sha256, tenant_id=cfg.tenant_id,
                    project_id=cfg.project_id)).decode("utf-8", errors="replace")
                vec_doc = json.loads((await store.get_artifact(
                    emb_sha, tenant_id=cfg.tenant_id,
                    project_id=cfg.project_id)).decode("utf-8"))
            except Exception:
                continue  # 工件不可达（理论不发生）：跳过保构建
            doc_sha = parent.source_sha256
            # 图像 caption 的直接源是 figure 工件；再上溯一层到根源文档（PDF）
            root_doc_sha = doc_sha
            if parent.transform == "rag_caption":
                grandparents = await store.lineage(
                    doc_sha, tenant_id=cfg.tenant_id, project_id=cfg.project_id)
                if grandparents:
                    root_doc_sha = grandparents[0].source_sha256
            entries.append(Entry(
                vec=vec_doc["vector"], kind="text" if parent.transform == "rag_chunk" else "image",
                chunk_sha=rec.source_sha256, doc_sha=doc_sha,
                root_doc_sha=root_doc_sha,
                path=str(parent.params.get("path", "?")),
                index=int(parent.params.get("index", 0)), text=text,
                fig_ref=str(parent.params.get("figure", ""))))
        return cls(entries)

    def __len__(self) -> int:
        return len(self.entries)

    def search(self, qvec: list[float], k: int, min_sim: float,
               merge_window: int = 1) -> tuple[list[Candidate], list[Entry]]:
        """返回 (合并后的候选列表, 合并前 top-k 条目——供 recall@k 用)。

        merge_window=1：文本候选并入同文档相邻 chunk（±1）——「原始兜底」
        的邻域扩展；merge_window=0：仅候选自身（L1-only 消融）。
        """
        scored = sorted(((_dot(e.vec, qvec), e) for e in self.entries),
                        key=lambda t: t[0], reverse=True)
        ranked = [e for sim, e in scored if sim >= min_sim][:k]

        picked: dict[str, list[Entry]] = {}
        for e in ranked:
            picked.setdefault(e.path, []).append(e)

        cands: list[Candidate] = []
        for path, group in picked.items():
            group.sort(key=lambda e: e.index)
            if group[0].kind == "image" or merge_window == 0:
                for e in group:  # 图像不合并；window=0 逐条
                    cands.append(Candidate(
                        kind=e.kind, path=path, doc_sha=e.doc_sha,
                        root_doc_sha=e.root_doc_sha, fig_prefix=e.fig_ref[:8],
                        chunk_shas=[e.chunk_sha], indices=[e.index],
                        sim=next(s for s, x in scored if x is e), text=e.text))
                continue
            # 文本：按「连续 index 段」切组（防止不相邻 chunk 把整篇文档拉进窗口）
            # 再各段邻域扩展 ±merge_window —— 每段独立成候选
            runs: list[list[Entry]] = [[group[0]]]
            for prev, cur in zip(group, group[1:], strict=False):
                if cur.index - prev.index <= merge_window + 1:
                    runs[-1].append(cur)
                else:
                    runs.append([cur])
            for run in runs:
                lo, hi = run[0].index - merge_window, run[-1].index + merge_window
                window = [e for e in self.by_path[path] if lo <= e.index <= hi]
                window.sort(key=lambda e: e.index)
                cands.append(Candidate(
                    kind="text", path=path, doc_sha=run[0].doc_sha,
                    root_doc_sha=run[0].root_doc_sha,
                    chunk_shas=[e.chunk_sha for e in window],
                    indices=[e.index for e in window],
                    sim=max(next(s for s, x in scored if x is e) for e in run),
                    text="\n\n…\n\n".join(e.text for e in window)))
        cands.sort(key=lambda c: c.sim, reverse=True)
        return cands, ranked
