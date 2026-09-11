# Epic 10 G3–G5 代码评审报告（2026-09-11）

- **评审对象**：Story 10.8–10.13（`6549529..b27479d`，6 提交、20 文件、3387 行 diff）
- **四层评审**：Blind Hunter / Edge Case Hunter / Verification Gap / Acceptance Auditor
  并行执行；盲审 16 项全实跑（`rv*.py`）、边界 23 项全实测（`ec4_*.py`）、验证缺口
  26 组删码突变（19 杀 / 7 不杀）、验收审计含声明逐条核实与组合缝实跑
- **Triage**：合并去重后 —— **patch 24 组（高危 4）/ defer 4 / dismiss 2**
- **验收审计判定（评审时点）**：有保留通过——3 项阻断级（ruff 红灯 +
  2 实测缺陷）+ 声明失实 2 处 → 本轮修复后复验通过
- **验证**：修复后 **894 测试全绿**（评审时 878，+16 评审锚定）、ruff 干净、
  import-linter 5 契约 KEPT

## 已修复（patch）

### 高危（4，多方共击或实测复现）

- **H-1/F1/审计阻断③ OIDC×RBAC 装配缝**（三方共击，实跑 500）：`require_role`
  同步调用 `resolver(token)` 不 await——OIDC `as_resolver` 是协程函数 →
  `AttributeError` → 全端点 500。两个 Story 各自测试全绿但**零组合测试**。
  修复：`inspect.isawaitable` 统一兼容同步/异步 resolver；组合测试三锚定
  （合法 token 200 / viewer 写 403 / 畸形 token 401 非 500）
- **H-2/F3/审计阻断② revoke 作用域漏传**（三方共击，实测双吊销）：
  `revoke_release` 内唯一漏传 tenant 的状态重建——非默认租户终态守卫完全
  绕过（已 revoked 可再 revoke + from 错记）。修复：补透传 + 跨租户
  不可逆锚定
- **F2 并发拒绝留痕丢失**（边界实测 17/20）：sequencer 空流首写撞号被
  rerun 例外（`_last_seq<0` 上抛）误伤——安全审计面并发下丢 15% 且静默。
  修复：rerun 例外删除（统一 resync+有界重试；rerun 检测本就由 quickstart
  显式预检承担——G0-G2 H3 修复的收尾）
- **M-4/F4/验证G2①/审计链式摘要载荷盲区**（三方共击，实测篡改不可见）：
  摘要只哈希五个表头字段——payload/parent/tenant 篡改后 `chain_sha256_tail`
  不变，「不可篡改声明」对最要命的篡改面（角色/金额/审批人）失明。
  修复：全信封（`model_dump(mode="json")`）入链 + 篡改检测锚定

### 阻断级（验收审计）

- **ruff 5 errors**（billing `Any` 未导入×3 + 死占位 + 测试死变量）：
  10.13 提交声称「ruff 干净」失实——G0-G2 模式沉淀 #4 重演（提交声明
  与门禁未同跑）。修复 + 报告勘误
- 其余两阻断即 H-1/H-2

### 中危（11）

**M-1/F10 账单版本读-写竞态**：同周期并发 `generate_bill` 双 v1——按
周期键 `asyncio.Lock` 串行 + 并发版本唯一锚定 **F11 label 日期粒度撞
id**：label 升到秒级 **F18 倒置窗拒**（`model_post_init` 校验）
**M-2/审计应修④ service RBAC 只接 3/9 端点**：六端点补挂
（evidence/ops 依赖从死代码变实挂）+ **service 面集成测试**
（共享 token 全端点 401 / viewer 403——G2④ 锚定）**M-3/F13 SCIM
撤权失效**：移出全部约定组 → `run.role_revoked` 回收（重放面同步
识别）+ 锚定 **F12 SCIM 分页**：totalResults 超页 startIndex 续拉
（裸 URL 先行——单页部署零负担）**F20 组名大小写**不敏感
**M-6/F5/F6 OIDC 容错收口**：畸形 header/payload（数组/null）→
受控 401；aud 标量不再裸 TypeError；JWKS 非 dict 元素容错；exp
NaN/inf 拒（L-5）**M-7/F14 canary/compare_shadow 租户线程化**：
set/get/compare 全补参数 + 跨租户隔离锚定 **M-5/F8 key=value DSN
密码泄漏**进 airgap 报告：password/user 键掩码 **F9 无 scheme URL
误判本地**（fail-open）：补 scheme 占位再解析

