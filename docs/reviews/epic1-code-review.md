# Epic 1 代码评审报告（2026-09-08）

- **评审对象**：`29af1ce..HEAD`（Epic 1 全部 7 个 Story 实现，73 文件）
- **四层评审**：Blind Hunter（24 条）/ Edge Case Hunter（21 条）/ Verification Gap（5 大项）/ Acceptance Auditor（17 项），全部独立上下文执行
- **Triage 结果**：去重后 41 项 —— **patch 35 / defer 3 / dismiss 3 / decision_needed 1**
- **验证**：修复后 123 测试全绿（新增 14 个回归钉子）、ruff 干净（含 examples）、import-linter 双契约 KEPT、quickstart 实跑正常

## 已修复（patch，35 项）

### 正确性与安全
- 升级暂停不建 checkpoint → resume 后环境变化检测静默失效（三评审共击）：`_escalate` 现构建 checkpoint；`run.paused` payload 统一双键 `{checkpoint, escalation}`
- 事件读取/元数据读取无作用域过滤（AD-7/14）：`get_event`/`iter_run_events`/`artifact_info` 增加可选 (tenant, project) 过滤与可达性校验；半作用域调用（只给一边）fail-closed 拒绝
- CAS 临时文件固定名跨进程冲突 → 唯一后缀；已存在 blob 被篡改时再保存同内容 → 校验并抛 corrupted；`user_version > 1` 拒读；`event_id UNIQUE` 冲突与 seq 冲突区分错误码
- `_emit` 序号先增后写 → 写成功才推进（不留因果链空洞）；`pause` 先验转移再存 checkpoint；`resume` 强制 PAUSED 态 + 重观察也记录为证据 + 重放守卫；`reset` 先真实重置成功再记录（失败不留假状态）
- 状态守卫统一：`observe`/`ingest_external`/`record_model_call(exchange)` 均要求 STARTED（顺带修 CREATED 下预算错误被转移错误掩盖）
- `env.execute` 异常 → Run 落 `run.failed(env_error:*)` 不卡 STARTED
- AD-15 冲突修正：预算墙钟是安全强制 → 独立真实时钟（`safety_clock` 可注入供测试），不再挂 seeded 注入时钟
- 暂停期间墙钟预算照烧 → BudgetTracker 增加暂停计费豁免（人工审阅等待不计入）
- 单一 RNG 流耦合 → 事件 ID 独立流（插事件不再平移应用随机数）
- replay 模式必须带 seed（否则 ValueError）；run_context 与 legacy config/clock 同传 → 歧义拒绝
- 非序列化 args/detail → `json.dumps(default=repr)` 不再崩溃（supervisor 模式键 + 观察采集）
- 采集覆盖适配器自带 artifact_refs → 合并；协议 `save_artifact` 签名补齐引擎实际调用的可选参数（AD-9 minor）
- 事件缺失键异常统一 `VastaError(event.not_found)`（内存日志此前裸 KeyError）+ 契约用例
- quickstart：`try/finally` 关连接；Supervisor 升级也接为正常结局；同根复用 run_id → 清晰错误提示；sdk 不再摸引擎内部（公共 `episode_ended`）；路径注释纠正

### 工具链与文档
- `VASTA-BRAINSTORM-PLAN.zip`（外部放入的二进制）被 `git add -A` 误扫入库 → 移出跟踪（**磁盘文件保留**）+ gitignore（含 `.vasta/`）
- 新增根 `README.md`（布局/AD-1/快速开始）
- 版本单源 `_version.py`（三处字面量合一）+ pyproject 同步守卫
- 文档预期输出数字（17/14）由测试钉住；NFR-002 措辞修正（两个不同根目录，非同根重跑）
- AD-5 静态禁令扩展（perf_counter/sleep/utcnow/getenv/random 族扩全/secrets）+ vasta_storage 纳入扫描（白名单仅 sqlite_store.py）
- CI：ruff 覆盖 examples、Python 3.12/3.13 矩阵
- 契约套件：补 read_back/compensate 用例；fakes 的 compensate 返回类型修正；套件文档注明 pytest-asyncio 依赖；环境套件 `valid_action_tool` 可覆写
- ScriptedEnv.status 少括号的潜伏 bug

### 新增回归钉子（tests/test_review_fixes.py + e2e，14 个）
fail() 双路径、升级 checkpoint + resume 检出环境变化、偏差流 resume/reset 清零、env_error 终态、守卫三则、暂停不计费、超预算模型交换证据仍在、同根重跑拒绝、版本单源、文档数字。

## 挂起（defer，3 项）

1. **CI 仅 ubuntu**——Windows runner 成本与时长，Stage 3 团队化时再评估（本仓开发机为 Windows，本地全量已验证）
2. **EventEnvelope payload 浅冻结**——深冻结有性能与兼容代价；落盘即 JSON 固化，Stage 3 序列化边界统一处理
3. **AD-5 禁令的 from-import 别名绕过**——正则不可靠，改为评审约定；ast 级 lint 属工具链增强

## 驳回（dismiss，3 项）

- "事件数 16"类文档数字（已在实现时修正并被守卫钉住）
- CI 应跑 Windows（同 defer 1，不重复计）
- uv.lock 不应入库（锁定文件入库是正确实践）

## 待决策（decision_needed，1 项）

**`action.*` 事件是否在 Epic 3 前提前发最小版**：验收审计指出回放无法从事件流重建"执行了什么动作"（动作仅在 checkpoint 里留痕）。13 族含 action 族，但 action.proposed/contracted/executed 语义属 Epic 3 六段链管道。**默认建议：维持现状**，Epic 3 一次性引入完整 action 事件族（避免最小版与管道版语义分叉）；如需提前，说一声即可加最小 `action.executed`。

## 复盘说明

- 三层评审共同击中的两处（升级 checkpoint、半作用域 fail-open）都是真实缺陷，独立上下文评审的价值得到验证。
- 修复过程中发现的一个"疑似 bug"最终是**测试 fixture 自身缺陷**（SimpleEnv 决策帧缺 available_actions 导致签名合法变化）——已修 fixture；顺带确认 Supervisor 的模式键对"动作集变化的决策帧"不误报。
