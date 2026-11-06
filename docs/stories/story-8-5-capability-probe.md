---
story_key: 8-5-capability-probe
baseline_commit: c617750
---

# Story 8.5: 模型五维能力探测（G3）

**Status:** review

## Story

As a 平台使用者,
I want 系统自动探测模型的视觉/结构化输出/工具调用/上下文/流式能力,
So that 路由与提示策略按真实能力走，而不是我手工声明。

## Acceptance Criteria

**Given** 任一模型适配器
**When** 运行能力探测
**Then** 产出五维能力清单（含探测方法与置信度）作为 Artifact 落盘留痕
**And** 探测失败 fail-closed（按无该能力处理，不猜测）（FR-003；伙伴信号可调整）

## Tasks/Subtasks

- [x] T1: `probe_capabilities(adapter)`——五维行为探测（不信任自声明）：
      视觉（image-marker-echo 密标回显）/ 结构化输出（json-roundtrip 严格往返）/
      工具调用（tool-schema-emit）/ 流式（optional-generate_stream 可选方法分块，
      协议 v0.1 无流式面如实标注）/ 上下文（needle-short 短程针探 +
      声明窗口交叉记录）
- [x] T2: `ProbeOutcome`（detected/not_detected/probe_failed 三态 + 方法 + 置信度 +
      证据摘要）与 `CapabilityReport`（五维 + 声明交叉核对 + 差异清单 +
      `effective_capabilities()` 行为准视图）
- [x] T3: fail-closed——探测异常 → supported=False、置信度 0、probe_failed、
      证据含异常类型；声明与行为不一致 → 行为胜出且差异入报告
      （声明 True + 行为败 → fail-closed 降无能力；声明 False + 行为成 → 记低估）
- [x] T4: `save_capability_report(store, ...)`——报告 JSON 入 CAS（AD-3，
      source/classification=capability-probe），哈希可校验、schema 可往返
- [x] T5: 测试 `tests/test_capability_probe.py` 7 条——四类替身（全能力/盲/
      爆炸/声明不一致）+ 落盘取回哈希校验 + 往返 schema；全量 433 passed +1
      skipped；ruff 全绿；import-linter 2 契约 KEPT

## Dev Notes

- 位置：`packages/vastacore-sdk/src/vastacore/probe.py`（组装根；探测只依赖
  ModelAdapter 协议——AD-1）。
- 置信度：单次行为证据 detected=0.7；声明+行为一致提至 0.9；不一致/失败=0。
- 流式与长程窗口探测受协议 v0.1 面限制——方法名如实标注，不虚构精度。
- 真实适配器为 FR-003/006 实现载体（PRD 无独立编号，ASSUMPTION 已披露）。

## Dev Agent Record

### Debug Log

- 无重大坑；探测面完全落在既有 ModelAdapter 协议（generate + context dict），
  未动 protocols 包——行为探测无需协议变更（流式经可选方法探测，如实标注）。

### Completion Notes

- 五维探测全部行为化：密标回显/严格 JSON 往返/工具调用产出/流式分块/短程针探；
  每维带方法名与证据摘要，报告可整包 JSON 化入 CAS 留痕。
- fail-closed 三层验证：爆炸模型全维 probe_failed+置信度 0；说谎模型
  （自声明全能力行为全错）行为胜出 + 差异清单非空 + effective 视图推翻声明；
  盲模型（答了但错）not_detected 与 probe_failed 严格区分。
- 置信度语义：detected 0.7（单次行为证据）、声明+行为一致 0.9——不虚构更高精度。
- 伙伴信号可调整标注：探测方法集（needle-short / optional-generate_stream）
  待 Stage 2 真实适配器反馈后扩展。

### 增补（2026-11-06，W-1 视觉面闭环）

- vision 探测载荷从合成形态（伪 b64 尾缀——仅替身可答）升级为**真实渲染
  PNG**（5×7 点阵密标画入像素，`evidence.engines` 同源字形子集就地内嵌
  ——models/evidence 子包互独立不跨引）；替身改从 `context['marker']`
  模拟回显（context 不进 prompt，真实模型拿不到提示）。
- 真实验证：本地 `qwen3.8-27b-mlx`（LM Studio，OpenAI 兼容）经
  `OpenAICompatAdapter` 多模态接线（image_b64 → image_url data-URL）
  **从像素读出密标**——`test_real_vision_probe_detected` 门控测试
  PASSED（VASTA_REAL_ADAPTER 面）；自家 TemplateOcrEngine 对同一 PNG
  自证读出（render→OCR 闭环）。
- probe_capabilities docstring 的「合成形态」诚实边界注记同步更新。

### File List

- packages/vastacore-sdk/src/vastacore/probe.py（新增：probe_capabilities/
  CapabilityReport/ProbeOutcome/save_capability_report）
- packages/vastacore-sdk/src/vastacore/__init__.py（导出）
- tests/test_capability_probe.py（新增：7 条）
- docs/sprint-status.yaml（8-5 状态）

## Change Log

- 2026-09-09: Story 8.5 实现完成（T1–T5 全过，433 passed +1 skipped，ruff/lint 绿）→ review
