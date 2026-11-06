"""CUA 原型配置：全部经环境变量覆盖（BYOK，密钥不落库不进日志）。

零侵入声明（同 examples/rag）：本目录是 examples 原型，只 import
packages/ 现有公共 API，不修改 packages/ 任何文件；运行数据不入库（源码在库）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class CuaConfig:
    # 模型端点（本地 LM Studio，OpenAI 兼容；rag 同款约定）
    base_url: str = _env("CUA_BASE_URL", "http://127.0.0.1:1234/v1")
    vlm_model: str = _env("CUA_VLM_MODEL", "qwen3.5-9b-mlx")
    api_key: str | None = os.environ.get("CUA_API_KEY") or None
    timeout_s: int = int(_env("CUA_TIMEOUT_S", "300"))
    # 思考型模型：reasoning 吃预算，回答保持短 JSON 但预算给足
    max_tokens: int = int(_env("CUA_MAX_TOKENS", "2000"))
    # qwen3.5 实测（2026-11）：chat_template_kwargs 压不住 thinking（空
    # content×finish=length，~2min/题）；prompt 尾缀 /no_think 立竿见影
    # （30s→11s）。默认开，CUA_NO_THINK=0 关闭。
    no_think: bool = _env("CUA_NO_THINK", "1") == "1"

    # 存储（独立 root，与平台示例 .vasta、rag 的 .vasta-rag 隔离）
    store_root: Path = Path(_env("CUA_STORE_ROOT", str(REPO_ROOT / ".vasta-cua")))
    tenant_id: str = "t-cua"
    project_id: str = "p-cua"

    # 安全边界（demo：默认只放行确定性强的自带应用）
    app_whitelist: tuple[str, ...] = tuple(
        s.strip() for s in _env("CUA_APP_WHITELIST", "Calculator,TextEdit").split(",")
        if s.strip()
    )
    # 白名单内应用的 R3 请求自动批准（demo 免交互；CUA_AUTO_APPROVE=""
    # 或 --require-approval 强制人工）
    auto_approve_apps: tuple[str, ...] = tuple(
        s.strip() for s in _env("CUA_AUTO_APPROVE",
                                "Calculator,TextEdit").split(",")
        if s.strip()
    )

    # SoM 标记
    max_marks: int = int(_env("CUA_MAX_MARKS", "80"))
    # AX 枚举限额（JXA 逐属性是 Apple event 往返，防爆量）
    ax_max_elements: int = int(_env("CUA_AX_MAX_ELEMENTS", "400"))
    ax_max_depth: int = int(_env("CUA_AX_MAX_DEPTH", "7"))
