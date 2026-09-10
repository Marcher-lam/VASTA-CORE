# Epic 8 代码评审报告（2026-09-10）

- **评审对象**：`4ee98bf..a6ed9b9`（Story 8.1–8.13 全部 13 个，8054 行 diff、58 文件）
- **四层评审**：Blind Hunter / Edge Case Hunter / Verification Gap / Acceptance Auditor 并行独立上下文执行；边界猎手留有 6 个复现脚本（.review-tmp/repro*.py），多项发现含实测
- **Triage**：合并去重后 —— **patch 约 30 项（高危 6）/ defer 6 / dismiss 4**
- **验收审计判定**：有保留通过（13/13 落地、架构合规、无假绿证据、门槛裁决记录完整；保留项见 defer）
- **验证**：修复后 **501 测试全绿**（+8 守卫）、ruff 全绿、import-linter 2 契约 KEPT

## 已修复（patch）

### 高危（6，三方共击或实测复现）

- **轨迹导入 all-or-nothing 破产**（盲审+边界+我方实测）：`kind` 校验（isalnum 放行大写/数字开头/CJK）与信封词形规则不同步 → 非法 kind 在**写入阶段**才被信封拒绝，中途炸裸 ValidationError 且残留 run.created，run 永久毒化（重导报 run_exists）。修复：`_check_kind` 与 `EventEnvelope._EVENT_TYPE_RE` 对齐（全小写字母开头），零写入阶段拒绝（三类非法 kind 实测残留事件=0）
- **batch 预算耗尽毁整批**（边界实测）：BudgetExceededError 穿透 → 已完成任务结果全丢。修复：逐任务隔离（预算/升级只记该任务失败），整批返回
- **batch start==goal 误判失败**（边界+我方实测）：solve() 空路径 → episode 永不 ended → success=False 污染 success_rate。修复：空解路径判成功
- **offline_eval 并行同工具 args 错配**（边界实测）：「向前找最近同工具 contracted」使并行 c1/c2 的 args 全挂到 c2——expected_changes 证据不可信（本模块唯一产出）。修复：FIFO 配对 + call_id 精确匹配优先
- **derive dim=0/-n 裸崩**（边界+我方实测）：ZeroDivisionError/IndexError 绕过血缘防线。修复：dim/max_sentences/from_s<to_s/正则/媒体清单 JSON 五类参数校验（全 VastaError 包装）
- **HTTP fail-closed 守卫恒真**（验证缺口删码实锤）：`in (200, 400)` 双收 + VastaError→400 映射零回归保护（改成 500 套件仍绿）。修复：真守卫测试（注册无模板 → 精确 400 + fail-closed 文案；未注册对照 200）

### 中危（约 20）

**agent.py**：summary 工件计数从全库改**按 run 事件引用去重**（原多 run 共享 root 互污指标）；close 后 summary 给 `sdk.session_closed` 明确错误（原裸 sqlite ProgrammingError，死守卫删除）
**batch.py**：run_id 预检（批内 task_id 重复/已存在 run 全量先拒——原 DuplicateEventError 毁整批）；**驱动循环真正经 policy.generate()**（原 SolvePolicyStandIn 是死代码、「换 policy 即可」承诺未兑现——现模型在环形态落地）
**offline_eval.py**：证据形状与引擎同构（result 传解析后本体，去二次包裹）；`_conflict` 最坏判定按严重度排序（deviation>system_error>inconclusive>pass，原 dict 首值吞 system_error）；单核验器异常隔离为 system_error（原毁整份报告）；非 JSON 结果 blob 降级 None 继续
**router.py**：构造期校验 strategy 枚举/chain 名单/retries≥0（原拼错静默退化）；usage 非法形态降级估算不炸好响应（原 AttributeError 丢弃成功响应）；重试循环尊重熔断（开闸后不再打死适配器）；incident.opened 仅跃迁时发射（原重复留痕）；成本 basis 混合口径显式标注 "mixed"（原被末次调用覆盖）
**service.py**：token 比较改 hmac.compare_digest（时序侧信道）；docs/openapi 匿名面关闭；lifespan shutdown 关闭会话与 store；complete 后回收会话（原句柄无界累积）；生命周期端点异常翻译对齐（VastaError→400、其余 500，原 except Exception 全 400 掩盖服务端缺陷）；CreateRunBody.max_actions 加 ge=1（原 500 噪声）；死会话终态映射补全（created/paused/cancelled）
**probe.py**：每维探测 wait_for 超时（原挂起 provider 永久阻塞）；capabilities 属性异常 fail-closed（原裸 AttributeError）；流式中途损坏判 probe_failed（原 2 块后异常不可见仍 detected）；vision 合成载荷假阴性风险与 context 置信度单侧口径入 docstring 披露
**versioning.py**：bundle 序列化包装 versioning.bad_bundle（与策略路径对称，原裸 TypeError）
**toolproxy.py**：idempotency_key=None 不入缓存（原 None 键全适配器共享一槽，直调拿无关结果）
**scaffold.py**：检查器 dry-run 门先行且按 supports_dry_run 声明探测（声明未实现即失败——原网关会裸抛的形态漏过）；execute 失败后跳过读回（原 NameError 被吞成误导文案）；「检查会真实执行」注意事项入 docstring
**timetravel.py**：version 递增只认五类转移（与 CognitionService 投影同构，原任意 claim.* 都 +1）
**lab 门面**：补 PartialWorldModel 模块属性（拆分后属性面破坏）
**测试/文档**：恒真自比较断言删除；README 测试计数更新（387→490+）；轨迹文件形态补 CI 守卫（原零覆盖）；batch 边界三守卫；versioning「run 事件引用当时版本」补演示测试（验收保留项）

