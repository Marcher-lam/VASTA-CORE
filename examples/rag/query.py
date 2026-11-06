"""双层检索 + 多模态生成 + 引用核验 + 事件留痕。

L1 粗筛：向量 top-k（可丢弃的摘要层——caption / chunk）
L2 兜底：邻域扩展原文 + 原图直读（VLM 看原始字节，防「摘要幻觉」）
留痕：答案落 CAS（source=rag.answer），查询经 observation.external 入事件流。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .cloud import CloudClient
from .config import RagConfig
from .events import new_sequencer
from .index import FIG_MARKER, RagIndex

SYSTEM = (
    "你是基于 VastaCore 项目文档的问答助手。只依据给出的材料回答问题；"
    "材料不足以回答时明确说「材料中没有足够信息」。"
    "引用材料时在句末用 [n] 标注编号。回答用中文，简洁准确。")

_MIME_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

_CITE_SPLIT = re.compile(r"CITATIONS\s*[:：]", re.IGNORECASE)


def _normalize(s: str) -> str:
    """quote 核验用的宽松归一：去空白与 markdown 标点（`*_:：等）。"""
    return re.sub(r"[^\w]", "", s, flags=re.UNICODE)


def _parse_citations(content: str) -> tuple[str, list[dict[str, Any]], bool]:
    """拆分答案与 CITATIONS JSON 块（容错解析）。"""
    parts = _CITE_SPLIT.split(content, maxsplit=1)
    if len(parts) != 2:
        return content.strip(), [], False
    answer, tail = parts[0].strip(), parts[1].strip()
    tail = tail.removeprefix("```json").removeprefix("```").removesuffix("```")
    lo, hi = tail.find("["), tail.rfind("]")
    if lo < 0 or hi <= lo:
        return answer, [], False
    try:
        cites = json.loads(tail[lo:hi + 1])
    except json.JSONDecodeError:
        return answer, [], False
    ok = isinstance(cites, list) and all(
        isinstance(c, dict) and isinstance(c.get("n"), int)
        and isinstance(c.get("quote"), str) for c in cites)
    return answer, cites if ok else [], ok


