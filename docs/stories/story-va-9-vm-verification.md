---
story_key: va-9-vm-verification
baseline_commit: 9c3b72d
---

# Story va.9: VM 内验证——P6 修复在基线原产地判别通过（+坑位 #27）

**Status:** done

## Story

As a Phase 4 基线的原产地环境,
I want 主机侧的 P6 根因修复在 VM 内复验（判别实验 + 长任务审计）,
So that 「VM 多种子基线重跑」前先确证修复在基线环境同样成立。

## 环境（vm-ops-manual 方式 C 三件套）

- relay 脚本曾随 /tmp 清盘——重建（25 行 TCP 转发；顺修自造签名
  bug：`start_server` 回调是 `(reader, writer)` 双参）；
- caffeinate（交流电在位）+ `tart run --no-graphics`；
- 代码同步 `git archive HEAD`（9c3b72d）→ VM `uv sync --frozen`；
- agent 从 VM 内 Terminal 启动（`.command` + `open -a Terminal`——
  SSH 直跑被 TCC 拒，手册实测坑）；离线取证走 SSH（纯读库）。

## 验证结果（VM 192.168.64.2 / macOS 26.6.2 / qwen3.8-27b 经 relay）

| 项 | 结果 |
|---|---|
| 判别实验 `77+7`（mark12 ×3） | **PASS**（EXIT_77=0，5 步全核验 ✓）——修复前必入重放死循环 |
| 长任务（17 位加法，20 步） | FAIL（坑位 #27 千分位，任务本身不可解）但**测试目标全中**：链 20/20、核验 16✓/0✗、AC 恢复 s5/s10/s15 全真点击、预算封顶收场（非熔断） |
| replayed 审计（两 run 25 动作） | **replayed=True 0 次**——重复 mark 循环（mark9/20/21/22/16 各 3-4 轮）全真执行 |
| 检查点（序④） | `[ckpt] s8→7ee9a6c1` + `[ckpt] s16→0153fe01` 双落 CAS——VM 实拍 |

## 新坑位登记

- **#27 VM 千分位**：输入第 4 位数字起屏显 `'1,234'`，核验期望
  `'1234'` 不含 → 必 ✗ → AC 循环到封顶。修法已定（比较前剥
  `,`，同 #26 两侧归一原则）；Phase 4 基线 6 任务数值均 <1000
  未触发——多种子重跑若加长数值须先修。

## Acceptance Criteria:

**Given** 修复代码（9c3b72d）同步入 VM、从图形会话 Terminal 启动
**When** 判别实验与含重复 mark 的长任务运行
**Then** replayed 审计零重放；重复键任务通关（77+7 PASS）；检查点
节奏触发并落 CAS；恢复动作真执行
**And** 新发现坑位入册（#27）

## 验证

- ~/va-vm-test.log（VM）全量日志 + 两 run replayed 审计输出
- 主机侧对照：同一判别实验主机 PASS（va-8 run#3）——双环境一致

## 遗留

- **VM 多种子基线重跑**（≥10 种子 × 6 任务，与 Phase 4 口径对齐）
  ——修复+坑位表就绪，窗口约 40 分钟/种子任务组；预期「点击失灵」
  主因消失后 mean/CI 显著变化（数字回填 vm-gui-scenario-plan）；
- #27 千分位修复（一行归一）可在重跑前顺手做（本 story 未做——
  避免未测试的改动混入已验证批次）。
