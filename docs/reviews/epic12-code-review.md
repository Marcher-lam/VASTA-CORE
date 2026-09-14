# Epic 12 代码评审报告（2026-09-14）

- **评审对象**：Story 12.1–12.11（`1abe896..401fae8`，11 提交、37 文件、+3793/-76）
- **四层评审**：Blind Auditor / Edge Case Hunter / Verification Gap / Acceptance
  Auditor 并行执行；盲审 3 高/6 中/6 低全实跑（`.review-tmp/ec12_r*.py`）、
  边界猎手 11 模块 40+ 项全实测（`.review-tmp/ec12b_*.py`，含大段「实测
  自洽的非缺陷边界」纪律记录）、验证缺口 37 组删码突变（26 杀 / 9 真实
  存活 + 2 原理性等价——杀死率 74.3%）、验收审计含 Gates 算术核验
  （11/11 笔严格可复现——Epic 11 的计数膨胀结构性关闭）与 6 轮门禁实跑
- **Triage**：合并去重后 —— **patch 14 组（高危 5 根因族）/ defer 6 / dismiss 8**
- **验收审计判定（评审时点）**：accepted-with-reservations
- **验证**：修复后 **1219 测试全绿**（评审时 1173，+46 评审锚定）+ 5 skipped
  （第 5 个为新增 VASTA_REAL_ADAPTER 门控集成测试）、ruff 干净、
  import-linter 5 契约 KEPT、双轮全绿无复现失败

## 已修复（patch）

### 高危（5 根因族——全部实测实锤）

- **REG-1 同版本重注册洗白/锁定漂移**（盲审 H2+边界 6-1 共击，两条链实测）：
  同 `(plugin_id, version)` 重注册即拒（`registry.version_exists`）——注册表
  条目不可变；此前撤销终态可被同字节重放洗白回 active、锁定引用被同版本
  换内容漂移（锁定后拉取拿到新 permissions）。新内容走新版本号
- **REG-2 revoked 终态被 deprecate 复活**（边界 7-1 端到端实测：revoke 后
  pull 拒 → deprecate 后 pull 复活）：deprecate 对 revoked 版本拒
  （`registry.already_revoked`）；后继版本须注册且 **active**（`successor_
  not_active`）且不可自指。共同根因——投影「后到覆盖 + 无状态机约束」
- **SCAN-1 扫描门与内容零绑定**（盲审 H3+边界 8-3/8-4 两链实测：替扫与
  陈旧扫描均让恶意 egress 插件「扫描通过」进公开面）：security_scan 要求
  扫描对象**在册**且事件携带 `content_sha256`（与注册条目对拍，不符即
  违例）；`scan_passed` 比对当前条目哈希（内容漂移即失效）。组合链补：
  `deploy_edge_group` 同过扫描门（`edge.plugin_not_scanned`——未扫描/
  内容漂移不可直达边缘）
- **GRD-1 GuardState 并发丢敞口更新**（边界 2-1 实测：4 并发高危动作敞口
  恒 1.0 vs 顺序 4.0——FR-077 总量闸实质绕过）：GuardState 持 asyncio
  锁串行化整段闸门评估。附带 GRD-3（盲审 L2/边界 2-6）：拒绝路径不提交
  自治连胜/敞口（被拒动作不蓄势、不计量——此前被拒读数可自己铺平放行）；
  `inputs.operation_risk` 单一口径覆盖入参（此前审批矩阵与自治评估两个
  风险口径互不校验）
- **AUT-1 autonomy 阈值 isfinite 回归**（盲审 H1 实测：inf t2 使满风险
  Agent 升出 L0）：12.2 收口 require_finite 时误删阈值有限性检查——逐
  阈值 `require_finite`（`autonomy.bad_threshold`）恢复

### 中危（patch）

- **VER-1 版本语义族**（盲审 M1/L5+边界 8-1/8-2 共击）：共享
  `_versions.py`（parse_version 契约异常 + 右补零对齐比较——`1.0.0 ≡ 1.0`
  三问三错根治）；registry latest 数值序（`1.10.0 > 1.9.0`，此前字典序）；
  platform_version 非法形态（`1.0.0-rc1`）VastaError 拒（此前裸
  ValueError 逃逸且 discover/compatible_with 崩溃）
