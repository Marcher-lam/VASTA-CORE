# Epic 9 G1–G3 代码评审报告（2026-09-10）

- **评审对象**：Story 9.1–9.7（`750801c^..d5e3017`，4158 行 diff、37 文件）
- **四层评审**：Blind Hunter / Edge Case Hunter / Verification Gap / Acceptance Auditor
  并行独立上下文执行；边界猎手留有 6 组复现脚本（`.review-tmp/ec_*.py`），
  验证缺口猎手用**删码突变体验证法**（回退到旧 bug 跑全量仍绿 = 零锚定实锤）
- **Triage**：合并去重后 —— **patch 21 项（高危 9）/ defer 9 / dismiss 5**
- **验收审计判定（评审时点）**：G1–G3 整体**不通过**（4 项阻断：权限旁路、
  跨租户删除、影子对比空转、多处删码验证零锚定）→ 本轮修复后复验通过
- **验证**：修复后 **587 测试全绿**（评审时 562，+25 评审修复锚定）、
  ruff 全绿（packages/tests 范围）

## 已修复（patch）

### 高危（9，多方共击或删码实锤）

- **9.4 evidence_access 权限旁路**（盲审+验收+验证缺口 G3+边界四方共击）：
  无作用域调用落到默认 `t-default`（且 project 笔误写成 `t-default`）→
  受限证据被无作用域调用直接读走。修复：**无作用域即拒**
  （`evidence.scope_required`——AD-12 fail-closed）+ 作用域必传。
  锚定：无作用域/半截作用域双拒测试
- **9.3 request_deletion 跨租户数据破坏**（四方共击）：依赖检查按租户、
  DELETE 按全局 sha → 单租户删除毁所有租户字节。修复：**删本租户映射
  （artifact_refs/restricted）+ 全局引用计数归零后才清 artifacts 行与
  blob**；TOCTOU 同修（依赖检查与删除移入同一锁/事务——法律保留不再有
  并发窗口）。锚定：跨租户删除保留他租户可达性 / 末租户清字节 /
  他租户保留不被绕过（G5）三测试
- **9.6 compare_shadow 恒空差异**（四方共击）：两次 `version_as_of` 同参数
  取同一 latest → 影子对比恒 0 差异，灰度放行依据是假的。修复：
  `version_as_of` 增加 `version=` 参数（按版本取记录），compare_shadow
  真取两个版本 bundle。锚定：**差异非空强断言**（原测试只查键存在——
  G1 假阳性根源）+ 同版本自比 0 差异对照
- **9.6 promote 幽灵版本**（盲审+验证缺口 G6+边界）：存在性检查只验资产级
  → 幻影版本号入状态机。修复：按 `version=` 校验（未发布该版本即
  `release.version_not_published`）。锚定：v9.9.9 拒绝测试
- **9.1 Sequencer 系统流 O(n²)**（边界实测：300 事件 1.4s、900 事件 15s）：
  每次 emit 全量重扫。修复：`last_event_info` 点查快路径（sqlite/PG 各
  实现，Sequencer 兼容 awaitable）；PG 无点查面时走 `aiter_run_events`。
  锚定：50 emit 零全量重扫计数测试
- **9.1 Sequencer sync 异常吞 + PG 不可用**（盲审+验证缺口 G10+边界）：
  `except Exception: pass` 吞掉 `pg.sync_iter_in_loop`——多实例安全承诺
  无声失效。修复：只容忍端口缺失（AttributeError/NotImplementedError/
  TypeError→内存序），其余上抛；PG 补 `last_event_info` 后根本不走 sync iter
- **9.1 PG blob 组合丢作用域与实体索引**（边界实测）：`save_artifact` 组合
  形态直接 return → artifact_scope/entity_index 全不落库，AD-14 租户可达性
  与 FR-013 检索双失效。修复：组合形态字节入 blob + **PG 元数据照落**
  （占位行/作用域/实体）；纯 PG 读路径补租户可达性校验（tenant 给定时
  JOIN artifact_scope）。锚定：stub-asyncpg 三测试（组合写元数据 /
  读路径租户不可达 / 并发首用单 pool）
