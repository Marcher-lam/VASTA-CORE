---
story_key: 10-14-console
baseline_commit: 80ef74d
---

# Story 10.14: Console 最小可用面（G0，NFR-012/013 收口）

**Status:** done

## Story

As a 运维/治理人员,
I want 一个键盘可操作、语义化标注、可本地化的 HTML 控制台,
So that NFR-012（无障碍）与 NFR-013（国际化）两处 UI 面缺口闭环。

## Acceptance Criteria

**Given** `mount_console(app, store=..., token=...)`（与业务面同 token）
**When** 浏览 /console（检索）、/console/runs/{id}（时间线）、…/compare（可读对比）
**Then** 首个可聚焦元素为跳转链接；全部交互原生元素（零 JS）；表单
label 显式关联；表格 caption + th scope；html lang 随 locale 切换；
UI 串/时间格式/数字分组/事件与策略描述双语目录化
**And** 对比视图按点分路径四组两栏；渲染零写侧——事件语义不随语言
切换变化（NFR-012 + NFR-013）

## Tasks/Subtasks

- [x] T1: `ops/console.py`——服务端渲染 HTML、自包含零构建零 JS
      （Studio/Epic4 Replay 同形态）；`mount_console`（token 与业务面
      一致，浏览器直访需带头部代理——认证模型不放宽）
- [x] T2: 无障碍四件——skip link（首个可聚焦元素）、原生元素键盘
      可达（无 onclick/javascript:）、label for 关联、table caption +
      th scope + main/nav 地标 + 焦点可见样式 + WCAG 对比色
- [x] T3: i18n 机制——双语目录（UI 串）、`format_ts`（手工月名/24h vs
      AM/PM——不依赖系统 locale）、`format_number`（千位分组）、
      `describe_event`（事件/策略描述目录化，未命中回退原始类型）
- [x] T4: 可读对比——payload 点分路径展平，变更/仅前/仅后/相同四组
      两栏（before/after），变更行视觉标记
- [x] T5: 原生表单落点 `/console/runs/__lookup__`（run_id 查询参数 →
      303 重定向时间线——无 JS 的检索路径）
- [x] T6: 测试 `tests/test_console.py` 18 条——三页 401/未知 run 404；
      skip 首位/无 JS/label/caption+scope/lang+地标；双语切换/时间
      两种呈现/数字分组/描述目录与回退；四组对比（zh+en）/坏 seq 404/
      lookup 重定向；渲染零写侧。全量 1305 passed + 5 skipped；
      ruff 全绿；import-linter 5 契约 KEPT

## Dev Notes

- 位置：`packages/vastacore-sdk/src/vastacore/ops/console.py`
  （ops 层，FastAPI 挂载式与 studio 同模式）。
- 事件语义稳定（NFR-013 字面）：describe_event 只做展示转换，
  未命中回退原始类型——两语言回退一致；渲染路径零写侧有测试锚定。
- 认证模型：Authorization 头（与 Studio 一致）——浏览器直访需代理/
  扩展；不为 UI 放宽零匿名面（AD-2 语义）。

## Dev Agent Record

### Debug Log

- 事件 seq 从 0 起（Sequencer last_seq 初始 0）——对比用例先按 1 起写
  错，跑通调试脚本后修正测试。
- compare 的集合运算优先级（`-` 先于 `&`）写错过一次——shared 先算
  再求差，正确分组。

### Completion Notes

- NFR-012 由 absent 升级 delivered（工程内可验面）；NFR-013 由
  partial（schema 面已交、UI 面零实现）升级 delivered——终检 §三 表
  两行闭环。

### Change Log