- **RATE-1 评分绑定**（盲审 M3+边界 9-1/9-3/9-5/9-6 共击）：被评插件须在册
  active；被引事件**写时预验分值可解析**（毒评分不再瘫痪聚合）；被引事件
  ranking/entries 候选须含该 plugin_id（他者评测不可刷分）；同引用重放即拒
  （`discovery.duplicate_rating`）；`_score_of` 非 dict 条目守卫 + 多元素
  ranking 取首位锚定；`plugin_rating` 增版本级聚合参数（plugin 级均值口径
  明示）
- **M4/GRD-2 官方接法预算腿**：`make_action_guard` 增 `budget_used_of`
  通道（此前委派预算腿在 AgentSession 接法下无参数面、永不触发）；
  `tool_category_of` 缺键受控拒（`guardrails.bad_tool_category`）
- **M5/TRC-1 租户透传**：`emit_world_model_event` 增 tenant/project 形参
  （缺省兼容），extended_tracing 三入口透传——此前租户 A 的模型留痕落进
  默认租户流
- **M6/EDGE-1 跨区回传鉴权**：`return_frames_cross_region` 增 principal
  必填走 registry write（与同模块治理标准一致）
- **L3/CI-1 attach_seed_ci 严格值**：契约字段恰齐（拒多余键）+ 全值有限数
  校验 + `model_validate` 重验（`model_copy` 绕过 pydantic——str/None/NaN
  直入报告根治）
- **验收保留项 1（check_shared_access 零入向）**：`guard_shared_asset_read`
  官方接线面（拒绝路径 `run.access_denied` 留痕——11.6 defer #5 部分清偿）
- **验收保留项 3（门控测试占位）**：`test_gated_path_wired` 恒真断言替换为
  真实 VASTA_REAL_ADAPTER 门控用例（≥10 种子端到端跑 `run_real_seed_eval`，
  未设环境 skip——第 5 个 skip 的来源）

### 低危（patch 摘要）

- L1 manifest 帧身份含清单摘要前缀（重复回传可区分）；11-3 同 seq 重复帧
  去重（同 digest 幂等/异 digest 拒）；L4 空/非数字 platform 约束构造期拒
  （两面口径一致）；3-1 巨整 OverflowError → VastaError；4-3 ci_level 前置
  校验（不跑完 10 种子才拒）；5-2 权限项空串拒；10-3 两处 key_resolver
  异常包裹（`plugin.key_unresolvable`/`evidence.key_unresolvable`）；10-4
  哈希形态校验（64 位小写十六进制）；1-1/1-2/1-4 流扫描器：字符集补下划线、
  `run_id=` 关键字形态捕获、envelope 对齐注释失实改口；L6 revocation 死变量
  删除

### 验证缺口补锚（9/9）

M01（`$` 锚定——`api/v2` 路径形态拒）、M03（`_RUN` 下划线约定）、M09（G1：
guard 入口 operation_risk NaN/负——含运行时路径经 AgentSession 拒）、M19
（`plugin.missing_resources` 可达面）、M21（G1：pull 哈希对拍+重建验签——
CAS 篡改/key_id 注入两条拒路径）、M23（依赖闭包环终止——突变体在此死循环）、
M26（satisfies 恰界相等侧）、M29（多元素 ranking 首位）、M36（多竞赛 seam
过滤）。M15（时序侧信道）以 monkeypatch 锚定说明 dismiss；M16（不可达死代码）
保留为声明式冗余防线（pydantic 约束先行）。

### 簿记核销（验收保留项 2）

Epic 11 复盘 items **22/23/24/26/27 五项已落地仍 open**——本轮经验收审计
证据核销翻 done（22 enforcement 接线=12.2+本轮 shared 面、23 流守卫=12.1、
24 11.9 裁决=1abe896+12.3、26 require_finite=12.2（6/7 抛出型+1 处文档化
非抛出豁免）、27 守卫惯例=本 Epic 7 笔同 commit 入册被守卫结构性强制）；
item-25（W-1）已于 12.10 同提交翻 done。`epic-12` 键维持 backlog 至复盘
翻转（生命周期约定）。

## Defer（6——入 Epic 12 复盘行动项）

