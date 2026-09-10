# Epic 9 G4–G6 代码评审报告（2026-09-10）

- **评审对象**：Story 9.8–9.14（`72ba12b..9d78d7c`，7 提交、29 文件、4235 行 diff）
- **四层评审**：Blind Hunter / Edge Case Hunter / Verification Gap / Acceptance Auditor
  并行独立上下文执行；边界猎手 21 项发现全部实测复现（脚本
  `.review-tmp/ec2_*.py`），验证缺口猎手执行 28 组删码突变
  （24 杀 / 4 不杀），验收审计员另发现测试子集 flaky 与矩阵簿记误差
- **Triage**：合并去重后 —— **patch 22 组（高危 6）/ defer 8 / dismiss 3**
- **验收审计判定（评审时点）**：有保留通过（保留项：9.14 全经池未接线
  ❌、9.11 模型级重验证缺、9.12 PG 档备份缺、子集 flaky）→ 本轮修复后
  ❌ 项解除、其余 defer
- **验证**：修复后 **727 测试全绿**（评审时 705，+22 评审修复锚定）、
  ruff 全绿

## 已修复（patch）

### 高危（6，多方共击或实测复现）

- **F1/H1 seeded Run 接管 event_id 撞号**（盲审+边界实测）：seeded ID 流
  「可再生」=从头发号——接管后与已消费 ID 全量相撞（真实存储
  event_id UNIQUE 硬拒，测试用 FakeStorageAdapter 不查该约束故失真）。
  修复：接管时按流尾 seq **预烧 ID 流**（快进 last_seq+1 抽）；
  补真实 SqliteStorage 集成测试（UNIQUE 下写入成功 + event_id 全局
  唯一断言）
- **M6 seeded 时钟重启 ts 回退**（同根因）：RunContext.create 增
  clock_start——接管以流尾 ts 为基点续算（集成测试断言 ts 单调）
- **F2 默认时钟 tick 必抛 TypeError**（边界实测）：Scheduler 默认
  `datetime.now`（naive）与 next_after 的 aware 比较——未注入时钟的
  真实部署第一个 tick 即崩。修复：默认 `datetime.now(UTC)`（与
  「调度统一 UTC」口径一致）
- **F3 系统流并发写裸抛 duplicate_seq**（边界实测：8 并发落账必现）：
  sync 与 append 之间的 await 交错窗口。修复：撞号 → resync →
  **有界重试循环**（上限 8——单次重试在多写者竞争下不够）；rerun
  上抛路径保留（quickstart 检测依赖）。锚定：8 并发 CostLedger 全部
  落账、seq 连续
- **H2 Studio 跨租户泄露**（盲审）：cognition 投影/conflicts/timeline
  读端点全部无租户过滤。修复：CognitionService 按作用域 scoped
  rebuild（FakeStore 兼容回退信封过滤）+ conflicts/timeline 端点
  作用域参数 + 跨租户隔离测试（A 租户 Studio 看不到 B 租户主张）
- **H3/F5/F6 备份只拷 store.db**（盲审+边界实测）：objects/ 证据 CAS
  全丢而校验仍绿；0 字节备份「恢复成功」静默全丢。修复：备份改
  **目录形态**（store.db + objects/）+ SQLite 头魔数校验
  （ops.corrupt_backup 拒截断/垃圾备份）+ 完整性校验增加**工件可达**
  （事件引用全部回读哈希校验，IntegrityReport.missing_artifacts）
- **H4/F11 PodmanBackend 四缺陷**（盲审+边界静态实证）：payload 不传
  入（模型执行必败）/无静态 allowlist/无超时（挂死占槽）/seccomp
  语法非法 + allowlist 缺 CPython 必需调用。修复：stdin PIPE 注入
  payload + `_static_check` 前置 + `wait_for` 超时 kill 回收（async
  与 sync 双路径）+ seccomp 改 profile JSON（ERRNO 默认拒 + 白名单）
  + allowlist 补 rt_sigreturn/newfstatat/getdents64 等
- **M5 SandboxPool 未接线（验收 ❌ 项）**：「模型执行全经池」原为
  注释自述。修复：`SandboxPool.run_sync`（同步 transition 钩子）+
  `make_sandbox_pool` 装配工厂 + 包导出 + **PythonWorldModel(sandbox=
  池) 集成测试**（本机回退子进程后端语义一致）

### 中危（10）

