---
story_key: va-8-integration-findings
baseline_commit: 0528b82
---

# Story va.8: 边界清偿①②④——真机集成两轮：三个真 bug 与 P6 根因

**Status:** done

## Story

As a 吸收机制的集成验证,
I want 真机长任务跑通吸收机制并清偿遗留登记,
So that 「集成数字待 VM 窗口」边界清偿 + P6 调查获得根因与修复。

## 集成环境

主机直连（本会话 VM 停机，主机=CUA 出生地）：Calculator + AX +
LM Studio `qwen3.8-27b-mlx`（W-1 十种子全对同款）+ temp 0.3。
驱动：`examples/cua/va_integration.py`（跑任务 + 事件流离线取证：
检查点/偏差率/P6 表；`--run-id` 支持对已落库 run 复检）。

## run #1（17 步长任务）→ 三个发现

1. **闸拒活锁**（新 bug）：闸拒反馈不变 × 响应缓存 → 0.7s/次同答案
   死循环（va-1 修了格式错误的同族根因，闸反馈漏了）；
2. **陈旧部分标定**：11/6 W-1 时代缓存仅 13/14 键（缺 0/=/AC）→
   任务不可解 + 恢复指令引导模型按 AC → 活锁放大。清缓存重标（17 键）；
3. 驱动 scope bug：result_ref 工件在事件自身作用域（engine 默认
   t-default），按 cfg(t-cua) 取被 AD-14 拒——按事件信封作用域取件。

## run #2（修复后 17 步，2063s）→ 机制实拍 + P6 根因

**机制在场**：`[ckpt] s8→67911fe7 / s16→68c8e8f1` 双检查点 CAS 落盘
（离线取证往返：边界 8/16 各含全量历史 8/16 条）；闸拒带次数+候选
清单（`可用按钮：%、+、0…`）每次真重采样（311s/163s，活锁根除）；
AC/⌫ 振荡被 Supervisor 熔断收场；坏 JSON 0 次（27b 格式稳——机制
备用，占比 0→0）。

**P6 根因（证据链）**：`replayed=True ×13 连`（seq31-86）——
`plan_step_id` 缺省 `"default"` → 同 run 同 mark 共享幂等键 →
核验失败后的重试被 AD-11 **重放原结果而非真执行**。「executed 而
屏值不变」、AX 读数漂移（重放 ToolResult 携首次旧值）、失败率随
任务位次递增（后期重复键概率高）、Phase 4 主力失败模式——全部
同源。CAS sha 同一性成为完美屏差判据（run #2 两态交替铁证）。

**附带证据**：主机侧 AX 表达式行/结果行漂移（'自然对数 (, 隐式 )'）
与瞬断 None ×5——三假设中「AX 层退化」获得主机样本（次要因，
根因让位于幂等碰撞）。

## run #3（判别实验：77+7，mark12 ×3）

修复（loop 传 `plan_step_id=f"decision-{res.steps}"`——每次决策是
新意图操作）后：**5/5 全核验 PASS，132s**，mark12 三次重复点击全真
执行（7→77→77+7）。修复前此任务必入重放死循环——判别命中。

## Acceptance Criteria（对照上轮四条边界）

- ✅ 检查点实拍：双检查点 CAS 工件 + 离线往返 + notes 留痕；
- ✅ 坏 JSON 占比：两轮 0 次发生（机制单测背书；27b 稳定）；
- ✅ 偏差率报表：离线取证输出「预期落史样本 16 条｜核验 4 条」
  （run#2 幂等污染下数字；机制可用性已证）；
- ✅ P6：根因锁定 + 判别实验修复验证 + 修复一行入 loop；
- ✅ 决策协议接线（va-7）；✅ pt↔px：27 mark 实测命中（run#3 五连中）；
  ✅ CAS 检查点：实拍+往返。

## Tasks/Subtasks

- [x] T1: 闸拒反馈带次数+候选（`_unavailable_feedback` /
      `_mark_mismatch_feedback`，破缓存活锁——测试 ×3）
- [x] T2: 驱动 scope 修复 + marks 重建降级 + sha 同一性主判 +
      `--run-id` 离线取证
- [x] T3: **幂等键修复**：loop 传 decision 序号 plan_step_id
- [x] T4: 陈旧部分标定缓存清除（重标 17 键全量）

## 验证

- run#2 机制实拍 + 取证报告（.vasta-cua/va-integration-report.json）
- run#3 判别实验 PASS（PYTHON_EXIT=0）
- 测试：micro_absorptions 8（含活锁 ×3）+ inspect 8；全量见终检
- 已知小瑕：取证表 mark 列/粗采样可视列在 AX 退化时降级（主判
  sha 同一性不受影响）；attempts 先显后加的 off-by-one 已修

## 遗留

- VM 多种子重跑基线（预期「点击失灵」主因消失后 mean 显著变化）
  → 下一 VM 评测窗口（数字回填 Phase 4 口径）；
- AX 表达式行漂移（次要因）→ 独立小项：display 元素锚定加固；
- 取证表可视化列（marks 降级路径的 32×32 辅证）已具备，按需用。
