---
story_key: 1-1-monorepo-protocols
baseline_commit: 29af1ce4fe37d7e64554890feb50e8acd9a766ea
---

# Story 1.1: Monorepo 骨架与协议基座

**Status:** review

## Story

As a VastaCore 开发者,
I want 一个按依赖规则（AD-1）搭好的 uv workspaces monorepo 与 vasta-protocols 基座（事件信封 schema + 五协议接口 + 契约测试套件框架）,
So that 后续所有能力在一致、可测试的骨架上生长。

## Acceptance Criteria

**Given** 全新克隆的仓库
**When** 运行 `uv sync` 与 `uv run pytest`
**Then** 十个 `vasta-*` 包骨架全部可安装、测试与 lint 在 CI 通过

**And**
- `vasta-protocols` 对本仓库其他包零依赖（AD-1，用 import-linter 校验）
- 事件信封含 `run_id/seq/type/parent_event_id/ts/tenant_id/project_id` 且实现 `(run_id, seq)` 唯一约束（AD-2）
- Model/Environment/Tool/Storage/Verifier 五协议 Protocol 类可被 adapter 实现并被契约测试套件驱动
- 协议与 schema 均携带版本字段（FR-001 后果）

## Tasks/Subtasks

- [x] 1. uv workspaces 根配置与十个 `vasta-*` 包骨架（pyproject + src 布局 + `__init__` 含版本字段）
- [x] 2. 事件信封 schema：pydantic v2 模型（七字段 + `schema_version` + 校验器：seq≥0、type 为 past-tense 点分、ts 为 ISO8601 UTC）与参考内存事件日志（强制 `(run_id, seq)` 唯一）
- [x] 3. 五协议接口：ModelAdapter / EnvironmentAdapter / ToolAdapter / StorageAdapter / Verifier（含 capabilities 与 manifest 结构体）
- [x] 4. 契约测试套件：每协议一个可复用 pytest 基类 + 信封/唯一性契约测试（用一个假 adapter 驱动验证套件本身可用）
- [x] 5. AD-1 依赖校验（import-linter）+ ruff lint + 全部测试绿
- [x] 6. CI 工作流（uv sync + lint + pytest）
- [x] 7. 对照 AC 逐条验证并记录 Dev Agent Record

## Dev Notes

- 架构约束（脊柱 docs/architecture/architecture-VastaCore-2026-09-08/ARCHITECTURE-SPINE.md）：
  - **AD-1**：protocols 是依赖根、零本仓库依赖；本故事只有 protocols 有实质代码，其余九包为空骨架（`__init__` + 版本）。
  - **AD-2**：事件信封字段与 `(run_id, seq)` 唯一性——本故事在 protocols 内交付参考内存事件日志承载该约束（SQLite 落地属 Story 1.4）。
  - **AD-7**：一切持久实体带 `(tenant_id, project_id)`——信封字段即首个体现。
  - **约定**：事件 past-tense 点分（`run.created`）；13 族封闭集；错误信封 `{code,message,retryable,run_id,event_id}`；UUIDv7/ULID 字符串 ID；ISO8601 UTC。
- 技术栈（已核证）：Python ≥3.12（本机 3.12.10）、pydantic 2.13.x、pytest 9.1.x、hypothesis 6.167.x、ruff、import-linter。
- 包清单（十个）：vasta-protocols、vasta-storage、vasta-cognition、vasta-contracts、vasta-policy、vasta-runtime、vasta-model-lab、vasta-eval、vastacore-sdk、vasta-adapters。
- 接口形态依据蓝图 §18.1：EnvironmentAdapter(reset/observe/execute/status)、ModelAdapter(capabilities/generate)、ToolAdapter(manifest/dry_run/execute/read_back/compensate)、Verifier(manifest/verify)；StorageAdapter 为 Evidence Store 端口（append_event/get_event，唯一性约束所在）。
- 禁止：本故事不实现 SQLite/CAS（Story 1.4）、不实现任何运行循环（Story 1.2+）。

## Dev Agent Record

### Implementation Plan

