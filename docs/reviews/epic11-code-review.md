# Epic 11 代码评审报告（2026-09-11）

- **评审对象**：Story 11.1–11.13（`bf0f14d..c184031`，13 提交、29 文件、3372 行 diff）
- **四层评审**：Blind Auditor / Edge Case Hunter / Verification Gap / Acceptance
  Auditor 并行执行；盲审 4 高/6 中/8 低全实跑（`.review-tmp/ec11_r*.py`）、
  边界猎手 40+ 项全实测（`.review-tmp/ec5_*.py`）、验证缺口 35 组删码突变
  （33 杀 / 2 存活）、验收审计含 git 历史取证与 6 轮门禁实跑
- **Triage**：合并去重后 —— **patch 24 组（高危 8 根因族）/ defer 9 / dismiss 5**
- **验收审计判定（评审时点）**：有保留通过（保留项见下「defer」——最大缩水点
  11.9 三个 AC 子句未交付且 docstring 虚陈、W-1 接线部分达成）
- **验证**：修复后 **1059 测试全绿**（评审时 1004，+55 评审锚定）、ruff 干净、
  import-linter 5 契约全 KEPT、目录守卫零漂移（AST 扫描器口径）

## 已修复（patch）

### 高危（8 根因族——多方共击或实测实锤）

- **H1 事件目录缺 7 个活事件 + 守卫假阴性**（盲审 H1+验收 11.1+边界 G-1/G-2
  三方共击，全部实测）：正则文本扫描改为 **AST 扫描**——注释/docstring 中的
  emit 文本不再假阳性、被注释掉的真实发射立即落入 extra（假阴性根治）、
  `"a.x" if … else "b.y"` 三元发射双支全捕获、`# noqa` 注释后的发射点不再漏。
  目录补 7 个活事件：`artifact.published/world_model.published`（versioning
  返回值发射面——本 Epic 曾亲手删除前者）、`artifact.shared(_revoked)`
  （sharing 三元分支）、`world_model.meta_decision`（包装发射——**AST 扫描器
  上线即抓获的新漏网**，盲审亦未发现）、`run.takeover/run.control_released/
  run.deviation_context`（9.x 遗漏——noqa 注释隔断正则的盲区，自目录建立
  起就不在册）。守卫测试新增已知活事件白名单独立断言（不依赖扫描器视野）
- **H2 private 排行榜跨租户任意读**（盲审 H2+边界 L-2 实测——榜无作用域
  绑定，校验的是「主体能否读调用方传入的作用域」而非「榜属于该作用域」）：
  `Leaderboard/LeaderboardSpec` 固化 `tenant_id/project_id`（生成即随 spec）；
  `check_leaderboard_access` 先比对榜归属与请求作用域（不符即拒）再走 RBAC。
  旧测试 `test_private_with_authorized_principal` 本身就是绕过演示——已改
  为作用域一致形态，另加跨租户拒回归
- **H3 EdgeBuffer 第二次 flush 必报假缺口**（盲审 H3 实测——连续性锚硬编码
  0，断连-恢复-再断连不可用）：锚改为 `_next_expected_seq` 随回传推进；
  回归锚定第二批帧（seq 3-4）flush 通过且零 `run.gap_detected` 假遥测
- **H4 自治升档连胜被同级评估污染 + 跳级**（盲审 H4+边界 A-4 实测——L1 上
  同级读数任意次后，单次低危读数 L1 直跳 L3）：streak 只由「读数达到高于
  当前档」的评估构成（同级不蓄势）；连胜满 `promote_streak` 只升**一级**
  （逐级推进）。旧测试 `test_promotion_needs_streak` enshrine 了跳级行为
  ——改写为逐级断言
- **D-1/A-1/R-1/T-1/L-1 NaN/inf 家族根因**（边界猎手跨模块模式①——
  `v<0`/`used>=limit`/`sum==1` 对 NaN 全失效，五模块同根因）：统一
  `math.isfinite` 入口守卫——delegation 预算值构造期拒、autonomy 权重逐项
  非负有限+键集恰为四维+阈值严格递增、risk_budget risk_weight 拒 +
  `model_copy` 后显式重验（ge=0 不再形同虚设）+ enforce 非有限 fail-closed
  降 L0、tournament 非有限指标候选判失败、leaderboard score
  `allow_inf_nan=False`
- **E-1/M5 flush 部分提交无幂等 + 并发双提交**（边界实测：中途失败重试帧
  0/1 重复入事件流；并发 flush 同帧 CAS 双提交）：逐帧提交即逐帧出队（重试
  从失败帧续传——已提交帧不重复）、`asyncio.Lock` 持锁回传；同 seq 不同
  digest 的重复缓冲即拒（E-2——前帧不可静默覆盖）