### 守卫测试（+8）

轨迹文件形态/非法 kind 零写入/坏行带序号/BOM 容忍；HTTP 真 fail-closed 400；batch 空解成功/预算隔离/重跑预检；versioning run 侧引用演示。

## 延后（defer，6）

1. **NFR-015 per-Run/项目/租户成本归集接线**：现仅路由器实例级 cost_summary（代码自称 MVP 档，诚实）；接线 Run 级预算台账属 Stage 3
2. **8.6 AC 字面偏差**：「路由决策落事件留痕」实现在 Artifact（AD-5 约束下的合理形态，story 已披露）——建议 AC 措辞对齐而非改实现
3. **8.2 story 陈述偏差**：「audit_six_segment 将导入动作如实分类为非受辖链」——audit 函数实际无 imported 过滤（会记 incomplete）；payload 标记真实。改述或补过滤留后续
4. **HTTP 服务并发面**：half_open 双试探/`_last_trace` 并发互踩/ModelRouter 无 in-flight 合并——MVP 单写者假设已在代码注释，多并发属 Stage 3
5. **真实 OpenAI 导出格式兼容**：现仅支持带 type 键的合成形态；role-based 标准 Chat Completions 日志转换器属 8.2 后续增强
6. **SM-5 运营条件**：≥3 设计伙伴每周使用 + middleware/proxy/sidecar 三形态——待伙伴信号（epics 备注承诺未违反）

## 驳回（dismiss，4）

1. 「normalization 抹除 parent 链使字节级对照发现不了因果断裂」——对照目标就是 payload 确定性，因果链另有 timeline 全覆盖守卫
2. 「onboarding-log 计时『实验』措辞」——机时为实测、人工列明示「估计」，披露充分
3. 「toolproxy 直接调用裸 TypeError」——经网关（唯一正确用法）会转 adapter_error；直调属误用
4. 「合成 call_id 理论撞名」——仅在用户省略全部 id 时发生，构造性输入

## 验收审计结论摘要

13/13 Story 符合（8.6/8.8 有已披露偏差）；AD-1/2/3/5/11 未违反、AD-12 fail-closed 实码确认；规格零篡改、story 无缩水、两个门槛裁决记录完整、A5 闭合；AC-01 翻绿证据实质充分（复现包/确定性为抽样——已在矩阵补注）。**判定：有保留通过**（保留项即 defer 1/2/3）。

## 模式沉淀

1. **「校验词表不同步」是本 Epic 最大缺陷源**（kind vs 信封、事件后缀 vs 核验词表、dry-run 声明 vs 探测条件）——两处校验规则必须共享同一常量或直接复用对方
2. **「演示成功路径」与「故障隔离」是两种代码**：前者谁都会写，后者（batch 逐任务隔离、verifier 异常隔离、评估遇坏 blob 降级）是本轮修复的主体——批处理类 API 的验收标准应包含「第 N 个元素失败时前 N-1 个仍在」
3. **死代码承诺比缺代码更危险**：SolvePolicyStandIn 案例中接口存在但从未被调——「可替换性」承诺必须有「真的调了这条路」的测试