1. 根 pyproject（uv workspace，members=packages/*，dev 组含 pytest/pytest-asyncio/hypothesis/ruff/import-linter；ruff 与 importlinter 配置内嵌）。
2. 九个骨架包由脚本生成（pyproject 依赖 vasta-protocols 以在包元数据层面编码 AD-1；src 布局 + `__version__`）。
3. vasta-protocols 实质代码：`ids.py`（UUIDv7/UTC）、`errors.py`（错误信封 + DuplicateEventError）、`envelope.py`（EventEnvelope 七字段 + schema_version + 校验器 + 13 族封闭集 + InMemoryEventLog 参考实现）、`protocols/`（五协议 + manifests/capabilities，各带版本常量）、`contract_suites/`（7 个可继承基类）。
4. 根 tests/：假适配器驱动全部套件（证明套件可运行）+ 工作区导入测试 + hypothesis 性质测试。
5. CI：uv sync → ruff → lint-imports → pytest。

### Debug Log

- 初版 ts 校验器含一处草率表达式，实现内即刻发现并改为 `astimezone(UTC)` 规范化。
- 首轮 ruff 报 10 处（骨架 docstring 超长 ×2、未用导入等），自动修复 9 处 + 手改 2 处 docstring 后全绿；修复后复跑 38 测试无回归。
- 依赖说明：pytest-asyncio 为异步契约测试所需（AD-10 async-first 的测试面），随测试栈一并引入；uuid6 为约定指定的 UUIDv7 库。均为 Dev Notes 范围内。

### Completion Notes

AC 逐条验证：
1. **十包可安装、测试与 lint 在 CI 通过** — `uv sync --all-packages` 十包全部解析安装；`uv run pytest -q` 38 passed；`uv run ruff check` All checks passed；`.github/workflows/ci.yml` 含 sync/lint/lint-imports/pytest 四步。✅
2. **protocols 零本仓库依赖（AD-1）** — `uv run lint-imports`：契约 "vasta-protocols is the dependency root" KEPT，附带第二条 "core packages may not import adapters or sdk" KEPT；另有测试级冗余检查 `test_no_intra_repo_imports_in_protocols_source`。✅
3. **信封七字段 + (run_id,seq) 唯一（AD-2）** — EventEnvelope 含 run_id/seq/type/parent_event_id/ts/tenant_id/project_id（+event_id/schema_version/payload），frozen+extra=forbid；InMemoryEventLog 强制唯一（DuplicateEventError），EventLogContract 5 条契约测试驱动验证（含跨 Run 同 seq 合法、因果父项回溯）。SQLite 强制属 Story 1.4。✅
4. **五协议可被实现并被套件驱动** — 五个 runtime_checkable Protocol；tests/test_contract_suites.py 用假适配器驱动全部 7 个套件通过；test_workspace 断言五个 isinstance 成立。✅
5. **版本字段（FR-001）** — PROTOCOL_VERSION/ENVELOPE_SCHEMA_VERSION + 各协议版本常量均为 0.1.0；manifest（Tool/Verifier）与 capabilities 均带 version 字段；test_protocols_surface 断言。✅

超出 Story 范围的未做：SQLite/CAS、运行循环、真实适配器（属后续 Story）。

## File List

- pyproject.toml（新建：workspace 根 + dev 依赖 + ruff/importlinter/pytest 配置）
- uv.lock（新建）
- .github/workflows/ci.yml（新建）
- packages/vasta-protocols/pyproject.toml、src/vasta_protocols/__init__.py、ids.py、errors.py、envelope.py
- packages/vasta-protocols/src/vasta_protocols/protocols/__init__.py、environment.py、model.py、tool.py、storage.py、verifier.py
- packages/vasta-protocols/src/vasta_protocols/contract_suites/__init__.py、event_envelope.py、event_log.py、environment.py、model.py、tool.py、storage.py、verifier.py
- packages/{vasta-storage,vasta-cognition,vasta-contracts,vasta-policy,vasta-runtime,vasta-model-lab,vasta-eval,vastacore-sdk,vasta-adapters}/pyproject.toml + src/*/__init__.py（各 2 文件，骨架）
- tests/__init__.py、fakes.py、test_contract_suites.py、test_workspace.py、test_envelope_properties.py
- docs/stories/story-1-1-monorepo-protocols.md（本文件）

## Change Log

- 2026-09-08：Story 1.1 实现完成——uv workspaces 十包骨架 + vasta-protocols（事件信封/13 族封闭集/内存事件日志/五协议/七套件）+ 38 测试 + AD-1 双 import-linter 契约 + CI。全部 AC 验证通过，状态置 review。