### 低危（9）

F7 related_runs 非序列容错（单事件曾崩整个查询）/ F15 多重 region
标记全查（首匹配曾可顺序操纵）/ F16 redact 非 str 键 + token 子串
全词匹配（next_page_token 不误伤）/ L-1 access_denied 资源取
payload.resource / L-3 retention as-of now 透传 / L-4 _active_holds
包锁（callee 契约）/ F19 负预算容错 / L-7 studio 注释去重 /
schema_registry 目录补录 8 新事件（role_assigned/revoked、
access_denied、identity_asserted、scim_synced、secret_ref_configured、
bill_generated、retention_configured——10.7 开放契约对 G3-G5 陈旧的
漂移修复）

### 评审锚定（+16 测试，878→894）

OIDC×RBAC 组合三态 / revoke 跨租户不可逆 / canary 隔离 / 链式摘要
篡改检测 / 并发账单版本唯一 / 倒置窗拒 / 周期右开边界（end 时刻
记录不入账）/ 负预算 / SCIM 撤权 / airgap 双修复 / redact 全词 /
多重 region / service 全端点 RBAC。

## 延后（defer，4）

1. **10.8「每操作鉴权」的完整语义**：本轮已补六端点（9/9 数据端点
   全接），但 `token` 形参在 RBAC 模式下仍必填（401 层双保险）——
   移除共享 token 通道属破坏性变更，随 10.9 真实 IdP 落地一并决策
2. **C4 腿 2 的 PG 演练执行证据**：`pg_recovery_drill` 代码就绪但无
   VASTA_PG_DSN 门控执行测试（需真实 PG 环境）；命令构造纯函数已有
   锚定——**re-defer 登记**（原「C4 全项解除」声明对演练半句证据
   不足，本报告勘误）
3. **`_retention_age` 存储端口抽象**：SQLite 专属直查——PG 档保留
   策略面（retention_due/disposal_drill）暂不可用；airgap 与驻留
   校验（路径面）不受影响
4. **审计主体/资源长度上限**（F23）+ SCIM displayName 大小写警示
   面（F20 行为已修、告警未做）

## 驳回（dismiss，2）

1. **studio 冒名检查排序**（L-7 附注）——同请求既缺参数又冒名时
   返回 400 而非 403：两者都是拒绝，信息优先级非安全缺陷
2. **单模型 100% 成本无 top-cost 建议**（F19 附注）——`len(by_model)>1`
   门是有意的「有替代空间」语义（单模型无替代可评），行为可辩护

## 验收审计结论（修复后复验）

- 三项阻断全部闭合：ruff 全绿、装配缝组合测试锚定、revoke 作用域
  补齐——**894 全绿 + 5 契约 KEPT 实跑复核**
- 声明勘误三处入本报告：10.13「ruff 干净」失实、10.8「revoke 全链
  透传」不准确（本轮补齐）、10.11「C4 全项解除」对 PG 演练半句证据
  不足（re-defer）
- **判定：通过（Epic 10 全 13 Story 可收口——进入复盘）**

## 模式沉淀

1. **「组件齐、组合碎」是分 Story 交付的系统性风险**：OIDC 验证器与
   RBAC 工厂各自测试充分，官方接法一拼就 500——跨 Story 的装配缝
   必须有组合测试（本模式第二次出现，第一次是 G1-G3 的 PG+S3 组合）
2. **声明的保质期**：提交信息里的门禁结论必须当次全跑得出——「上
   一次绿了这次应该也绿」在快节奏三连提交（10.11-10.13）中两次
   失实；建议提交脚本化（pytest+ruff+lint-imports 一键串联）
3. **安全审计链的完整性是数量承诺**：「拒绝都留痕」在并发下丢 15%
   等于没承诺——审计写路径的并发语义（重试/幂等）要同业务写路径
   一个标准
4. **摘要哈希的字段面 = 声明的边界**：说「不可篡改」就要把全部可变
   字段纳入链——表头五字段防不了改 payload，安全声明的粒度要用
   篡改测试钉住而非 docstring 自述
