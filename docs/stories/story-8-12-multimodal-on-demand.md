---
story_key: 8-12-multimodal-on-demand
baseline_commit: 2e1f051
---

# Story 8.12: 多模态按需派生（G5）

**Status:** review

## Story

As a 多模态 Agent 开发者,
I want 按需触发 OCR/ASR/摘要/embedding 与视频时间窗/音频对齐（不默认全量派生）,
So that 派生成本可控、需要才算。

## Acceptance Criteria

【GUI Pack 决议门槛：UX 契约与 GUI Pack 决议未定前不实施】
**Given** 证据引用（图像/音视频）
**When** 显式请求派生
**Then** 派生物带血缘可回链源时间轴/源 Artifact；按需触发留痕
**And** 不请求不派生（FR-015 + FR-016，Should）

> **门槛裁决（2026-09-10）**：用户指令跨 GUI Pack 决议门槛提前实施。
> 范围诚实口径：**按需派生框架 + 零依赖 deriver**（确定性摘要/哈希 embedding/
> 正则抽取/媒体清单窗口——真实 OCR/ASR/Embedding 模型随 GUI Pack 或真实
> 适配器接入，结构零变更）。

## Tasks/Subtasks

- [x] T1: `DeriverRegistry` + `derive_on_demand(store, source_sha, kind, params)`
      ——源存在 fail-fast（get_artifact）；未注册 kind fail-closed
      （derive.unregistered_kind）；派生经 save_derived（血缘+CAS 幂等，
      按需触发即留痕）；同 (source, kind, params) 幂等同址（实测血缘单条
      不重复登记）、异参数不误去重
- [x] T2: 零依赖 deriver 四件——`text_summary`（抽取式摘要前 N 句）、
      `text_embedding`（确定性哈希词袋向量，dim 可配，演示级如实标注 +
      近邻文本余弦相似度实测高于无关文本）、`text_extract`（正则状态
      抽取 fields={名: 正则}）、`media_window`（清单时间窗：相交即入窗、
      边界裁剪、**对齐键 align 原样保留**——音视频对齐可溯源）
- [x] T3: 不请求不派生守卫——保存源零派生（artifact 数仅 +1）；
      params 入血缘可原样回读
- [x] T4: 测试 `tests/test_on_demand_derive.py` 11 条（四 deriver 行为/
      幂等同址/异参不去重/零派生守卫/未注册拒/未知源拒/注册表扩展）；
      全量 493 passed +1 skipped；ruff 全绿；import-linter 2 契约 KEPT

## Dev Notes

- 位置：`packages/vastacore-sdk/src/vastacore/derive.py`（组装根）。
- 媒体窗与音频对齐用「媒体清单」形态（JSON 段落表）——不引入编解码依赖；
  真实媒体处理随 GUI Pack。
- embedding 为演示级确定性哈希向量——文档如实标注，不冒充语义模型。

## Dev Agent Record

### Debug Log

- 测试断言笔误：`b"\u3002"` 是 ASCII 转义串（6 字节）而非 UTF-8 句号——
  改 `"。".encode("utf-8")`。字节断言中文时直接 encode 而非字面量转义。

### Completion Notes

- 按需派生框架落地：显式请求才派生、血缘即留痕、幂等同址、异参不去重、
  双 fail 语义（源缺失 fail-fast / 类型未注册 fail-closed）。
- 四 deriver 全部零依赖且确定性（同输入同输出——embedding 近邻相似度
  实测 ordered）；真实 OCR/ASR/Embedding 模型注册即用，结构零变更。
- 媒体窗为多模态对齐的清单形态：segments 相交入窗、边界裁剪、align 键
  （audio: a-00x）保留——GUI Pack 真实媒体接入时清单由探测器生成。

### File List

- packages/vastacore-sdk/src/vastacore/derive.py（新增：derive_on_demand/
  DeriverRegistry/DerivedRef/四 deriver/default_registry）
- packages/vastacore-sdk/src/vastacore/__init__.py（导出）
- tests/test_on_demand_derive.py（新增：11 条）
- docs/sprint-status.yaml（8-12 状态）

## Change Log

- 2026-09-10: Story 8.12 实现完成（T1–T4 全过，493 passed +1 skipped，ruff/lint 绿）→ review
