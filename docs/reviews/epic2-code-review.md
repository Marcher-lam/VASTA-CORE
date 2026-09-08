# Epic 2 代码评审报告（2026-09-08）

- **评审对象**：`0c6953f..HEAD`（Story 2.1–2.3，18 文件）
- **四层评审**：Blind Hunter（21 条）/ Edge Case Hunter（18 条）/ Verification Gap（2 大项 + 2 附加）/ Acceptance Auditor（4 高 3 中 4 低），独立上下文执行
- **Triage**：去重合并后 —— **patch 24 / defer 5 / dismiss 2**
- **验证**：修复后 182 测试全绿（+25 守卫）、ruff 干净、AD-1 契约 KEPT、quickstart 实跑不变

## 已修复（patch，24 项）

### AC 违反（验收审计 4 项高全部落地）
- **search_artifacts 死链缺口**：返回前校验 blob 存在性/可达性，死链抛 `search.dead_links`（与事件侧同款）
- **哈希校验显式化**：`verify_hashes=True` 开关——检索期重算引用内容 sha256（默认存在性+可达性；全量哈希重算不适合每次检索，AC 的哈希承诺由开关+测试共同锚定）
- **verify_lineage 派生状态失真**：derived_status 三态（ok/derived_missing/derived_corrupted），派生侧坏时逐记录并入状态（不虚标 verified）；未知存储错误不再压平成"来源不可再验证"
- **crop/read_pixels/diff 输出无引用**：全部携带 provenance（类型化 EvidenceReference；diff 双出处）；provenance 参数化 limit 取多引用

### 正确性与安全
- AD-10：图像解码/裁剪/像素循环/拼接全部经 `asyncio.to_thread`；解码（89 万像素）与扫描面积上限分离
- `last_action` 并发错标：共享 `_current_action` 状态改为参数传递（交错 step 不再互相污染；reset/observe/external 路径结构性不携带）
- save_derived：源可达预检（拒登记悬空血缘）、差异重登记冲突拒绝（不静默吞 params/version）、params 显式 JSON（不再 repr 化）
- tags：键校验存查对称；同键冲突 first-wins（不跨作用域覆盖既有值）；内容级全局元数据边界显式文档化
- 检索防护：ts 必须 tz-aware（统一 UTC）、族前缀 %/_ 通配符拒绝、payload_equals 仅 JSON 标量、limit 必须为正、空白作用域拒绝、IN 参数 900 分块（SQLite 变量上限）、Box 坐标必须 int、解码错误区分（not_decodable vs decode_failed）
- events(tenant, project, ts) 索引（作用域+时间窗检索主路径）

### 与 Story 2.3 打通
- crop/diff `persist_derived=True`：输出 PNG 经 save_derived 登记血缘（transform=image.crop/image.diff，参数含 box/双 sha），需显式作用域——图像派生可回链源帧

### 测试守卫（+25）
泄漏守卫（step 外路径不携带 last_action——验证缺口层的实锤场景）、verify_hashes 双模式、artifact 死链、limit/通配符/值类型/naive ts/空白作用域拒绝、artifact 时间窗、ts+run+seq 排序、tag 存查对称与 first-wins、**带数据的迁移存活**、quickstart 端到端 `last_action=right/down` 命中（Task 7 原始形态）、derived_missing/derived_corrupted、悬空源/冲突重登记/非 JSON params 拒绝、persist_derived 回链、面积上限；修复既有测试的恒真断言与错误注释；allowlist 存在性守卫对齐当前白名单。

## 挂起（defer，5 项）

1. **tags 作用域化**（schema v4：租户私有标签表）——现值可跨作用域读（键值属内容级），Stage 3 数据治理（FR-017/018）一并重构
2. **检索分页 offset/游标**——MVP 规模 limit 足够
3. **json_extract 标签无法走索引**——容量证据出现后再做标签子表/表达式索引
4. **last_action 仅 tool 名**（args 不入维度）——Epic 3 action.* 事件族落地时统一解决
5. **side_by_side_png 大字节入 Claim**——Claim 模型（Epic 5）设计时定引用而非内嵌

## 驳回（dismiss，2 项）

- "last_action 破坏 CAS 去重"——不同动作产生不同观察证据是设计语义（动作是观察上下文），非缺陷
- "provenance 无作用域时跨租户枚举"——无作用域路径是管理面语义（与 get_artifact 一致），已在 docstring 声明；MVP 单机档无跨租户面

## 复盘

- 验证缺口层再次实锤：删掉 last_action 的 finally 清理后 157 测试全绿（缺陷带绿发布）——本次参数化重构 + 泄漏守卫双保险关闭
- 两轮评审共同模式：**AC 字面与实现的缝隙**（"哈希校验通过"谁来做、何时做）是最肥的缺陷来源；本轮以显式开关+守卫测试把语义钉死
- Bash heredoc 在长中文内容上反复截断（3 次），本轮起补丁脚本一律走 Write 工具落文件再执行
