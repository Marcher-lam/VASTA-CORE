---
story_key: va-3-inspect-history-projection
baseline_commit: 0daa163
---

# Story va.3: VISTA 吸收序③——inspect + history 模型侧投影（R0）

**Status:** done

## Story

As a CUA 模型侧循环,
I want 从存档帧按 CAS ref 回看指定区域（最近邻放大）与分页回看交互
历史,
So that 模型能主动复查自己的视觉证据（VISTA 核心机制），且为序④
上下文预算治理提供紧凑历史投影构件。

## 来源

[吸收方案](../vista-absorption-plan-2026-11-16.md) §二 B。语义移植自
VISTA ``core/tools.py``（inspect ≤16 views 请求序返回、
"without smoothing"）/ ``core/session.py``（帧寻址 + 实现）/
history 分页（start 含 / end 排 / 钳制 / limit 封顶）。

## 有据偏离（非漏译）

- 帧寻址用 **CAS sha256 ref**（VISTA 用 turn 索引）——天然确定性
  重放兼容；
- 放大**保持纵横比**（VISTA 固定 1024 方形——其显示是方形；CUA
  窗口裁剪非方形，方形化引入几何失真）；
- pt→px 换算用 ``Region.from_pt(scale)``，scale 逐帧实测（惯例同
  scene.py:48 截图 px 宽 / 屏幕 pt 宽）——计划 ⚠️「标定映射」以
  活体惯例收口，无需 VM 窗口单独标定。

## Acceptance Criteria:

**Given** 存档帧（bytes 或 CAS ref）+ 像素 Region（或 pt×scale）
**When** inspect_views 多视图回看
**Then** ≤16 上限、请求序返回、ref 经 store.get_artifact 取原件、
缺失 ref 由存储层 fail-closed；crop_view 最近邻放大纯色不混、
纵横比保持、**越界显式拒绝**（PIL 越界是静默黑边——review 补强）
**And** history_lines 分页语义正确（start 含/end 排/钳制/封顶），
✓/✗ 核验标记、部分记录容错
**And** ViewSpec frame_bytes/frame_ref 二选一构造期校验

## Tasks/Subitems

- [x] T1: ``Region.from_pt``（pixels.py——pt×scale 四舍五入换算）
- [x] T2: ``revisit.py``——crop_view（NEAREST + 纵横比 + 越界拒绝）、
      ViewSpec（xor 校验）、inspect_views（上限/顺序/CAS 取件/
      store 缺位 fail-closed）、history_lines（VISTA 分页语义）
- [x] T3: 测试 ×16（tests/test_cua_revisit.py）：四象限纯色放大、
      纵横比、PNG 魔数、越界拒绝（review 补）、pt 换算含半像素、
      请求序 + ref 往返 + 缺 ref + 无 store + 17 上限 + xor、
      history 窗口/钳制/封顶/✗ 标记/部分记录

## 验证

- 三 story 套件合计 **37 passed**（14 基础 + 2 review 补强 + 12 + 9）
- ruff 过；loop/revisit/pixels 导入冒烟过
- code-review 修正 ×2（crop 越界静默黑边 → 显式 ValueError；
  store=None + frame_ref → 可行动错误）

## 遗留

- 决策协议接线（模型在 JSON 决策里发 inspect 请求）→ 序④ LoopContext
  重构时一并设计（避免两次改循环协议）；
- history_lines 接入 prompt（替代 history[-4:] JSON）→ 序④ 预算
  触线时启用。