**F8 Studio 投影 mount 固化**：CognitionService.refresh()（清空重放），
读端点与写路径前置刷新——mount 后跨实例写入可见（测试锚定）
**F9 非 ASCII token 500**：compare_digest 两侧 encode（studio 修；
  service 同型问题属 8.11 遗留记录）**F10/M3 存储型 XSS**：前端
  esc() 转义全部插值（statement/claim_ids/scope_key/run_id）
  **F4/F13 NaN/负成本**：record 校验有限非负（billing.bad_cost）；
  汇总面对历史毒化行（null）容错不崩 **M4 error_rate 分母**：
  errors/(errors+actions) + le=1.0 **M1 replayed 计数**：预算重放
  过滤 replayed=True（与运行期口径一致）**M2 调度重复注册**：
  schedule_id 全局查重（曾事件源路径双触发）**F7 cron 闰年/空扫描**：
  扫描上限 400 天→4 年（2/29 合法）+ dom×month 可行性剪枝
  （2 月 30 日构造期拒，不再 4 年空转；剪枝年域取 4 年窗口——单年
  误拒闰日是实现期自损 bug，测试抓出）**F14 影响面含终态下游**
  （报告计数不变量破坏）：闭包排除 refuted **F21 annotate/review
  类型强转**：str 类型校验（垃圾标注不再入审计流）

### 低危（patch 6）

**F12 CREATED 接管提前计费**：仅 STARTED/PAUSED 起 start()
（CREATED 接管方 start() 才计费——测试锚定）**F15 decay factor
守卫**（0,1]——confidence 不再可能出界落流 **F16 CI NaN 拒**
**F18 共享模型重复挂起**：桥接去重 **F19 Unicode 数字 cron 拒**
**F20 max_retries 上界**（le=10）

### 验证缺口补锚（+22 测试，705→727）

G2 预算**累计**多行触顶（原全单行零锚定）；G3 闭包 fixture 假锚定
（下游主张改空 scope——闭包真正承重，原 fixture 同 scope 使删闭包
仍绿）；G3 parent_breaks 注入（data JSON 层）；G3 refute_below 等值
（0.2==0.2 不推翻）；M2 滑窗 60.0s 精确滑出（原 61s 无法区分 >=/>）
+ F1 真实存储集成/并发落账/各新守卫。

## 延后（defer，8）

1. **9.11 模型级重验证**：AC「主张/模型」双对象只交付主张侧（模型侧
   是 9.14 的挂起而非重验证）——模型重验证（性质测试复跑）属后续
2. **9.12 PG 档备份**：备份/演练仅 SQLite 档（pg_dump 属团队档运维）
3. **测试子集 flaky**（验收审计发现）：G4-G6 文件与 TestClient 类组合
   选取时跨模块漂移失败（asyncio_mode=auto 与 portal 线程干扰）；
   全量套件 5/5 稳定——门禁不受影响，测试卫生修复入复盘
4. **check_budget/台账全流重放性能**（2000 事件≈18ms/次线性）——
   聚合表属 Stage 4
5. **F17 时钟回拨防护**（合成钟误用场景）
6. **L2 resolve_incident TOCTOU**（并发结案双落事件——归档幂等吸收）
7. **进程侧身份传播**（Epic 9 备注：每用户身份——现为共享 token +
   approver 字段）
8. **service.py 同型 token encode**（8.11 遗留——本 Story 只修 studio
   侧，统一修入服务化 Story）

## 驳回（dismiss，3）

1. 「annotate 不走批准流」——设计语义：旁注非判定（判定必须走
   review 批准流）；验收审计亦认可该解释
2. 「429 语义未到 HTTP 字面」——AC 措辞即「429 语义」，错误信封
   （retryable+retry_after）承载；HTTP 层映射属服务化 Story
3. 边界猎手「性能注记」（claims 列表 O(n²)/check_budget 重放）——
   MVP 规模实测证伪（1000 主张 0.07s），万级再评估

## 验收审计结论（修复后复验）

- 7/7 Story 落地；审计 ❌ 项（全经池未接线）已解除；六项保留中的
  实现类全部修复或转 defer 登记
- 架构决策：AD-5 十三族（16 新事件类型全族内）、AD-11/12/13/15
  无违例；AD-2 留痕零旁路成立
- **W-4 解除合法性确认**（链路+测试真实达成，附「opt-in 组合」与
  「provider 注入」两条保留——均为披露形态）
- 矩阵勘误：复评六 39/39 系分母未随 FR-024 转正更新——正为
  **40/40 = 100% PASS**（复评七登记；头部总表同步）
- **判定：通过（Epic 9 整体闭环——可做 Epic 复盘）**

## 模式沉淀

1. **「可再生」与「可续接」是两个需求**：seeded ID 流的可再生性
   （同种子同序列）恰恰使接管方从头发号——跨进程恢复需要的是
   游标快进（预烧），「确定性」不自动给出「可续接」
2. **测试替身要复现真实约束**：FakeStorageAdapter 不查 event_id
   UNIQUE，使接管的核心失败模式在测试面不可见——fake 的每个
   「简化」都是潜在的假绿面；关键路径补真实存储集成测试
3. **「组件已备、装配未做」是验收黑洞**：SandboxPool 三天前写了
   全套测试仍被审计判 ❌——「模型执行全经池」的承诺在装配点
   （make_sandbox_pool 进 PythonWorldModel）才兑现；AC 写「全经池」
   就必须有一个测试真的经池跑模型
4. **单次重试在多写者竞争下不够**：并发撞号重试要循环有界——
   每轮 resync 收敛竞争，固定次数上限兜底真异常