- **VG-G1 帧内容寻址零锚定**（验证缺口删码实锤：`frame_commit` 删除 +
  sha 硬编码 "stub-sha" 均存活）：`commit_frame` 校验返回 sha 必须等于提交
  体 SHA-256（存根/错位哈希即拒 `stream.cas_mismatch`）；测试锚定提交体
  字段=帧字段、sha=真实摘要、payload_digest=帧内事件体摘要
- **M3/M-1 发布/撤销零鉴权 + 撞号漂移 + 撤销后假成功**（盲审 M3+边界
  M-1/M-2/M-3/M-4/M-5 全实测）：`publish/unpublish_knowledge` 增
  `principal`（RBAC cognition write on 目标作用域——必填 fail-closed）；
  私有槽（`agent:` 前缀）拒为发布目标；同 ID 撞号——内容一致幂等 / 分歧拒
  （`knowledge.claim_collision`）/ 已 retired 诚实拒（`knowledge.target_claim_
  retired`——指引 revised ID，原「事件说已发布、投影仍 retired」根治）

### 中危（patch）

- **M1/D-2/D-3 委派预算装饰性**（盲审 M1+边界 D-1..D-5 实测）：父配额
  **缺键即拒**（原 fail-open）；`committed_budget` 累计对拍（多份委派合计
  不可透支）；`validate_action` 执行 **input_scope**（FR-050 四要素之
  「输入范围」原为纯声明——动作 `inputs` 逐键对拍契约作用域）；
  `success_criteria` 构造期校验非空字符串列表（字符串逐字符核验/整数裸
  TypeError 根治）；budget_used 非负有限；docstring 撤「CostLedger 记账」
  虚陈（真实记账由调用方接）与 `run.delegation_violation` 幽灵事件引用
- **M4/T-2 tournament 缺指标静默计 0**（盲审 M4+边界 T-2 实测——越小越好
  维度少报者必胜）：缺任一 spec 指标即该候选 failed（`missing_metrics`）；
  同名候选/重复指标项规格期拒（T-3）
- **M6/H-3 ship.py 流程缺陷**（盲审 M6+边界 H-1/H-2/H-3 实测）：
  `git add -A` → `git add -u` + 显式 `--paths`（Epic 1 复盘 git-hygiene
  禁令——工作区垃圾不入档）；`pattern.sub` 带 `count=1`（epic-11 两处同键
  只翻 development_status 区）；temp + `os.replace` 原子替换；空值键识别
  （`\S+`→`\S*`）；**pytest 计数尾行从当次输出解析入提交信息**（验收审计
  「11.13 声明 1014 实测 1008」的结构性根治——数字不再手写）
- **S-1/S-2/S-3 sharing 边界**（边界实测）：organization 面补 tenant 校验
  （两租户同名 org 互穿透拒）；acceptance 的 asset_ref 与 grant 对账（他资产
  接受不可激活本资产跨组织共享）；PRIVATE 可见性拒共享（语义矛盾）；补
  artifact 分支共享/撤销留痕测试（验收审计缝隙）
- **RA-1/L6/L7 适配器响应面**（边界实测）：http_post 非 dict → 受控
  `real_adapter.invalid_response`（裸 AttributeError 根治）；上游 error 体
  语义保留（`upstream_error`）；content 空/非字符串受控拒；
  `run_real_seed_ci` 的 seeds 与 task_results 键集对账（事件不可声称与实际
  计算不同的种子集）
- **P-1/P-5 扩展模型**（边界实测）：逐概率 ∈[0,1]（负概率静默转移质量拒）；
  CompositeModel add 目标/增量类型守卫（字符串裸 TypeError → 受控错误）；
  docstring 撤「全部走既有沙箱执行面」虚陈（见 defer #1）
- **VG-G2 autonomy 阈值边界无锚定**（验证缺口 `<`→`<=` 突变存活）：补
  0.25/0.50/0.75 恰为边界 + 边界内侧的档位断言（`<` 语义锚定）
- **G3-说明 demotion 预置 streak 穿透**（验证缺口说明项）：随 H4 重写
  （降级清零 + 同级不蓄势语义下穿透面消失），trace_adjustment 幂等分支
  保持

### 低危（patch 摘要）

- L2/A-3 autonomy 阈值严格递增校验（非单调使档位互斥失效）
- A-2 权重键集恰为四维（缺键运行期裸 KeyError、多键静默忽略）
- L8 catalog 正则贪 emit 前缀函数——AST 精确函数名匹配根治

## Defer（9——入 Epic 11 复盘行动项）

1. **11.9 三个 AC 子句未交付**（验收审计 ❌：沙箱执行接线/validation.py
   静态检查扩展/模型类型事件留痕）——孤立模块。docstring 已改口为「后续
   接线」；接线或 AC 改口留 Epic 12 规划裁决
