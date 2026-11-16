---
story_key: va-4-compaction-checkpoint
baseline_commit: 7a508ec
---

# Story va.4: VISTA 吸收序④——压缩检查点治理（LoopContext 协议）

**Status:** done

## Story

As a 长任务 CUA 循环,
I want 上下文预算触线时无静默状态丢失、节奏化检查点留痕、边界漂移
fail-closed,
So that 超窗任务（如 TextEdit 文档流程）不因裸滑窗截断丢状态，且
归档历史不可变（VISTA compact 治理语义）。

## 来源

[吸收方案](../vista-absorption-plan-2026-11-16.md) §二 A——VISTA
``compact_hook.py``（压缩前强制检查点 + request/ready 门）与
``core/session.py`` 三态恢复（边界校验 / "changed before delivery"
拒绝 / forced_termination）。

## 本仓缺口（实测证据）

loop.py 两处 ``history[-4:]`` 裸滑窗——第 5 步前状态对模型静默消失
（吸收方案 §二 A 登记）。

## 有据偏离（非漏译）

- 不做 Claude Code 钩子（本仓自有循环）——吸收**语义**：触线投影 +
  检查点 + 边界校验；
- 检查点落 **CAS 工件 + 实体索引**（vlm.py 先例，AD-2 合规面）而非
  事件信封——seq 由 engine sequencer 独管，loop 侧手搓 envelope 会
  破坏「事件溯源唯一写路径」；事件引用化待协议层暴露安全追加口；
- 续接状态进事件/工件而非 markdown（WORKING.md 唯一值得搬的是
  「续接载体」语义，不是文件形态）。

## Acceptance Criteria:

**Given** 循环历史增长
**When** len(history) 超窗（4）
**Then** prompt 含「已归档步骤（紧凑投影）」（序③ history_lines）
+ 窗口全量 JSON——模型可复述边界前关键状态；窗口内输出与旧
``history[-4:]`` 逐字节相同（向后兼容，va-1 测试不动仍绿）
**And** 每 8 步落 LoopCheckpoint（全量历史 + 边界步，canonical JSON
零时钟熵）→ CAS 工件 + 实体索引 ``cua_loop_checkpoint:run:step``；
save/load 往返相等、按边界隔离寻址、缺失返回 None
**And** 每轮迭代校验活历史与最近检查点前缀全等——漂移/回退 →
CheckpointBoundaryError → 任务 fail-closed 终止（notes 留痕）

## Tasks/Subtasks

- [x] T1: ``checkpoint.py``——LoopCheckpoint（frozen，as_payload/
      from_payload 确定性）、should_checkpoint、context_projection、
      save/load（作用域缺省回落存储默认——search_by_entity 必填
      fail-closed 的适配）、validate_boundary
- [x] T2: loop 接线——两 prompt 改 context_projection；循环顶边界
      校验（漂移熔断）；步后节奏落盘（cfg 作用域）；
      ``history[-1]`` 的 display_after 变异发生在存盘**前**（同迭代
      内先变异后存——避免前缀假漂移，代码序保证）
- [x] T3: 测试 ×11：投影短历史逐字节不变 / 超窗归档头 + 窗口全量、
      节奏、负载确定性 + JSON 往返、CAS 存取往返 / 缺失 None / 边界
      隔离、边界校验通过 / 漂移抛（含步号）/ 短历史抛

## 验证

- 四 story 套件合计 **48 passed**；ruff 过；loop 导入冒烟过；
  **lint-imports 契约 5 kept / 0 broken**（AD-1 保有）
- 集成（真机 >8 步任务跑出「检查点@s8」note + 投影 prompt 实拍）→
  ⚠️ 待 VM 评测窗口（与 P6 同批，回填本节）

## 遗留

- 崩溃后续跑（load_checkpoint 接入 run_agent 冷启动路径）——协议件
  已就绪，接线待真实崩溃场景需求出现（避免无场景接线）；
- 上下文预算阈值目前为步数代理（窗口 4 / 每 8 步）——VLM token 级
  预算待序⑥/后续按实测窗口定。

## 集成回填（2026-11-16，va-8）

run#2 实拍：`[ckpt] s8→67911fe7b96b`、`[ckpt] s16→68c8e8f1306a` 双
检查点 CAS 落盘 + notes 留痕；离线取证（va_integration --run-id）
按 t-cua 作用域往返成功（边界 8/16 各含全量历史 8/16 条——
load_checkpoint 需显式传 cfg 作用域，默认作用域是存储默认值，已修）。
