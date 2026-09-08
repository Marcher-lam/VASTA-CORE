---
story_key: 1-5-runcontext-determinism
baseline_commit: f2b55cd03c99cd17033729a97bcbee321141261a
---

# Story 1.5: RunContext 确定性注入

**Status:** review

## Story

As a 平台工程师,
I want Run 的时钟、随机种子与配置经 RunContext 注入、模型请求响应整体 Artifact 化,
So that Run 历史可在干净环境确定性重放。

## Acceptance Criteria

**Given** 使用了时间与随机的核心路径代码
**When** 以相同种子重放事件流
**Then** 非模型事件与核验结果逐字节一致（NFR-002）
**And** 直接调用系统时钟/随机/环境读取的路径在静态检查下为零（AD-5）；重放模式适配器接确定性替身，接真实工具需显式授权

## Tasks/Subtasks

- [x] 1. RunContext（vasta_runtime.runcontext）：注入 clock/rng/config 快照/作用域身份/seed；seeded 模式 = 确定时钟（固定基点+微步进）+ random.Random(seed) + 种子派生事件 ID；record 模式 = 真实时钟（经 protocols.ids 供给）+ UUIDv7
- [x] 2. RunEngine 接入：事件 ts/id 全部来自 context；保留 legacy clock/config 参数（内部转为默认 context，既有测试不破坏）；budget 时钟同源
- [x] 3. 重放模式守卫：replay_mode 下引擎拒绝非确定性替身的环境适配器（除非 real_tools_authorized）；替身以 `deterministic = True` 属性标记
- [x] 4. 模型交换 Artifact 化：engine.record_model_exchange(request, response)——载荷整体落 CAS（source=model.exchange）→ 预算登记 → 返回 sha；证据先于预算检查落盘
- [x] 5. 确定性验证：同种子两次完整 Run 的事件流逐字节一致（model_dump_json 全等）；异种子 ID 不同
- [x] 6. AD-5 静态禁令测试：核心包扫描 datetime.now/time.time/random.* 直接调用与 os.environ，白名单仅 protocols/ids.py（供给点）与 storage 簿记（1.4 已文档化例外）；budget 默认时钟改为经供给点
- [x] 7. 对照 AC 验证并更新记录

## Dev Notes

- 种子派生 ID 与约定的 UUIDv7 偏差：确定性重放要求 ID 可再生，seeded 模式用 rng.getrandbits(128) 构造 UUID（记录模式仍 UUIDv7）——在代码与 story 注明，Stage 2 开放 schema 时可改 ULID(seed,counter)。
- fakes.py 的 FakeStorageAdapter.save_artifact 需接受元数据 kwargs（端口以带默认值参数扩展，AD-9 minor 规则）。
- 引擎事件"逐字节一致"包含 checkpoint payload（预算墙钟也走注入时钟，天然一致）。

## Dev Agent Record

### Implementation Plan

1. `runcontext.py`：RunContext（frozen dataclass）——create() 工厂分 seeded/record 两态；_SeededClock（固定基点+每次 1ms 步进）；new_event_id()（seeded→rng 派生、record→UUIDv7）；require_replay_adapter()（deterministic 属性或显式授权放行）。
2. `runner.py`：新增 run_context 参数（legacy clock/config 归一为默认 context）；_emit 的 ts 与 event_id 改由 context 供给；step 前置重放守卫；record_model_exchange（json 载荷整体落 CAS → record_model_call 预算）。
3. `budget.py`：默认时钟改经 protocols.ids.now_utc（缩小静态禁令白名单至纯供给点）。
4. fakes.py：save_artifact 接受 **meta（端口 minor 扩展）。
5. 测试：同种子两次完整 Run 事件 JSON 逐字节全等（NFR-002 核心）；异种子 ID 不同；时钟/RNG 可复现；重放守卫三态（拒真实/放行替身/授权放行）；模型交换落盘+预算+超限安全停止；AD-5 静态扫描（11 类禁令模式 × 核心包，白名单双文件，附白名单失效检测）。

### Debug Log

- 静态禁令测试首跑抓到"白名单自己"：相对路径计算按仓库根，白名单条目少了 packages/.../src/ 前缀——修正后零违例（budget.py 供给点改造后核心包确实无直接调用）。
- ruff 5 处自动修复（runner 中 context 化后不再使用的 ids 导入等）。

### Completion Notes

AC 逐条验证：
1. **同种子逐字节一致（NFR-002）** — `test_same_seed_byte_identical_event_stream`：seed=42 两次完整 Run（create→start→reset→step→step 含 pause 不可比因素外的全部事件），事件 model_dump_json 列表全等（含 ts、event_id、因果链、payload）；`test_seeded_clock/rng` 证明时间戳与随机序列各自可复现。✅
2. **异种子区分** — `test_different_seed_different_ids`。✅
3. **AD-5 静态禁令为零** — `test_no_direct_nondeterminism_in_core_paths`：7 个核心包 × 11 类禁令模式（datetime.now/time.time/monotonic/random 族/os.environ/uuid4）扫描，仅 ids.py（供给点）与 sqlite_store.py（簿记，1.4 文档化例外）在白名单；附白名单文件存在性检测防失效。budget 默认时钟已改经供给点。✅
4. **重放守卫** — replay_mode 下真实适配器 step 抛 `replay.real_env_unauthorized`；`deterministic=True` 替身放行；`real_tools_authorized=True` 显式授权放行；record 模式无守卫。✅
5. **模型交换 Artifact 化** — record_model_exchange：请求响应整体 JSON 落 CAS（sha 返回、内容往返校验）、模型调用预算 +1、超预算安全停止；证据先于预算检查落盘（顺序在实现中固定）。✅

回归：全套 86 passed（前序 74 + 本故事 12）；ruff 全绿；import-linter 双契约 KEPT。legacy clock/config 路径未破坏（1.2/1.3 测试原样通过）。

## File List

- packages/vasta-runtime/src/vasta_runtime/runcontext.py（新建）
- packages/vasta-runtime/src/vasta_runtime/runner.py（修改：context 接入、重放守卫、record_model_exchange）
- packages/vasta-runtime/src/vasta_runtime/budget.py（修改：默认时钟经供给点）
- packages/vasta-runtime/src/vasta_runtime/__init__.py（修改：导出 RunContext）
- tests/fakes.py（修改：save_artifact 接受元数据 kwargs）
- tests/test_runcontext_determinism.py（新建，10 测试）
- tests/test_determinism_guards.py（新建，2 测试）
- docs/stories/story-1-5-runcontext-determinism.md（本文件）

## Change Log

- 2026-09-08：Story 1.5 实现完成——RunContext 双态（seeded/record）注入、事件 ID/ts 全量 context 化、同种子逐字节重放验证、重放守卫三态、模型交换 Artifact 化、AD-5 静态禁令扫描；86 测试全绿；全部 AC 验证通过，状态置 review。