2. **W-1 接线部分达成**（验收专项：无适配器×VastaLab 执行路径、无 ≥10
   种子门槛、CI 未并入 OfflineEvalReport 结构）——W-1 维持在册待复评，
   Stage 6 适配器 Story 补齐
3. **跨模块 enforcement 零接线**（盲审总评：`validate_action`/
   `check_shared_access`/`enforce_budget`/`assess_autonomy` 等在 agents/
   之外零调用——组件齐、组合碎，复刻 Epic 10 模式）——Stage 6 组装 Story
4. **11.7 策略引擎联动为纯映射**（FR-033 PolicyEngine 零引用）——同上
5. **11.6 未授权读取无留痕**（docstring 自认「调用方接」）——接线时补
6. **11.12 榜分与证据引用不回读对账**（score 为复制值）——证据链回读属
   消费者装配面
7. **11.13 流式与批量共存仅纸面**（无 EnvironmentAdapter 集成/混行测试）；
   `commit_frame` 直调不校验 seq 连续性（帧级 API 设计内）——接线 Story
8. **ship.py TOCTOU/并发锁/失败回滚**（边界 H-1/H-2 实测：门禁与 add 之间
   变更可入档、双 ship 并发后到者 commit 失败）——单驱动流程下风险低，
   文件锁+失败回滚留 D3 迭代
9. **L5/R-2/D-6**：accepted_orgs 自报无验证 / 层级链式校验 API /
   permissions 无上限——API 边界面统一收口

## Dismiss（5——语义选择或非缺陷）

- **L3 complete_delegation 放过 False/0**：`not in ("", [], {}, None)` 把
  False/0 视为「有值的输出」——falsy-but-real 是合法输出值（语义选择）
- **P-2 归一化容差端点浮点**：0.99/1.01 名义在 ±0.01 内因浮点误差被拒
  ——边界值口径问题，非安全面
- **P-3/P-4 因果环静默保持观测 / 空约束恒可行**：有注释的设计内行为
  （环保持观测值；空谓词列表=真空真值）
- **E-3 env 不持未提交帧**：帧级 API 设计（push→commit 由调用方编排）
- **验收「守卫三次抓漂移」**：证据支持 2 次 + 11.5 起预同步惯例——
  叙事口径修正（提交信息内），不改代码

## 验收审计保留项追踪

| # | 保留项 | 本轮处置 |
|---|---|---|
| 1 | 11.9 三 AC 子句未交付 | defer #1（docstring 已改口） |
| 2 | W-1 接线部分达成 | defer #2（waiver 维持在册） |
| 3 | 11.1 守卫盲区 | **patch H1**（AST + 白名单） |
| 4 | 11.3 input_scope 零消费 | **patch M1**（validate_action 执行） |
| 5 | 提交计数声明不可复现 | **patch M6**（计数尾行自动入提交信息） |
| 6 | 次要（11.5 事件面/11.6 留痕/11.7 联动/11.12 对账/11.13 共存/D2 点名缝） | defer #3-#7（roles docstring 已改口） |

## 锚定测试清单（+55）

- `test_catalog_guard.py`：扫描器免疫注释/docstring、三元双支捕获、包装
  发射捕获、注释掉发射落 extra、已知活事件白名单（10 条）
- `test_streaming_edge.py`：第二次 flush 锚推进、部分提交续传无重复、
  重复 seq 拒、CAS 体锚定+存根 sha 拒（+6）
- `test_autonomy.py`：同级不蓄势、不跳级、负/NaN 权重、键集、阈值单调、
  0.25/0.50/0.75 边界（+7，1 条改写）
- `test_delegation.py`：NaN 预算、父配额缺键拒、累计透支拒、input_scope
  两向、criteria 类型、负用量（+7）
- `test_memory_boundary.py`：无/异 principal 拒、attacker 撤销拦、私有槽
  目标拒、同内容幂等、内容分歧拒、撤销后重发布诚实拒（+7，存量补 principal）
- `test_sharing.py`：artifact 分支留痕×2、PRIVATE 拒、acceptance 对账、
  跨租户同名 org 拒（+5）
- `test_risk_budget.py`：负/NaN 权重拒、非有限敞口 fail-closed（+3）
- `test_tournament.py`：缺指标失败、NaN 失败、同名拒、重复指标拒（+4）
- `test_leaderboard.py`：跨租户私榜拒、作用域固化、NaN 分拒（+3，1 条改写）
- `test_real_adapter.py`：非 dict 响应×3、上游 error 体、content=None、
  seeds 对账（+4）
- `test_extended_models.py`：负概率拒、add 类型守卫（+2）
- `test_ship_script.py`：重复键只翻首处、空值键、原子写无残留、计数尾行
  解析（+4）
