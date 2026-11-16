---
story_key: va-1-error-as-observation
baseline_commit: eea0301
---

# Story va.1: VISTA 吸收序①——错误即观测（VLM 坏 JSON 回喂）

**Status:** done

## Story

As a CUA 评测消费者,
I want VLM 坏 JSON 时把错误与原文作为「系统观测」回喂下一轮 prompt，而不是盲重试到耗尽,
So that 单次格式错误不再注定任务失败（消除 Phase 4 基线次因「VLM 坏 JSON 重试耗尽」）。

## 来源

[吸收方案](../vista-absorption-plan-2026-11-16.md) §三 C——VISTA
`core/session.py` 模式：`{"ok": False, "error": …}` 回喂而非抛完即弃。

## 根因（比基线报告深一层的机制）

loop 盲重试（prompt 不变）× vlm 响应缓存（成功即落盘，同 body 同
key）→ 二次请求命中缓存取回**同一份坏文本** → 必然二连炸。观测注入
使 prompt 变化 → 缓存 key 变化 → 真重采样。

## Acceptance Criteria:

**Given** VLM 返回不含 JSON 或坏 JSON 的文本
**When** ask_json 解析失败
**Then** 抛 `VlmFormatError`（携带 `raw` 原文），loop 构造观测（错误
原因 + 原文 ≤160 字符截断 + 修正指令）注入下一轮 prompt（vision /
memory 两模式）
**And** 无错误时 prompt 不渲染观测段；既有 `RuntimeError` 消费者
（probe_grounding 等）零破坏——子类兼容
**And** 重试预算仍 2 次（有界恢复不变）

## Tasks/Subtasks

- [x] T1: `VlmFormatError`（raw 随行）+ ask_json 两处格式错误改抛
      类型化异常（消息不再内嵌原文，原文走 `.raw`）
- [x] T2: `loop._vlm_error_note` 构造回喂观测；`_vision_prompt` /
      `_memory_prompt` 增 `vlm_error` 参数渲染「系统观测」段
- [x] T3: run_agent 接线——except 分层（`VlmFormatError` 先于
      `RuntimeError`）、`vlm_feedback` 生命周期（错误置位 / 成功重置）
- [x] T4: 测试 ×9（tests/test_cua_vlm_error_observation.py）：无
      JSON / 坏 JSON 抛类型化错误携 raw、好 JSON 不受影响、观测构造
      含原因 + 截断 + 标记、两模式注入 / 无错干净

## 验证

- `uv run pytest tests/test_cua_vlm_error_observation.py` → **9 passed**
- `uv run ruff check`（vlm / loop / test）→ All checks passed
- 导入冒烟（loop + eval）→ OK；probe_grounding 兼容性核验（RuntimeError
  子类，`str(exc)` 照常）
- 集成验证（真机 / VM 多种子基线对比）→ ⚠️ 待下一轮 VM 评测窗口
  （与 P6 对照实验同批跑，验收信号见吸收方案 §七 序①）

## 遗留

- 空 content 路径（内部 3× max_tokens 重试后仍空）维持原 RuntimeError
  分支——无原文可喂，观测无意义；
- 集成数字（坏 JSON 失败模式在基线中的占比变化）待 VM 重跑后回填。
