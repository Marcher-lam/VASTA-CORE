---
story_key: va-2-read-pixels
baseline_commit: d37b4f2
---

# Story va.2: VISTA 吸收序②——read_pixels 视觉取证原语（R0）

**Status:** done

## Story

As a P6 点击失灵调查者,
I want 一个不依赖 AX 的像素级取证原语（区域中心采样 + 双帧 diff）,
So that 能区分「点击真没生效（屏没变）」与「AX 读数偏差（屏变了但
AX 没读到）」——三假设对照实验的独立观测通道。

## 来源

[吸收方案](../vista-absorption-plan-2026-11-16.md) §二 B——VISTA
`core/tools.py` / `core/session.py` 语义：区域均分 rows×cols、采样每格
**中心像素**（偏移 `(2c+1)*W//(2*C)`）、输出符号调色板 + 每采样行
紧凑字符串；「不对齐、不变换、不解释」。上限对齐：单次采样 ≤4096。

## Acceptance Criteria:

**Given** 任意 PNG 帧字节 + 像素坐标 region + rows×cols
**When** read_pixels 采样
**Then** 每格取中心像素（VISTA 偏移公式），输出 frozen PixelReadout
（rgb 行主序 / row_strings / palette 首见顺序分配——确定性）；越界、
非正网格、超 4096 采样 → ValueError（信息可行动）
**And** 同帧同参数多次调用全字段相等（重放兼容前提）
**And** diff_region 逐格对比：区域内变化检出 + 变化格计数、区域外
变化不检出、相同帧零变化
**And** 零 VLM 调用（纯本地 PIL）——取证成本为零

## Tasks/Subtasks

- [x] T1: `examples/cua/pixels.py`——Region/PixelReadout/RegionDiff
      （frozen）+ read_pixels（中心采样 + 紧凑读出）+ diff_region
- [x] T2: `as_event()` JSON 投影（审计链负载）
- [x] T3: 测试 ×12（tests/test_cua_read_pixels.py，合成 PNG 全确定性）：
      采样公式（全域/子域）、调色板与行串、单色坍缩、跨调用确定性、
      越界/超采样/非正网格、diff 三态（区内/区外/相同）、frozen 数据类

## 验证

- `uv run pytest tests/test_cua_read_pixels.py` → **12 passed**（红→绿）
- 与序①合计 21 passed；ruff 过（含 zip strict=）
- P6 管线组装零新码：事件流 → observation 工件 ref →
  `SqliteStorage.get_artifact` → `diff_region`（vlm.py 缓存已证此取件路径）

## 遗留（按计划属后续序号）

- SoM pt 坐标 ↔ 像素坐标映射标定 → 序③（模型侧接线时做）；
- `inspect`（裁剪 + 最近邻放大 + 多 view）与 history 模型侧投影 → 序③。
