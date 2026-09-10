---
story_key: 8-11-tool-proxy
baseline_commit: 347415c
---

# Story 8.11: Tool Proxy（G1）

**Status:** review

## Story

As a 浏览器自动化团队,
I want Tool Proxy 把现有 Playwright 工具调用代理进六段链,
So that GUI Pack 不必重写既有工具。

## Acceptance Criteria

**Given** 既有 Playwright 工具调用
**When** 经 Proxy 执行
**Then** 走网关通道（清单/幂等/风险分类/超时）；原始响应入 CAS
**And** 蓝图 §31 Stage 2 交付物项（SM-5 伙伴信号确认需求后启动）

> **启动门槛裁决（2026-09-10）**：原排序「SM-5 伙伴信号后启动」，由用户
> 指令提前实施——Proxy 实现为**通用既有工具包装**（Playwright 为动机场景
> 但不引入浏览器依赖，测试用替身浏览器工具）。

## Tasks/Subtasks

- [x] T1: `proxy_tool(name, fn, *, risk, read_only, idempotent, timeout_ms,
      version)`——既有 async 可调用包装为 ToolAdapter：清单强制分类、
      适配器级幂等缓存（同键 replayed=True，`calls` 计数器审计底层执行次数）、
      单次调用 wait_for 超时（超时/异常按网关协议路径落 adapter_error）、
      action.args 以 kwargs 转发
- [x] T2: 浏览器预设分类——`browser_action_proxy`（写操作 R2/非只读/
      **非幂等**：双击有副作用）与 `browser_read_proxy`（读操作 R1/只读/
      幂等）工厂；FakeBrowser 替身（Playwright 接入时换真实 page 即可）
- [x] T3: 集成验证——Proxy 工具经 AgentSession.act() 走六段链
      （contracted/executed 落事件）；原始响应 result_ref 入 CAS 可哈希
      取回（替身浏览器响应原样在 blob）；读预设过五面协议检查器
- [x] T4: 测试 `tests/test_tool_proxy.py` 7 条（网关注册分类/六段落事件+CAS/
      幂等 fn 仅执行一次/超时捕获/写读预设风险分类/协议检查绿）；
      全量 482 passed +1 skipped；ruff 全绿；import-linter 2 契约 KEPT

## Dev Notes

- 位置：`packages/vastacore-sdk/src/vastacore/toolproxy.py`（组装根）。
- 不引入 playwright 依赖：Proxy 是通用包装层；Playwright 接入时以
  `proxy_tool(browser_click, ...)` 形式挂真实函数（GUI Pack Stage 2 后段）。
- 适配器级幂等缓存与脚手架骨架同模式（协议检查器直调适配器路径）。

## Dev Agent Record

### Debug Log

- 协议检查器以空 args 探测适配器——被包装函数带必选参数会炸（fn 契约与
  探测形态不匹配，非 Proxy 缺陷）；替身函数补默认参数。真实 Playwright
  接入时同理：被代理函数应可空参探测或提供默认 selector。

### Completion Notes

- ProxyToolAdapter：签名正确（含 idempotency_key）+ 幂等缓存（同键
  replayed=True，底层 fn 计数可审计）+ wait_for 超时（慢函数 60ms 超时
  实测落 adapter_error 不悬挂）+ args→kwargs 转发。
- 浏览器预设把风险判断前置：click/type R2 非幂等、get_text/screenshot
  R1 只读幂等——GUI Pack 接入时直接选预设不再逐工具拍风险。
- 六段链集成实测：act() → contracted/executed 事件 + 替身浏览器原始响应
  入 CAS 哈希可取回——既有工具零重写进链达成。
- Playwright 真实接入（GUI Pack 决议后）：`proxy_tool("browser_click",
  page.click, ...)` 换真实函数即可，结构零变更。

### File List

- packages/vastacore-sdk/src/vastacore/toolproxy.py（新增：proxy_tool/
  browser_action_proxy/browser_read_proxy/ProxyToolAdapter）
- packages/vastacore-sdk/src/vastacore/__init__.py（导出）
- tests/test_tool_proxy.py（新增：7 条）
- docs/sprint-status.yaml（8-11 状态）

## Change Log

- 2026-09-10: Story 8.11 实现完成（T1–T4 全过，482 passed +1 skipped，ruff/lint 绿）→ review
