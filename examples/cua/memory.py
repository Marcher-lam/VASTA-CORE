"""UI-布局记忆：把「按钮在哪」存成 Claim 图（vasta-cognition 公共 API）。

主张结构（事件溯源，历史不覆盖）：
- 父：``calc:layout:<sig>:vN`` —— 布局整体（display path + 元素数），
  memory_type=guide；
- 子：``calc:btn:<label>:<sig>:vN`` —— 各按钮 AX 路径，
  depends_on=[父]，scope={"app", "layout"}。

生命周期：标定成功 → propose(hypothesis)；任务全核验通过 → support
（+证据）→ accept；UI 改版活检查失败 → decay → refute（父先翻，
子由平台**依赖闭包级联失效**——refute() 自带传播）。
同布局重学 = 版本号 +1 的新主张（旧 refuted 留在图里，可审计）。
"""

from __future__ import annotations

import json
from typing import Any

from vasta_cognition import Claim, CognitionService

#: 活检查用的数字按钮（运算符判定贵，交由父主张级联覆盖）。
_SPOT_LABELS = tuple("0123456789")


def _next_version(cognition: CognitionService, prefix: str) -> int:
    """prefix 已有主张数 + 1（含终态——事件溯源永不重用 id）。"""
    return 1 + sum(1 for cid in cognition._claims if cid.startswith(prefix))


async def record_layout(
    cognition: CognitionService, app: str, sig: str,
    labels: dict[str, tuple[int, ...]],
    display_path: tuple[int, ...], element_count: int,
    *, evidence_run: str,
) -> tuple[str, list[str]]:
    """把一次成功标定写进 Claim 图。返回 (父 id, 子 id 列表)。"""
    parent_id = f"calc:layout:{sig}:v{_next_version(cognition, f'calc:layout:{sig}:')}"
    await cognition.propose(Claim(
        claim_id=parent_id, memory_type="guide",
        statement=json.dumps({"display_path": list(display_path),
                              "element_count": element_count},
                             ensure_ascii=False),
        scope={"app": app, "layout": sig},
        evidence=[f"run:{evidence_run}"], confidence=0.9,
        run_id=evidence_run,
    ))
    child_ids: list[str] = []
    base = f"calc:btn:"
    for label, path in sorted(labels.items()):
        cid = f"{base}{label}:{sig}:v{_next_version(cognition, f'{base}{label}:{sig}:')}"
        await cognition.propose(Claim(
            claim_id=cid, memory_type="guide",
            statement=json.dumps({"label": label, "path": list(path)},
                                 ensure_ascii=False),
            scope={"app": app, "layout": sig},
            depends_on=[parent_id],
            evidence=[f"run:{evidence_run}"], confidence=0.9,
            run_id=evidence_run,
        ))
        child_ids.append(cid)
    return parent_id, child_ids


def recall_layout(
    cognition: CognitionService, app: str, sig: str,
) -> tuple[str, dict[str, tuple[int, ...]], tuple[int, ...], int] | None:
    """按 (app, layout sig) 查活跃主张 → (父id, labels, display_path, 元素数)。

    只认 accepted/supported 状态（proposed 未经验证不提速）。"""
    cognition.refresh()
    scope_hit = {"app": app, "layout": sig}
    parents = [c for c in cognition._claims.values()  # noqa: SLF001
               if c.status in ("accepted", "supported")
               and set(scope_hit.items()) <= set(c.scope.items())
               and c.claim_id.startswith("calc:layout:")]
    if not parents:
        return None
    parent = max(parents, key=lambda c: c.version)
    try:
        pm = json.loads(parent.statement)
    except json.JSONDecodeError:
        return None
    labels: dict[str, tuple[int, ...]] = {}
    for c in cognition._claims.values():  # noqa: SLF001
        if (c.status in ("accepted", "supported")
                and parent.claim_id in c.depends_on
                and c.claim_id.startswith("calc:btn:")):
            try:
                m = json.loads(c.statement)
            except json.JSONDecodeError:
                continue
            labels[str(m["label"])] = tuple(m["path"])
    if len(labels) < 12:  # 键盘不全的布局记忆不可用（fail-safe）
        return None
    return parent.claim_id, labels, tuple(pm["display_path"]), \
        int(pm.get("element_count", 0))


async def refute_layout(
    cognition: CognitionService, parent_id: str,
    counterevidence: list[str],
) -> list[str]:
    """推翻父主张——子主张由平台级联失效。返回受影响清单。"""
    return await cognition.refute(parent_id, counterevidence)


def active_calc_claims(cognition: CognitionService, app: str) -> list[Any]:
    """app 域内全部活跃主张（impact_analysis 同口径的便捷读）。"""
    cognition.refresh()
    return [c for c in cognition._claims.values()  # noqa: SLF001
            if c.status not in ("refuted", "retired")
            and c.scope.get("app") == app]


__all__ = ["active_calc_claims", "recall_layout", "record_layout",
           "refute_layout"]