- **9.1 S3 head/get 异常吞**（盲审+边界实测）：head 任何异常当「不存在」
  → 瞬态故障触发全量重传；get 任何异常报 `artifact.not_found` → 限流被
  误读为「证据已删除」污染审计语义。修复：仅 404/NoSuchKey/KeyError 视为
  不存在，其余 `s3.head_failed`/`s3.get_failed` 上抛。锚定：503 不重传 /
  SlowDown≠deleted / 404 仍 not_found 三测试
- **验证缺口零锚定组（删码实锤）**：① 快道「成功才推进」——推进移回
  append 前跑全量仍 45 绿（G2）；② 事务批次引擎离场信号——置 False 跑
  5/5 仍绿（G7）；③ 影子差异非空（G1 假阳性根源，见上）。全部补真锚定
  （append 失败 last_seq 不推进+重试无洞 / 引擎离场判失败并补偿 /
  差异非空+对照）

### 中危（12）

**sequencer.py**：并发 emit 实例锁（asyncio.Lock——sync 与 append 之间
await 交错窗口不再必败一路；锚定 gather 三发 0/1/2 全成功）；快道 resume
落后撞号**自愈续接**（同步尾部后重试一次——边界实测「resume 时点过期
永久卡死」修复；**rerun 例外**：last_seq<0 撞非空流上抛不自愈——
quickstart.rerun_conflict 检测依赖，全量回归验证）；PG 契约测试死码
（导入不存在的 `FakeStorageContract`——DSN 一设即 ImportError；改
`StorageAdapterContract` 并补齐四项契约方法调用）
**pg_store.py**：`_ensure_pool` 双检锁（并发首用双 pool 泄漏）；sync iter
临时循环改**专用连接用后即关**（曾把共享 pool 绑到已关闭循环、异步路径
报废）；唯一冲突按约束名分流（`events_pkey`→DuplicateEventError、
`events_event_id_key`→event.duplicate_id——曾按英文串匹配且 event_id 冲突
误报为 seq 冲突）
**approvals.py**：approval_id 加 uuid4 尾段（同秒碰撞）；revoke 按作用域
过滤（跨租户同 id 不可误撤）+ `get_approval` 从事件流重建记录（revoke →
重建 → is_approval_valid 立即失效的闭环）；ttl_s<=0 拒（`approval.bad_ttl`）；
naive `datetime.now()` 按本地时区解释（公共 API 不再 TypeError——UTC+8
实测修正）。锚定：20 连发无碰撞 / 跨租户撤销 not_found / naive now 四测试
**transactions.py**：补偿失败**留痕**（`action.batch_step_compensation_failed`
事件 + BatchResult.compensation_failed 字段 + aborted payload——「各步
compensate 留痕」docstring 承诺兑现）；dry-run 门 fail-closed（未注册工具
拒整批、dry_run 抛异常拒不裸逃）。锚定：引擎离场判失败 / 未注册拒 /
dry_run 异常拒 / 补偿失败留痕四测试
**sqlite_store.py**：entity 索引值类型校验（`_valid_entity_value`——
None/嵌套 dict 曾 str() 字面量落库且与真实 'None' 撞键；事件侧
entity_refs 与 save_artifact entities 双修）；别名解析 SELECT 移入锁内
**release.py**：`version_as_of` version 参数化（compare_shadow/promote 共用）
**lifecycle.py**：`already_deleted` 状态可达（幂等重放与首删可区分——
打错 sha 不再误报成功）；删除同步清理本租户 restricted 孤儿行（「同内容
重存旧限制复活」消除）

### 评审修复锚定（+25 测试，562→587）

sequencer 6（点查零扫描/失败不推进/并发串行/落后自愈/rerun 上抛/持续撞上抛）、
approvals 4、transactions 4、lifecycle 3、evidence 1、release 2、
S3 错误路由 3、PG stub 3（含并发单 pool）。

## 延后（defer，9）