async def answer_question(store: Any, cfg: RagConfig, index: RagIndex,
                          cloud: CloudClient, question: str,
                          mode: str = "full") -> dict[str, Any]:
    if mode not in ("full", "l1only"):
        raise ValueError(f"未知模式：{mode}")
    qvec = (await cloud.embed([question]))[0]
    merge_window = 1 if mode == "full" else 0
    cands, ranked = index.search(qvec, cfg.top_k, cfg.min_sim,
                                 merge_window=merge_window)
    top_doc_shas = [e.doc_sha for e in ranked]

    # ---- 上下文装配（预算内；单块设上限防「巨块饿死小块」） ----
    blocks: list[dict[str, Any]] = []
    images: list[tuple[bytes, str]] = []
    attached: set[str] = set()  # 已附原图的 figure doc_sha（防候选/标记双通道重复）
    budget = cfg.char_budget
    per_block_cap = 2600

    async def _attach_figure(fig_doc_sha: str, mime: str) -> bool:
        if len(images) >= cfg.max_images or fig_doc_sha in attached:
            return False
        raw = await store.get_artifact(
            fig_doc_sha, tenant_id=cfg.tenant_id, project_id=cfg.project_id)
        images.append((raw, mime))
        attached.add(fig_doc_sha)
        return True

    for cand in cands:
        if budget <= 0:
            break
        ext = "." + cand.path.rsplit(".", 1)[-1] if "." in cand.path else ""
        if cand.kind == "image":
            if mode == "full" and await _attach_figure(
                    cand.doc_sha, _MIME_BY_EXT.get(ext, "image/png")):
                text = f"[图像 {cand.path}——原图已附给模型]\n内容描述：{cand.text}"
            else:
                text = f"[图像说明 {cand.path}——原图未附]\n{cand.text}"
            # 反向对齐：figure → 引用它的文字上下文（图的讨论段落/图注）
            if mode == "full" and cand.fig_prefix:
                ctx = index.context_chunks(cand.fig_prefix)
                if ctx:
                    text += f"\n〔图周边文字〕{ctx[0].text[:500]}"
        else:
            text = cand.text
            # 正向对齐：chunk 内占位标记 [图: xxxxxxxx] → 机械附上对应原图
            if mode == "full":
                for marker in list(FIG_MARKER.finditer(text)):
                    fig = index.resolve_figure(marker.group(1))
                    if fig is None:
                        continue
                    if await _attach_figure(fig.doc_sha, "image/jpeg"):
                        text = text.replace(
                            marker.group(0), f"{marker.group(0)}（原图已附）", 1)
        text = text[: min(budget, per_block_cap)]
        budget -= len(text)
        blocks.append({
            "n": len(blocks) + 1, "kind": cand.kind, "path": cand.path,
            "doc_sha": cand.doc_sha, "root_doc_sha": cand.root_doc_sha,
            "chunk_shas": cand.chunk_shas,
            "sim": round(cand.sim, 4), "text": text,
        })
    if not blocks:
        return {"question": question, "mode": mode, "answer": "检索无候选"
                "（min_sim 未命中），材料中没有足够信息。", "citations": [],
                "blocks": [], "top_doc_shas": top_doc_shas, "images_used": 0}

    material = "\n\n".join(f"[{b['n']}] {b['text']}" for b in blocks)
    prompt = (
        f"材料：\n{material}\n\n问题：{question}\n\n"
        "要求：1) 只用材料回答并标注 [n]；2) 回答完另起一行，以"
        " `CITATIONS:` 开头输出一个 JSON 数组，每项形如"
        ' {"n": 1, "quote": "支撑该结论的材料原文片段（40字内）"}，'
        "没有引用输出 []。")

    resp = await cloud.generate(SYSTEM, prompt,
                                images=images if mode == "full" else None)
    answer_text, raw_cites, parse_ok = _parse_citations(resp["content"])

    # ---- quote 回源核验（玩具级核验：包含性检查） ----
    material_norm = _normalize(material)
    block_by_n = {b["n"]: b for b in blocks}
    citations: list[dict[str, Any]] = []
    for c in raw_cites:
        block = block_by_n.get(c["n"])
        if block is None:
            continue  # 引用了不存在的编号：丢弃
        quote = c["quote"].strip()
        citations.append({
            "n": c["n"], "quote": quote,
            "verified": _normalize(quote) in material_norm,
            "path": block["path"], "doc_sha": block["doc_sha"],
            "root_doc_sha": block.get("root_doc_sha") or block["doc_sha"],
            "kind": block["kind"], "sim": block["sim"],
        })

    # ---- 留痕：答案入 CAS，查询入事件流 ----
    result_core = {"question": question, "mode": mode, "answer": answer_text,
                   "citations": citations, "model": resp.get("model")}
    ans_sha = await store.save_artifact(
        json.dumps(result_core, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        mime="application/json", source="rag.answer",
        tags={"rag_kind": "answer", "rag_mode": mode},
        tenant_id=cfg.tenant_id, project_id=cfg.project_id)
    qh = hashlib.sha256(question.encode("utf-8")).hexdigest()[:8]
    seq = new_sequencer(store, f"rag-query-{qh}", cfg)
    env = await seq.emit("run.created", {"question": question, "mode": mode})
    await seq.emit("observation.external", {
        "question": question, "mode": mode, "answer_sha256": ans_sha,
        "citations": [{k: c[k] for k in ("n", "path", "kind", "sim", "verified")}
                      for c in citations],
        "candidates": [{"path": b["path"], "kind": b["kind"], "sim": b["sim"]}
                       for b in blocks],
        "images_used": len(images), "citations_parse_ok": parse_ok})
    await seq.emit("run.completed", {"answer_chars": len(answer_text)})

    return {**result_core, "blocks": blocks, "top_doc_shas": top_doc_shas,
            "images_used": len(images), "citations_parse_ok": parse_ok,
            "answer_sha256": ans_sha, "run_id": env.run_id}
