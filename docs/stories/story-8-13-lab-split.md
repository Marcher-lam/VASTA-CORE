---
story_key: 8-13-lab-split
baseline_commit: d883e26
---

# Story 8.13: lab.py 模块拆分（并行技术债，复盘 A5）

**Status:** review

## Story

As a 维护者,
I want lab.py（667 行十概念）拆分为 sandbox/models/planner/meta 模块,
So that Epic 8 各接入扩展不再挤单文件。

## Acceptance Criteria

**Given** 现有 vasta_model_lab 单文件实现
**When** 拆分模块
**Then** 公共 API 不变（`__all__` 兼容再导出）；388 测试全绿（拆解时点数；
现全量 493+）；import-linter 契约 KEPT
**And** 与 G1–G5 并行、不阻塞任何接入 Story（复盘 A5 行动项）

## Tasks/Subtasks

- [x] T1: 拆分为八模块——manifest（清单+协议+Observation_）/ dsl /
      python_model（含静态检查与白名单）/ sandbox（执行器+EventEmitter）/
      validation / meta / planner / bridge；`lab.py` 保留为门面
      （41 行，`__all__` 与符号再导出不变——包级与 `lab` 子模块双路径可用）
- [x] T2: 内容原样搬移（行为零变更）——全量 493 测试为安全网；无新增行为、
      无 bug 修复、无功能
- [x] T3: 验证——公共 API 面不变（下游消费者 import 全绿：test_model_lab
      32 测、versioning/timetravel/batch/probe 包内消费者、`from
      vasta_model_lab.lab import plan_bfs` 旧路径）；import-linter 2 契约
      KEPT；ruff 全绿
- [x] T4: 体量对比入 Completion Notes

## Dev Notes

- 纯结构重构：不修 bug、不改语义、不加功能——任何行为差异都是回归。
- `_static_check`/`ALLOWED_IMPORTS` 属 python_model；`EventEmitter` 属
  sandbox；跨模块依赖：validation→python_model、sandbox→python_model
  （静态检查前置）、python_model→sandbox 仅 TYPE_CHECKING 注解（运行时
  单向 sandbox→python_model，无环）。

## Dev Agent Record

### Debug Log

- 拆分脚本按行号锚点原样搬移——三处模块头部 import 缺失在测试与 ruff 下
  立即暴露（validation 缺 dataclass/VastaError、sandbox 缺 _static_check
  导入），逐个补齐——测试安全网有效性的一次实证。
- ruff --fix 曾把 TYPE_CHECKING 块当未用导入删除（注解在 `from __future__
  import annotations` 下运行时不可见）——重加后 F821/UP037 双规则互锁，
  以「TYPE_CHECKING 块 + 非引号注解」收敛（两规则同时满足的正确形态）。

### Completion Notes

- 体量对比：单文件 667 行 → 九文件最大 166 行（sandbox）、门面 41 行、
  八实现模块全部 <170 行——单文件多职责问题消除。
- 公共 API 零变更：`__all__` 18 项原样；`vasta_model_lab` 包级与
  `vasta_model_lab.lab` 双 import 路径均可用（下游零改动验证）。
- 依赖方向保持 AD-1：包内模块化不引入任何新跨包边；运行时包内依赖无环
  （sandbox→python_model 单向；python_model→sandbox 仅类型注解）。
- 复盘 A5 行动项闭合。

### File List

- packages/vasta-model-lab/src/vasta_model_lab/lab.py（重写为门面，41 行）
- packages/vasta-model-lab/src/vasta_model_lab/manifest.py（新增，52 行）
- packages/vasta-model-lab/src/vasta_model_lab/dsl.py（新增，61 行）
- packages/vasta-model-lab/src/vasta_model_lab/python_model.py（新增，128 行）
- packages/vasta-model-lab/src/vasta_model_lab/sandbox.py（新增，166 行）
- packages/vasta-model-lab/src/vasta_model_lab/validation.py（新增，101 行）
- packages/vasta-model-lab/src/vasta_model_lab/meta.py（新增，82 行）
- packages/vasta-model-lab/src/vasta_model_lab/planner.py（新增，70 行）
- packages/vasta-model-lab/src/vasta_model_lab/bridge.py（新增，35 行）
- docs/sprint-status.yaml（8-13 状态）

## Change Log

- 2026-09-10: Story 8.13 拆分完成（行为零变更，493 passed +1 skipped，ruff/lint 绿，API 面不变）→ review