1. **SDK 系统流模块的 PG 兼容**（结构性）：approvals/release/lifecycle/
   evidence_access 走 sync `iter_run_events`/`search_events`/`_lock`——
   对 PostgresEventStore 分别 AttributeError/`pg.sync_iter_in_loop`/裸驱动
   异常。SQLite 档（MVP）完整；团队档接通属 G4+（epics 备注已披露范围）
2. **S3 async 接口全同步阻塞**：head/get/put 在事件循环线程直执行、
   单请求 5GB 无 multipart——MVP 小工件假设，大文件属 Stage 3
3. **S3 metadata 非 ASCII**：source/classification 中文入 S3 用户元数据
   在真实 botocore 发送层会被拒（fake 层不可见）；送真实 S3 前需 ASCII
   化或标签承载
4. **别名链/环/自指**：单跳解析语义（A→B→C 检索不到 C），无链检测；
   文档化单跳或加链检测留后续
5. **classify 坏/未来时间戳**：不可解析静默按 now → 永远 hot；未来时间戳
   负年龄——真实数据源均为 ISO 格式，容错增强属 Stage 3
6. **PG schema 版本门**：`CREATE TABLE IF NOT EXISTS` 对旧 shape 静默通过
   （sqlite 侧有 user_version 门）；PG 侧版本表属团队档运维
7. **rolled_back 无出边**：回滚版本永久死亡只能换号——若为设计需文档化
   （当前状态机字面如此，epics 已含 (+rolled_back) 表述）
8. **get_canary_percent 未知资产默认 100 / get_release_status 返回
   candidate**：未见过即默认的语义——消费方接灰度路由时再定
9. **search_approvals 空 approver=不过滤**：行为可接受但未文档化

## 驳回（dismiss，5）

1. 「rollback 不恢复 version_as_of 引用」——**设计语义**：version_as_of 是
   内容寻址的版本检索（历史不可变），激活语义在 `_get_state_sync`
   （release.rolled_back 已恢复 _active）；回滚改写版本历史违反审计流原则
2. 「expires_at 含端点（恰到期仍有效）」——设计选择，边界猎手自己标注
   「点名备查」而非缺陷
3. 「session complete 后执行 batch 返回 aborted 语义可疑」——不炸、事件
   留痕、状态正确；「complete 后拒批」属产品策略非正确性
4. 「batch_id 含冒号可伪造 step 段」——当前无解析消费方（幂等键只做
   前缀匹配），埋雷说成立但无现实路径
5. 「restrict 不存在的 sha 静默接受=预登记语义未文档化」——预登记行为
   本身合理（先限后存是合法时序），文档化即可（已入 defer 清单外的
   docstring 更新范围）

## 验收审计结论（修复后复验）

- 7/7 Story 落地；四项阻断（权限旁路/跨租户删除/影子空转/零锚定）全部
  修复且有测试锚定；删码突变体验证法复核：G1/G2/G7 突变体现在均被杀死
- AD-12 fail-closed 在 evidence_access（无作用域即拒）、transactions
  （dry-run 门）双点实码确认
- **判定：通过（G1–G3 可进入 G4 开发）**；defer 项进入 Epic 9 复盘清单

## 模式沉淀

1. **「默认作用域」是 fail-closed 的反模式**：凡权限/删除/作用域判定，
   缺省即拒——落到默认租户等于给旁路开门（9.4 与 9.3 是同一根因的两面）
2. **删码验证应纳入评审标准动作**：本轮 3 项「测试全绿但语义无锚定」
   全靠回退突变体暴露；「有测试」≠「语义被锚定」，断言要打到**行为差分**
   （差异非空/计数归零/状态区分）而非键存在
3. **组合形态要测「两侧都写了什么」**：PG+S3 组合曾只测「返回 sha 对」，
   元数据侧静默丢失——跨后端组合的验收必须断言每个后端的落库面
4. **自愈与报错的分界要在写入端定义清楚**：快道撞号三种形态（rerun/
   落后/持续撞）各归其位——自愈不是无条件的，语义检测依赖的错误路径
   （rerun_conflict）必须保留
