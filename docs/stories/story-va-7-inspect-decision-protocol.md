---
story_key: va-7-inspect-decision-protocol
baseline_commit: e7bad92
---

# Story va.7: 边界清偿③——inspect 请求进决策协议（va-3 遗留收口）

**Status:** done

## Story

As a CUA 模型侧循环,
I want 决策 JSON 可选 inspect 字段——不确定时只发回看请求不发动作,
So that 模型能主动复查视觉证据（VISTA inspect 语义在自有循环落地，
不再"待真实需求场景"）。

## 来源

[吸收方案](../vista-absorption-plan-2026-11-16.md) §二 B +
上一轮终审诚实边界③。区域按 **mark 编号**指定（模型既有词汇），
pt×scale 经 va-3 的 Region.from_pt；crop_view 最近邻放大。

## Acceptance Criteria:

**Given** 决策 JSON 含 inspect（≤2 项，mark 词汇）
**When** button 缺失或不可用且 vision 模式
**Then** 循环裁剪当前场景对应 mark 区域（NEAREST 放大）作为附加图
像回喂下一轮 + 提示注记；连续回看 ≤3 次（防无限放大循环，超限转
闸拒反馈）；未知编号/坏条目错误即观测回喂（坏条目跳过好条目保留）
**And** memory 模式无标记表 → 明确反馈不支持

## Tasks/Subtasks

- [x] T1: `_parse_inspect`（mark→Region，≤2；空表/未知编号反馈）
- [x] T2: `_inspect_prompt_note`（附图标签注记）
- [x] T3: run_agent 接线——附图并入 vlm images、streak 闸、动作执行
      清零；SYSTEM_PROMPT 协议文档化
- [x] T4: 测试 ×8（tests/test_cua_inspect_protocol.py）

## 验证

- 8 测试红转绿；全量 1389 passed / 7 skipped（当轮）；ruff 过
- 真机 run #2/#3 中模型未主动使用 inspect（27b 倾向试错）——机制
  在场由闸路径与单测背书；真实使用率待 VM 评测窗口统计

## 遗留

- inspect 使用率与效果（减少误点？）→ VM 多种子评测统计项
