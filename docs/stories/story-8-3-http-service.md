---
story_key: 8-3-http-service
baseline_commit: 3eb2109
---

# Story 8.3: HTTP 接入服务（G1）

**Status:** review

## Story

As a 非 Python 技术栈的工程师,
I want HTTP 服务暴露 Run 生命周期与证据查询,
So that 任何语言都能接入 VastaCore。

## Acceptance Criteria

**Given** SDK 已就绪（Story 8.1）
**When** 以服务模式启动
**Then** run/step/evidence/timeline 端点可用且经令牌鉴权
**And** 事件写入仍走唯一通道（AD-2，服务层不旁路）；服务崩溃不丢已落盘证据（FR-002）

## Tasks/Subtasks

- [x] T1: `create_app()` FastAPI 应用工厂——Bearer 令牌鉴权（401，token 必填无匿名面），
      服务端装配 env 工厂/tools/契约模板（复用 AgentSession，服务层不旁路 AD-2）
- [x] T2: 端点——POST /runs（建会话）；POST /runs/{id}/start|reset|act|complete；
      GET /runs/{id}/summary|timeline；GET /evidence/search（动作维度）；
      未知 run 404；VastaError → 400（HTTPException 不被吞）
- [x] T3: 崩溃安全——每事件即时落盘；服务 dispose（未 complete）后新开 store
      读同根目录事件完好且 timeline 全覆盖；重启后对历史 run 的
      timeline/search 仍可用（读存储而非会话内存；summary 会话死时从事件流推导终态）
- [x] T4: `vasta serve --token ...` CLI 命令（uvicorn；token 必填，缺参 exit 2）
- [x] T5: 测试 `tests/test_http_service.py` 10 条 + CLI serve 守卫 1 条；
      全量 416 passed +1 skipped；ruff 全绿；import-linter 2 契约 KEPT

## Dev Notes

- 依赖：fastapi 0.141.x（架构脊柱 web 核证，L172）+ uvicorn（serve 运行时）
  + httpx（dev 测试）。
- 位置：`packages/vastacore-sdk/src/vastacore/service.py`（组装根）。
- 并发：MVP 单写者——全局 asyncio.Lock 串行化 run 操作（多会话并发属 Stage 3）。
- summary 对已死会话从事件流推导终态（run.completed/failed），不依赖内存。

## Dev Agent Record

### Debug Log

- **路径双重嵌套 bug（首版实锤）**：AgentSession.create 会自加 `/store`，服务层
  又传了已含 store 的路径 → 会话写进 `tmp/store/store/`、服务读 `tmp/store/`，
  timeline 404/search 空。修复：统一 root=基目录语义（双方同规则加 /store）。
- 404 被 400 吞：生命周期端点 `except Exception` 连 HTTPException 一起捕获——
  加 `except HTTPException: raise` 豁免。

### Completion Notes

- `create_app(env_factory, tools, contracts, root, token)`：服务端持装配件；
  每会话经 AgentSession 建独立 run（写通道唯一，AD-2）；`VastaService` 持读连接，
  timeline/search 读存储——重启后历史 run 仍可查。
- 六段链经 HTTP 不变：act 端点 → AgentSession.act → execute_contracted
  （测试断言 action.contracted/executed/verification.passed 落事件）。
- 崩溃安全实测：服务 dispose（未 complete）→ 新开 store 事件完好、timeline
  全覆盖；同根目录重启 → 历史 run timeline 200。
- 依赖变更：vastacore-sdk + fastapi/uvicorn；根 dev 组 + httpx（脊柱已核证）。

### File List

- packages/vastacore-sdk/src/vastacore/service.py（新增：create_app/VastaService/serve）
- packages/vastacore-sdk/src/vastacore/__init__.py（导出）
- packages/vastacore-sdk/src/vastacore/cli.py（serve 命令）
- packages/vastacore-sdk/pyproject.toml（fastapi/uvicorn 依赖）
- pyproject.toml（dev + httpx）
- uv.lock（锁定）
- tests/test_http_service.py（新增：10 条）
- tests/test_cli.py（serve 守卫 +1）
- docs/sprint-status.yaml（8-3 状态）

## Change Log

- 2026-09-09: Story 8.3 实现完成（T1–T5 全过，416 passed +1 skipped，ruff/lint 绿）→ review
