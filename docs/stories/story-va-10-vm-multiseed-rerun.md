---
story_key: va-10-vm-multiseed-rerun
baseline_commit: 1cbd0e4
---

# Story va.10: VM 多种子基线重跑——五轮事故、四修复、终局翻身

**Status:** done

## Story

As a Phase 4 基线的对照实验,
I want P6 修复（及连带挖出的全部坑位）后的 ≥10 种子重跑,
So that 用同口径 CI 回答「修复带来了什么」。

## 终局数字（run6 + seed-9 补齐，2026-11-18）

| | 重跑（本 story） | 基线（eea0301） |
|---|---|---|
| mean | **0.916** | 0.583 |
| CI@95% | **[0.843, 0.989]** | [0.483, 0.684] |
| 种子 | 0.83/1.00/0.83/1.00/1.00/0.67/0.83/1.00/1.00/1.00（七满分） | mean 0.583 |
| 崩溃 | 0 | 0 |

**Δ = +0.333（+57%），CI 不重叠——统计显著**。口径：同模型
（qwen3.5-9b-mlx）、同温度（0.3）、同 6 任务、同 VM（vasta-ci-macos
金像系）；增量=四修复合力（幂等 #28 + 滴流 #29 + 字形 #30/#26 族
四层），非单变量——如实登记。

逐任务（重跑 vs 基线）：mul-42x3 10/10（~9）、mul-7x8 10/10（~9）、
add-12p34 7/10（~9，**唯一下行**——残余失败待查）、sub-90m15
**10/10（3）**、div-144d12 **8/10（0）**、mix-6x7m2 **10/10（4）**。
基线三大重灾区（sub/div/mix = 3/0/4）翻身至 10/8/10——「失败率随
任务位次递增」的退化曲线消失（其根因即幂等重放）。

## 五轮事故与修复（全程 TDD，全部入库）

| run | 结局 | 挖出 | 修复 |
|---|---|---|---|
| run1 | seed0-2 好（0.50/0.67/0.83），3-9 七连崩 rc=-9 | #29 LM Studio swap 龟速滴流（栈现行：`_buffered_readline` 挂 VLM TCP、socket 超时免疫） | 硬总超时 wait_for（`efe56ff`）+ LM 服务重启减压 |
| run2 | 假阳性采样（看门狗盯错信号）+ 真冻结再证 | 看门狗信号学：主日志种子期间本就安静 | WAL 活性判据 |
| run3 | seed-0 五任务 4 PASS 后磨死 | #30 按钮层字形（'-'≠'−' 闸拒马拉松，sub 单场 1398s） | `_normalize_button`（`d8bcff8`） |
| run4 | 三连崩 + faulthandler 上保险 | #29 机制本地验证正常（7.0s 精确拉回）vs 产线静默矛盾 → 时间盒止猜 | faulthandler 周期栈 + 种子上限 60min（`1cbd0e4`） |
| run5 | 十颗齐 0.617 [0.507,0.726]——判中间值 | #26 族第四层：loop 历史快检漏归一（引擎核验 3✓ 全过而快检误判 → 假恢复带崩；sub/mix 1/10 崩塌、div 8/10 翻身旁证） | `_step_verified` 两侧归一（`b208097`/`0a330dc`） |
| run6 | **终局**：0-8 落袋（隔夜宿主睡眠二连击杀 seed-9） | 运维坑：caffeinate 限时到期→睡；/tmp 周期清理杀 relay ×2 | caffeinate 无限守护 + relay 永久副本 `~/bin`；`--start` 补齐通道（`bddcffb`/`59bfa6f`） |

## 验证

- 终局 CI/分布如上（VM 内 `~/VastaCore/.vasta-seeds/` 十颗全档 +
  五轮现场归档 `~/vasta-seeds-run*-evidence`）
- 全量 1397 passed（四修复各带 TDD：#29×2、#30×6、快检×3、offset×3）
- 运维面证据：本机 caffeinate 无限 PID 42337、relay `~/bin` 副本

## 遗留

- add 7/10 的残余失败（3 颗）——非字形族；待读 seed 日志定因
  （候选：VLM 空 content thinking 失控 #23 的重试预算耗尽）；
- faulthandler 保险本轮未触发（run6 无停滞）——留作常驻；
- VM/relay/caffeinate 保持运行供复核；收摊：`kill 42337` +
  `tart stop vasta-ci-macos`。
