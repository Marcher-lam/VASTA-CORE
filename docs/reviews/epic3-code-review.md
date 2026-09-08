# Epic 3 代码评审报告（2026-09-08）

- **评审对象**：`a196f21^..HEAD`（Story 3.1–3.6，30 文件）
- **四层评审**：Blind Hunter（20 项）/ Edge Case Hunter（21 条）/ Verification Gap（5 大项，含两个实锤复现）/ Acceptance Auditor（4 高 8 中 6 低），独立上下文执行
- **Triage**：合并去重后 —— **patch 约 30 项 / defer 4 / dismiss 2**
- **验证**：修复后 285 测试全绿（+12 守卫）、ruff 干净、契约 KEPT、CLI 实跑通过

## 已修复（patch）

### 正确性与安全核心
- **恢复分类接真实证据**（三层评审共击）：`_on_deviation` 硬编码 RecoveryInput → 从最近 executed 事件取 tool_ok、扫窗口内 observation.external 判 external_change——五类分类在引擎路径可达（守卫测试：工具失败场景不再误判环境延迟）
- **默认策略 fail-open 消除**：未装配 policy_engine 时用 PolicyEngine 默认风险映射（R0-R2 allow / R3 请求批准 / R4 拒）——`approved=True` 不可自证；策略 callable 异常 → fail-closed 拒 + 事件
- **fail-closed 只读语义**（AD-12 字面）：策略不可用时低风险**写动作**拒、只读放行降级（fallback 增 read_only 参数，网关清单传入）
- **批准安全三件套**：approved=True 必须对应真实挂起请求且未被 revoked（防伪造）；approve_pending 验暂停原因（手动/升级暂停不可借此放行）+ `execute=False` 形态（撤销目标态经公共 API 可达）；revoke 防重复 + 撤销后解除挂起（cancel）+ 重入被撤销门拦截
- **超时强制**：env 与网关执行均 `asyncio.wait_for(timeout_ms/1000)`——超时 → action.failed + run.failed{safe_stop}；超时链审计 = failed 合法终态
- **网关并发与失败缓存**：asyncio.Lock + in-flight task 去重（并发同键不再双执行）；适配器异常缓存失败结果（副作用未知时防同键重执行放大）；混合键字符串化（sort_keys 不再 TypeError）
- **审计器四项语义**：新增 `failed` 合法终态（执行异常/超时/预算链不再误报 NFR-001）；`pending` 计入 all_success_paths_complete；链作用域扫描到下一条 contracted（消 [:3] 魔法窗口与跨链污染）；失败链不再虚报 incomplete

### 核验与恢复语义
- **ReadBack 双源**：after 观察 + ToolResult detail 都入比对范围——网关成功路径默认核验不再全判 deviation（守卫：EchoTool + status=approved → verification.passed；成功不烧恢复预算不触发升级）
- **观察不足 inconclusive**：读回双源全缺 → inconclusive（不再是 deviation 冒充证据）
- **unchanged 不冒充 pass**：无前后对照 → inconclusive（Stage 3 事件对照完备前不可判）；contains 非容器 → inconclusive；_dig dict 键优先于对象属性（防绑定方法泄漏）
- **默认流水线三器齐备**：invariant 默认注册
- **恢复预算**：retry 同计副作用总闸（重试是真实重执行）
- **Supervisor 成功复位**：核验 passed 喂 note_deviation(False)——偏差-成功交替不再累积升级
- **run.failed 附偏差上下文**：run.deviation_context 事件（契约 ref/核验 seq/恢复预算快照）

### 结构与卫生
- **幂等函数入 protocols**（AD-11 明文）：`vasta_protocols/idempotency.py`（canonical_args/canonical_args_hash/idempotency_key），runtime 再导出保持兼容
- **plan_step_id 绑定**：plan 提供时自动取首个 pending 步（消 default 键静默碰撞）；绑定值入 action.contracted 事件
- **before 段防护**：无观察先采集；evidence 回读失败 → result=None（核验判 inconclusive 不炸链）
- **死代码清除**：contracted._aggregate_outcomes、control._check_takeover、verifiers.DEFAULT_PIPELINE/EVIDENCE_KEYS、__all__ 私有名
- **Plan.invalidated_reason 声明化字段**（替代私有属性 hack，参与序列化）
- **pause() manual 标记**；release_control 未接管拒
- **AD-1 图 PO→CT 边**：spine 更新（vasta-policy 依赖 vasta-contracts）

### 交付补齐
- **CLI 最小交付**（3.6 Task 4）：`vasta` console script（typer）——`vasta run`（端到端首跑，实跑验证）+ `vasta control demo`（四操作语义演示）+ `vasta version`；Story 3.6 记录补注
- **sprint-status epic 状态**：epic-1/2/3 置 in-progress（与 16 个 review story 对齐）

### 测试守卫（+12）
伪造批准拒、撤销后重入拒、双重撤销拒、非批准暂停拒 approve、挂起链 NFR 不误报、网关成功不 deviation、成功不烧恢复预算、超时失败链审计 failed、偏差-成功交替不升级、无接管 release 拒、接管+R3 挂起可见、plan 绑定 step_id 入事件；既有恒真断言全部收紧（失败链 failed、fallback 只读双分支、ReadBack 双源）。

## 挂起（defer，4 项）

1. **恢复序列前段**（等待稳定窗/读回复核/回看证据前后引用）——wait_ms 与回看事件引用记录在案；完整序列编排随 Epic 4 回放（证据回看天然在那）一并落地
2. **revoke 的 tool+args 精确匹配**——当前按 tool 匹配最近 approved（同工具不同参数的批准区分需要契约 ref 入批准事件，Epic 4 事件 schema 细化时补）
3. **FR-052 "更正"操作**——PRD 列了更正，story 范围只覆盖四操作；随 3.6 追加或 Epic 5 认知资产修订一并
4. **verification.errored/inconclusive 的恢复联动**——当前仅 deviated 触发恢复（AC 语义）；errored 是否升级为 incident 随 Stage 3 监控告警体系定

## 驳回（dismiss，2 项）

- "网关路径 ok=False 仍记 action.executed"——执行了但失败是事实记录，审计通过 failed/complete 区分口径已在本次修复中理顺（executed{ok:false} + 后续核验 deviation 链路成立）
- "审计 [:3] 换成 payload tool 匹配"——采用更强方案（链作用域扫描），原建议被覆盖

## 复盘

- **验证缺口层的两个实锤复现价值极高**：批准可在接管场景下丢失（resume 后被接管门拒）、网关成功路径默认核验全判 deviation（3 次成功触发升级暂停）——都是"测试全绿但产品语义错"的形态
- **审计器语义债务集中爆发**：3.1 承诺"失败链语义在 3.4 细化"未兑现 + 3.3 pending 与 NFR-001 断言矛盾——跨 Story 的语义承诺需要守卫测试即时钉住，本次 failed/pending/作用域三项一次清偿
- 恢复预算"retry 不计副作用"是设计错觉（retry 重执行真实工具）——三层评审交叉命中后修复
