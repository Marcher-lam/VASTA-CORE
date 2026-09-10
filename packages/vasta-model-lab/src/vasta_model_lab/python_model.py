"""受限 Python 世界模型与静态检查（Story 6.1 + 4-7 评审修复）。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from vasta_protocols.errors import VastaError

from .manifest import WorldModelManifest

if TYPE_CHECKING:  # 注解专用（运行时 sandbox→python_model 单向依赖）
    from .sandbox import SandboxExecutor

#: 沙箱 Python 允许的导入白名单（生成代码侧）。
ALLOWED_IMPORTS = frozenset({"json", "math", "itertools", "collections"})


_FORBIDDEN_PATTERNS = [
    r"\bopen\s*\(",
    r"\b__import__\s*\(",
    r"\bexec\s*\(",
    r"\beval\s*\(",
    r"\bcompile\s*\(",
    r"\bgetattr\s*\(",
    r"\bsetattr\s*\(",
    r"\bvars\s*\(",
    r"\bglobals\s*\(",
    r"\blocals\s*\(",
    r"\bbreakpoint\s*\(",
    r"\binput\s*\(",
    r"\bos\.",
    r"\bsubprocess\.",
    r"\bsocket\.",
    r"\bshutil\.",
    r"\bsys\.",
    r"\bpathlib\.",
    r"\bctypes\.",
    r"\bimportlib\.",
]


def _static_check(code: str) -> None:
    """静态检查（FR-044）：导入白名单（含 from-import 形态）+ 危险模式禁用。"""
    for pattern in _FORBIDDEN_PATTERNS:
        if re.search(pattern, code):
            raise VastaError(
                code="model_lab.forbidden_pattern",
                message=f"生成代码含禁止模式 {pattern!r}（静态检查拒绝）",
            )
    for match in re.finditer(r"^\s*import\s+(\w+)", code, re.MULTILINE):
        module = match.group(1)
        if module not in ALLOWED_IMPORTS:
            raise VastaError(
                code="model_lab.forbidden_import",
                message=f"导入 {module!r} 不在白名单 {sorted(ALLOWED_IMPORTS)}",
            )
    # from-import 形态同样过白名单（评审修复：原正则漏检）
    for match in re.finditer(r"^\s*from\s+(\w+)", code, re.MULTILINE):
        module = match.group(1)
        if module not in ALLOWED_IMPORTS:
            raise VastaError(
                code="model_lab.forbidden_import",
                message=f"from-import {module!r} 不在白名单 {sorted(ALLOWED_IMPORTS)}",
            )





class PythonWorldModel:
    """受限 Python 世界模型（双执行模式，评审修复后语义与文档一致）：

    - ``sandbox=SandboxExecutor(...)``：每次 transition 经受限子进程
      （AD-6 主路径：静态检查 + 资源限额 + 最小环境 + 超时墙钟）；
    - ``sandbox=None``：受限 builtins 本地直跑（静态检查 + 无 IO/反射
      的内置集；用于快速验证与测试，不是生产边界）。"""

    def __init__(
        self,
        manifest: WorldModelManifest,
        code: str,
        *,
        timeout_s: float = 5.0,
        sandbox: SandboxExecutor | None = None,
    ) -> None:
        self.manifest = manifest
        self.code = code
        self.timeout_s = timeout_s
        self.sandbox = sandbox
        # 静态检查：导入白名单（含 from-import）+ 禁止危险调用
        _static_check(code)

    #: 受限 builtins——数值/容器/基础函数，无 IO/import 反射。
    _SAFE_BUILTINS: dict[str, Any] = {
        "abs": abs, "min": min, "max": max, "sum": sum, "len": len,
        "range": range, "enumerate": enumerate, "zip": zip, "sorted": sorted,
        "reversed": reversed, "any": any, "all": all, "map": map,
        "filter": filter, "round": round, "int": int, "float": float,
        "str": str, "bool": bool, "list": list, "dict": dict, "set": set,
        "tuple": tuple, "isinstance": isinstance, "print": lambda *_: None,
        "True": True, "False": False, "None": None,
    }

    def _run_local(self, payload: dict[str, Any]) -> Any:
        _static_check(self.code)
        scope: dict[str, Any] = {"state": payload["state"], "action": payload["action"]}
        # 显式置空 __builtins__：否则 exec 会向 globals 自动注入全量 builtins
        exec(self.code, {**self._SAFE_BUILTINS, "__builtins__": {}}, scope)  # noqa: S102
        return scope.get("result")

    def _execute(self, payload: dict[str, Any]) -> Any:
        if self.sandbox is not None:
            out = self.sandbox.run_sync(self.code, payload)
            return out.get("result") if isinstance(out, dict) else None
        return self._run_local(payload)

    def init_state(self, observation: dict[str, Any]) -> dict[str, Any]:
        return dict(observation.get("detail", {}))

    def transition(self, state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        result = self._execute({"state": state, "action": action})
        return result if isinstance(result, dict) else dict(state)

    def observe(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"kind": "decision", **{k: v for k, v in state.items() if not k.startswith("_")}}

    def outcome(self, state: dict[str, Any]) -> str:
        return state.get("_outcome", "ongoing")


