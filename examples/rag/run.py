"""RAG 原型 CLI。

用法（repo 根目录，经 uv 带全工作区依赖）：
  uv run python -m examples.rag.run ingest            # 摄入语料（幂等，可增量重跑）
  uv run python -m examples.rag.run query "AD-14 说了什么"
  uv run python -m examples.rag.run query "..." --mode l1only
  uv run python -m examples.rag.run eval              # 全量评测 + 消融
  uv run python -m examples.rag.run eval --tiers I,X
"""

from __future__ import annotations

import argparse
import asyncio
import json

from vasta_storage import SqliteStorage

from .cloud import CloudClient
from .config import RagConfig
from .eval import run_eval
from .index import RagIndex
from .ingest import ingest
from .query import answer_question


async def cmd_ingest(args: argparse.Namespace) -> None:
    cfg = RagConfig.from_env()
    corpus = tuple(args.corpus.split(",")) if args.corpus else None
    summary = await ingest(cfg, corpus)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


async def cmd_query(args: argparse.Namespace) -> None:
    cfg = RagConfig.from_env()
    store = SqliteStorage(cfg.store_dir)
    index = await RagIndex.build(store, cfg)
    if not index:
        raise SystemExit("索引为空：先运行 ingest")
    result = await answer_question(store, cfg, index, CloudClient(cfg, store=store),
                                   args.question, mode=args.mode)
    print(f"\n〔{result['mode']}〕候选 {len(result['blocks'])} 个，"
          f"附图 {result['images_used']} 张\n")
    print(result["answer"])
    if result["citations"]:
        print("\n引用：")
        for c in result["citations"]:
            mark = "✓" if c["verified"] else "⚠未核验"
            print(f"  [{c['n']}] {mark} {c['path']} (sim={c['sim']}) "
                  f"「{c['quote'][:40]}」")
    else:
        print("\n（无引用 / 解析失败）")
    print(f"\n答案工件：{result['answer_sha256'][:16]}…  run：{result['run_id']}")


async def cmd_eval(args: argparse.Namespace) -> None:
    cfg = RagConfig.from_env()
    tiers = set(args.tiers.split(",")) if args.tiers else None
    await run_eval(cfg, tiers)


async def cmd_config(_args: argparse.Namespace) -> None:
    cfg = RagConfig.from_env()
    print(json.dumps(
        {k: str(v) for k, v in cfg.__dict__.items()}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="examples.rag")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="摄入语料（幂等）")
    p.add_argument("--corpus", help="逗号分隔的语料路径（覆盖默认）")
    p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("query", help="双层检索问答")
    p.add_argument("question")
    p.add_argument("--mode", choices=("full", "l1only"), default="full")
    p.set_defaults(fn=cmd_query)

    p = sub.add_parser("eval", help="评测 + 消融")
    p.add_argument("--tiers", help="逗号分隔的层过滤，如 T,I,X")
    p.set_defaults(fn=cmd_eval)

    p = sub.add_parser("config", help="打印生效配置")
    p.set_defaults(fn=cmd_config)

    args = parser.parse_args()
    asyncio.run(args.fn(args))


if __name__ == "__main__":
    main()
