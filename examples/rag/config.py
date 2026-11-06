"""RAG 原型配置：全部经环境变量覆盖（BYOK，密钥不落库不进日志）。

零侵入声明：本目录是 examples 原型，只 import 现有公共 API，
不修改 packages/ 任何文件；运行数据不入库（源码在库）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_TEXT_EXTS = {".md", ".markdown", ".txt"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
_PDF_EXTS = {".pdf"}


@dataclass(frozen=True)
class RagConfig:
    # 模型端点（本地 LM Studio，OpenAI 兼容；embedding 与 VLM 同服务双模型）
    base_url: str = "http://127.0.0.1:1234/v1"
    embed_model: str = "text-embedding-qwen3-embedding-0.6b"
    # 27b：稳定可靠（思考行为正常，长材料不退化）；干净内存下 ~13 tok/s。
    # 9b 实测在长中文材料上思考必然退化（2200+6600 token 全耗尽仍无 content，
    # 四种禁思考姿势均无效）——只适合短 prompt（caption 可用）。
    vlm_model: str = "qwen3.8-27b-mlx"
    api_key: str | None = None
    timeout_s: int = 300

    # 方案 B：MinerU 文档解析服务（PDF → md + figures）
    mineru_base_url: str = "http://127.0.0.1:18000"
    mineru_output_dir: Path = Path.home() / "Desktop/mineru-service/output"
    mineru_timeout_s: int = 900

    # 存储（独立 root，与平台示例的 .vasta 隔离）
    store_root: Path = REPO_ROOT / ".vasta-rag"
    tenant_id: str = "t-default"
    project_id: str = "p-default"

    # 检索 / 生成参数
    top_k: int = 10
    min_sim: float = 0.25
    char_budget: int = 12000
    max_images: int = 4
    # 思考型模型：reasoning_content 吃预算，max_tokens 必须给足
    max_tokens: int = 2500

    # 摄入参数
    chunk_chars: int = 800
    corpus: tuple[str, ...] = (
        "README.md",
        "docs/quickstart.md",
        "docs/architecture/architecture-VastaCore-2026-09-08/ARCHITECTURE-SPINE.md",
        "docs/prds/prd-VastaCore-2026-09-08/prd.md",
        "plan.md",
        "VASTA-BRAINSTORM.md",
        "examples/rag/corpus/",  # 合成架构图（见 make_figures.py，README 有诚实标注）
    )

    version: str = "rag-proto/0.1"

    @classmethod
    def from_env(cls) -> RagConfig:
        env = os.environ
        return cls(
            base_url=env.get("RAG_BASE_URL", cls.base_url),
            embed_model=env.get("RAG_EMBED_MODEL", cls.embed_model),
            vlm_model=env.get("RAG_VLM_MODEL", cls.vlm_model),
            api_key=env.get("RAG_API_KEY") or None,
            mineru_base_url=env.get("RAG_MINERU_URL", cls.mineru_base_url),
            mineru_output_dir=Path(env.get("RAG_MINERU_OUTPUT",
                                           str(cls.mineru_output_dir))),
            store_root=Path(env.get("RAG_STORE_ROOT", cls.store_root)),
            top_k=int(env.get("RAG_TOP_K", cls.top_k)),
            min_sim=float(env.get("RAG_MIN_SIM", cls.min_sim)),
        )

    @property
    def store_dir(self) -> Path:
        return self.store_root / "store"


def iter_corpus(corpus: tuple[str, ...], root: Path = REPO_ROOT) -> list[tuple[str, Path, str]]:
    """展开语料路径 → [(相对路径, 绝对路径, kind)]，确定性排序。

    kind ∈ {"text", "image"}；无法识别的扩展名跳过。
    """
    out: list[tuple[str, Path, str]] = []
    for item in corpus:
        p = (root / item).resolve()
        if p.is_file():
            files = [p]
        elif p.is_dir():
            files = sorted(q for q in p.rglob("*") if q.is_file())
        else:
            continue
        for f in files:
            ext = f.suffix.lower()
            if ext in _TEXT_EXTS:
                kind = "text"
            elif ext in _IMAGE_EXTS:
                kind = "image"
            elif ext in _PDF_EXTS:
                kind = "pdf"
            else:
                continue
            rel = f.relative_to(root).as_posix()
            out.append((rel, f, kind))
    return sorted(out)
