---
story_key: 8-15-sidecar
baseline_commit: 72103cc
---

# Story 8.15: Sidecar 接入形态（G1，FR-002 第五形态）

**Status:** done

## Story

As a 非 Python 技术栈的 Agent 团队,
I want 一个与我的 Agent 进程同部署的本地伴生进程,
So that Agent 侧任意语言只说 HTTP、证据与六段链在 sidecar 侧。

## Acceptance Criteria

**Given** `python -m vastacore.execution.sidecar --module myagent:build`（build() → SidecarSpec）
**When** SidecarProcess.spawn 起 sidecar（ready-file 握手）
**Then** Agent 经纯 HTTP（observe/act/complete/timeline/summary）操作；
写动作走同一六段链（verification.passed 事件入证据库，库落 root/store）；
数据面全端点 token 强制（healthz 豁免）、loopback-only 绑定
**And** /shutdown 优雅关停（会话关闭、进程退 0）（FR-002，蓝图 §18.5-4）

> **启动门槛裁决（2026-11-06）**：同 8.14——用户指令提前实施。

## Tasks/Subtasks

- [x] T1: `SidecarSpec`（env/tools/contracts/seed/run_id/budget 或
      session_factory）+ `build_sidecar_app(spec, token)`——单会话最小面：
      healthz/observe/act/complete/summary/timeline/shutdown；lifespan
      装配会话（start+reset）与关闭
- [x] T2: `SidecarServer` 进程内线程形态（uvicorn 后台线程、随机端口、
      healthz 就绪轮询）——测试/嵌入用
- [x] T3: `SidecarProcess.spawn` 子进程形态——预绑 socket 先写 ready-file
      （原子写：tmp+rename）、父进程 healthz 轮询确认会话就绪、close
      优雅关停（/shutdown → 等退 → 超时强杀）
- [x] T4: `SidecarClient` 纯 stdlib（urllib）——Bearer token、JSON 面；
      HTTPError → VastaError(code=sidecar.http_error) 带状态码
- [x] T5: 安全面——token 全数据面端点强制（hmac 常数时间比较）、
      loopback-only（127.0.0.1）、uvicorn access_log 关闭（stderr 管道
      不被访问日志灌满）
- [x] T6: 测试 `tests/test_sidecar.py` 6 条（进程内全契约面/token 401+
      healthz 豁免/loopback+随机端口/422 形状/子进程握手+优雅退 0/
      证据落 root/store）+ 夹具 `tests/_sidecar_usermod.py`（外部团队
      build() 形态）；全量 1260 passed + 5 skipped；ruff 全绿；
      import-linter 5 契约 KEPT

## Dev Notes

- 位置：`packages/vastacore-sdk/src/vastacore/execution/sidecar.py`
  （不 import ops——与 ops.service 的分工：service=控制面多会话
  token/RBAC；sidecar=单伴生 loopback 一次性 token 同进退）。
- `python -m vastacore.execution.sidecar` 双模块陷阱：__main__ 转调
  正身 `vastacore.execution.sidecar._main`——用户模块 import 的类在
  正身实例内，isinstance 闭合（否则 SidecarSpec「同名不同一」）。
- uvicorn ≥0.29 lifespan 先于绑端口：端口不经 lifespan 暴露——
  `_main` 预绑 socket 即知端口、先写 ready-file；会话就绪以 healthz
  轮询确认（文件出现 ≠ 会话可用）。
- FastAPI Request 注解须模块顶层导入（future-annotations 下嵌套
  局部导入的字符串注解解析不了 → 被当 query 参数）。

## Dev Agent Record

### Debug Log

- 三连修：① Request 注解 422；② __main__/正身双模块 isinstance 失效；
  ③ uvicorn lifespan 时序（server.servers 尚未建）——预绑 socket 根治。

### Completion Notes

- FR-002 第五形态交付；非 Python Agent 接入参考 = SidecarClient 的
  HTTP 面（约 40 行，任意语言照抄）。

### Change Log