1. **airgap localhost 白名单口径**（边界 5-3）：插件 egress 声明
   `http://localhost:8080/proxy` 零违例——10.12 为 model_base_urls 设计的
   白名单被原样套用；localhost 代理是现实外传通道。需 airgap 分面白名单
   策略（per-surface），非本轮单点修
2. **2-2 跨 Sequencer 实例并发竞态**（`event.duplicate_seq` 误拒）：
   guard 侧锁已消闸内竞态；根因在 Sequencer 系统流模式的跨实例 seq
   分配——存储层课题
3. **11-1 in-region 清单帧本体不进 CAS**：digest 锚定清单内容但接收方无
   处取被签清单复核——需 manifest 帧伴随 CAS 存档（清单 bytes 入库）
4. **4-2 judge 中途异常无留痕**：已跑种子无审计面（fail-closed 已保证零
   事件泄漏）——评测中断的进度留痕面
5. **环境偶发污染**（验收：6 轮 2 轮同测试失败、不可复现——Epic 11 同型）：
   仓库在 Desktop（OneDrive/Defender 疑似干扰）——迁仓库位置或加 flake
   遥测
6. **12.2 验收口径**：AgentSession 运行时路径测试仅角色面正反例（其余四面
   闸门组合级）——session 级四面正反例补齐；12.8 可见性 public/private 为
   约定陈述非机制字段

## Dismiss（8）

- **M15** `hmac.compare_digest`→`==`：原理性等价突变（仅时序侧信道差异）
- **M16** 空权限 post_init 分支：pydantic `min_length=1` 先拒（声明式约束
  先行——保留为冗余防线）
- **2-3** risk_weight bool/str 强转：pydantic 配置层语义（数值字段强转是
  pydantic 契约）
- **2-4** budget_used 契约外维度跳过：delegation 代码注释明示的口径
- **9-4 默认 plugin 级均值**：口径已在 docstring 明示（版本级聚合本轮以
  参数补齐，默认行为保留）
- **1-3** 流名尾连字符合法/首连字符非法：首字符字母约束的自然结果
- **1-2 部分形态**（元组解包/walrus 常量）：治理模块单名常量约定（无实际
  使用面——出现时 drift 守卫会以 extra 报警强制对齐）
- **8-5 兼容矩阵含 revoked 条目**：文档口径「已注册版本全量」（矩阵是
  事实面，compatible_with 才是决策面）

## 验收审计保留项追踪

| # | 保留项 | 本轮处置 |
|---|---|---|
| 1 | check_shared_access 零入向（12.2「六积木」实为五面） | **patch**（guard_shared_asset_read 官方面 + 拒绝留痕） |
| 2 | sprint-status 簿记滞留 | **patch**（items 22-27 核销翻 done） |
| 3 | 12.10 门控测试恒真占位 | **patch**（真实门控用例，第 5 个 skip） |
| 4 | 环境偶发污染复发 | defer #5（Desktop 仓库位） |
| 5 | require_finite 6/7 口径差 | dismiss（1 处非抛出语义文档化豁免——行为等价 fail-closed） |
| 6 | session 级四面测试 + 可见性机制 | defer #6 |

## 锚定测试清单（+46）

- `test_guardrails.py` +9：并发敞口不丢、拒路径不提交状态、单一风险口径、
  M09 双路径（NaN 入口+运行时）、官方预算通道、类别缺键、shared 读面×2
- `test_plugin_registry.py` +7：洗白两链、deprecate 复活/后继活性/自指、
  latest 数值序、M21 CAS 篡改两路径
- `test_plugin_trust.py` +5：替扫/陈旧扫描封链、未注册不可扫、M23 环终止
- `test_plugin_discovery.py` +9：跨精度/预发布/恰界版本、毒评分、他者评测、
  重放、幽灵插件、多元素 ranking、版本级聚合、空约束一致
- `test_stream_catalog_guard.py` +4：M01/M03 形态锚、关键字形态、下划线
- `test_leaderboard.py` +5：AUT-1 inf 阈值、M36 多竞赛 seam、CI 严格值×3、
  门控集成（skip）
- `test_plugin_manifest.py`/`test_edge_orchestration.py`/`test_real_eval.py`
  若干：权限空串、约束构造期拒、编组扫描门、回传鉴权/去重/清单帧身份
