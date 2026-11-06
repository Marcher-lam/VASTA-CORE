"""评测：四指标 + L1-only/L1+L2 消融 + LLM 裁判 + 报告落盘。

指标（前三个全自动客观）：
  recall@k       gold 源是否进入 L1 top-k（衡量粗筛层，独立于生成）
  citation_hit   引用的 doc_sha 是否命中 gold 源（双层范式核心主张）
  kw_coverage    答案含 gold 关键词比例（生成质量，客观版）
  judge          VLM 裁判 1-5 分（与生成同端点——自评偏差在报告标注）

所有模型调用经响应缓存 → 评测重跑零 API、结果逐字节可复现。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from vasta_storage import SqliteStorage

from .cloud import CloudClient
from .config import RagConfig
from .events import new_sequencer
from .index import RagIndex
from .query import answer_question

JUDGE_SYSTEM = "你是严格的评分裁判。只输出一个 1 到 5 的整数，不输出其他内容。"
JUDGE_PROMPT = (
    "问题：{q}\n参考要点（gold 关键词）：{kws}\n待评回答：{a}\n\n"
    "评分标准：5=准确完整且正确引用材料；4=基本准确有小瑕疵；3=部分正确；"
    "2=大量错误或未引用材料；1=错误/答非所问/编造。只输出整数。")

QA_PATH = Path(__file__).resolve().parent / "qa_set.json"


async def _judge(cloud: CloudClient, item: dict[str, Any], answer: str) -> int:
    prompt = JUDGE_PROMPT.format(q=item["question"],
                                 kws="、".join(item["gold_keywords"]),
                                 a=answer[:2000])
    resp = await cloud.generate(JUDGE_SYSTEM, prompt, max_tokens=800)
    m = re.search(r"[1-5]", resp["content"])
    return int(m.group(0)) if m else 0


def _metrics(result: dict[str, Any], gold_shas: set[str],
             keywords: list[str]) -> dict[str, Any]:
    cited = {c.get("doc_sha") for c in result.get("citations", [])}
    cited |= {c.get("root_doc_sha") for c in result.get("citations", [])}
    kw_hit = sum(1 for kw in keywords if kw in result.get("answer", ""))
    return {
        "recall_k": any(sha in set(result.get("top_doc_shas", []))
                        for sha in gold_shas),
        "citation_hit": bool(cited & gold_shas),
        "kw_coverage": round(kw_hit / len(keywords), 3) if keywords else 0.0,
        "images_used": result.get("images_used", 0),
        "parse_ok": result.get("citations_parse_ok", False),
        "verified_quotes": sum(1 for c in result.get("citations", [])
                               if c.get("verified")),
    }


async def run_eval(cfg: RagConfig, tiers: set[str] | None = None) -> dict[str, Any]:
    store = SqliteStorage(cfg.store_dir)
    cloud = CloudClient(cfg, store=store)
    index = await RagIndex.build(store, cfg)
    if not index:
        raise RuntimeError("索引为空：先运行 ingest")

    qa = json.loads(QA_PATH.read_text(encoding="utf-8"))["items"]
    if tiers:
        qa = [q for q in qa if q["tier"] in tiers]

    rows: list[dict[str, Any]] = []
    for item in qa:
        gold_shas = {index.doc_by_path[p] for p in item["gold_sources"]
                     if p in index.doc_by_path}
        row: dict[str, Any] = {"id": item["id"], "tier": item["tier"],
                               "gold_found": bool(gold_shas)}
        for mode in ("full", "l1only"):
            # 逐题容错：单题失败（模型循环/超时等）记零分继续，不炸整轮
            try:
                result = await answer_question(store, cfg, index, cloud,
                                               item["question"], mode=mode)
                m = _metrics(result, gold_shas, item["gold_keywords"])
                score = await _judge(cloud, item, result["answer"])
                row[mode] = {"metrics": m, "judge": score,
                             "answer": result["answer"],
                             "citations": result["citations"]}
            except Exception as exc:  # noqa: BLE001
                row[mode] = {"metrics": {"recall_k": False,
                                         "citation_hit": False,
                                         "kw_coverage": 0.0,
                                         "images_used": 0,
                                         "parse_ok": False,
                                         "verified_quotes": 0},
                             "judge": 0, "answer": "", "citations": [],
                             "error": str(exc)[:200]}
        rows.append(row)
        full = row["full"]
        l1 = row["l1only"]
        print(f"  {item['id']}({item['tier']}) "
              f"full: judge={full['judge']} cite={full['metrics']['citation_hit']} "
              f"| l1only: judge={l1['judge']} cite={l1['metrics']['citation_hit']}",
              flush=True)

    # ---- 聚合 ----
    def agg(mode: str) -> dict[str, float]:
        n = len(rows)
        return {
            "recall_k": sum(r[mode]["metrics"]["recall_k"] for r in rows) / n,
            "citation_hit": sum(r[mode]["metrics"]["citation_hit"] for r in rows) / n,
            "kw_coverage": sum(r[mode]["metrics"]["kw_coverage"] for r in rows) / n,
            "judge": sum(r[mode]["judge"] for r in rows) / n,
        }

    summary = {mode: agg(mode) for mode in ("full", "l1only")}
    by_tier = {}
    for tier in sorted({r["tier"] for r in rows}):
        sub = [r for r in rows if r["tier"] == tier]
        by_tier[tier] = {mode: {
            "judge": sum(r[mode]["judge"] for r in sub) / len(sub),
            "citation_hit": sum(r[mode]["metrics"]["citation_hit"] for r in sub) / len(sub),
        } for mode in ("full", "l1only")}

    report = _render_report(rows, summary, by_tier)
    report_rel = "reports/rag-eval-report.md"
    report_path = cfg.store_root / report_rel
    from asyncio import to_thread

    def _write() -> None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
    await to_thread(_write)

    payload = json.dumps({"summary": summary, "by_tier": by_tier, "rows": rows},
                         ensure_ascii=False, indent=2)
    rep_sha = await store.save_artifact(
        payload.encode("utf-8"), mime="application/json", source="rag.eval",
        tags={"rag_kind": "report"},
        tenant_id=cfg.tenant_id, project_id=cfg.project_id)
    seq = new_sequencer(store, "rag-eval", cfg)
    env = await seq.emit("run.created", {"questions": len(rows)})
    await seq.emit("run.completed", {"summary": summary, "report_sha256": rep_sha})

    print(report)
    print(f"\n报告：{report_path}\nJSON 工件：{rep_sha}")
    return {"summary": summary, "by_tier": by_tier, "report_path": str(report_path),
            "run_id": env.run_id}


def _render_report(rows: list[dict[str, Any]], summary: dict[str, Any],
                   by_tier: dict[str, Any]) -> str:
    lines = [
        "# RAG 原型评测报告",
        "",
        "消融：full = L1 粗筛 + L2 原始兜底（邻域扩展 + 原图直读）；"
        "l1only = 仅 L1（孤立 chunk 文本，无原图）。",
        "裁判与生成同端点（自评偏差已知）；judge 1-5。",
        "",
        "| 指标 | full | l1only | Δ(full−l1only) |",
        "|---|---|---|---|",
    ]
    for key in ("recall_k", "citation_hit", "kw_coverage", "judge"):
        f_v, l_v = summary["full"][key], summary["l1only"][key]
        lines.append(f"| {key} | {f_v:.3f} | {l_v:.3f} | {f_v - l_v:+.3f} |")
    lines += ["", "## 分层", "", "| 层 | 指标 | full | l1only |", "|---|---|---|---|"]
    for tier, modes in by_tier.items():
        for key in ("judge", "citation_hit"):
            lines.append(f"| {tier} | {key} | {modes['full'][key]:.3f} "
                         f"| {modes['l1only'][key]:.3f} |")
    lines += ["", "## 逐题", "",
              "| ID | 层 | gold定位 | full judge | full cite | full kw | "
              "l1 judge | l1 cite | l1 kw |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        fm, lm = r["full"]["metrics"], r["l1only"]["metrics"]
        lines.append(
            f"| {r['id']} | {r['tier']} | {'✓' if r['gold_found'] else '✗'} "
            f"| {r['full']['judge']} | {'✓' if fm['citation_hit'] else '✗'} "
            f"| {fm['kw_coverage']:.2f} | {r['l1only']['judge']} "
            f"| {'✓' if lm['citation_hit'] else '✗'} | {lm['kw_coverage']:.2f} |")
    return "\n".join(lines)
