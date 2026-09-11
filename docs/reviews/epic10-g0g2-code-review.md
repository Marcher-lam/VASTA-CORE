# Epic 10 G0–G2 代码评审报告（2026-09-11）

- **评审对象**：Story 10.1–10.7（`5d056df..9e1ee92`，7 提交、66 文件、3533 行 diff）
- **四层评审**：Blind Hunter / Edge Case Hunter / Verification Gap / Acceptance Auditor
  并行执行；边界猎手 21 项发现全实测（`.review-tmp/ec3_*.py`）、盲审 12 项全实跑、
  验证缺口 22 组删码突变（16 杀 / 6 不杀）、验收审计含提交声明核实
- **Triage**：合并去重后 —— **patch 21 组（高危 7）/ defer 5 / dismiss 0**
- **验收审计判定（评审时点）**：有保留通过（阻断：AD-1 层契约 BROKEN——
  10.4 引入且 10.4/10.7 提交的「5 契约 KEPT」声明失实）→ 本轮修复后复验通过
- **验证**：修复后 **808 测试全绿**（评审时 788，+20 评审锚定）、ruff 干净、
  **import-linter 5 契约全 KEPT**（实跑复核）、盲审观测的 flaky 簇 5 次复跑稳定

## 已修复（patch）

### 高危（7，多方共击或删码实锤）

- **F1/H1 Schema pattern 族位置反**（盲审+边界共击，边界实测 72/72 合法事件
  被拒、倒置形态被收）：改为族在首位 `^(族)(\.[a-z][a-z0-9_]*)+$` 对齐运行时
  语义；测试重写为**目录全量对拍**（72 类型逐一 match + 4 倒置形态拒）
- **F2 promote(to="revoked") 零复核吊销**（盲审实测）：promote 收紧为灰度链
  ——suspended/retired/revoked 一律拒并指向专用函数（复核门/级联在彼处）；
  锚定：三目标拒 + approvals 流零事件
- **F3/M9/AD-1 层契约 BROKEN**（三方共击）：告警原语（AlertRule/Alert/
  MetricsSnapshot/evaluate_alerts）下沉 `governance/alerting.py`、事故原语
  （declare/resolve/archive/IncidentRecord）下沉 `governance/incidents.py`
  ——incident 本就是治理语义；ops.py 头部 re-export 后向兼容（消费者零改动）；
  drift 改同包导入；**5 契约实跑全 KEPT**
- **F4/M1/M2/M3/G1(c) release 状态重放重写**（盲审两场景实测+验证缺口删码
  实锤「终态弹出删除后 788 全绿」）：放弃栈式 active_history（suspend→resume
  同版本重复压栈、多次终态只弹一次——_active 指向 revoked、rollback 自回滚
  且抹掉吊销终态）→ **去重活跃序**重放（进入 active 入列、离开任意位置移除）；
  rollback 复用同源重放 + 终态/挂起目标防护；resume 增 active_conflict 守卫
  （他版本服务中拒——promote 灰度替换是设计内让位）。六锚定测试
- **H3 sequencer 空流首写竞态**（边界确定性复现）：rerun 启发式（last_seq<0
  撞号上抛）把「同步时对手未提交」误判为重跑，短路有界重试——删该例外统一
  resync+重试；**rerun 检测移交 quickstart 显式预检**（流非空即拒——语义更准）
- **F5/H2 审计导出 naive 窗裸 TypeError**（盲审+边界实测）：查询侧按 UTC
  归一（事件 ts 恒 aware——naive 窗是调用方最自然形态）；锚定测试
- **F9 cognition._rebuild 静默吞异常**（盲审 flaky 根因嫌疑）：兜底收窄为
  TypeError（端口兼容）——存储故障 fail-loud；盲审观测的 claim.version 归 1
  簇 5 次复跑全绿

### 中危（10）

**M4/F6 include_runs 死旗**：实装（非系统流名的 run 直查收集——开/关双态
锚定）**M5 幻影模型漂移**：run_drift_check 加 version_as_of 预检（不留任何
治理事件）**M6 evaluator 异常断头**：按重验证失败继续链路（incident 照发
——append-only 语义下重复 measured 可接受，缺 incident 不可接受）**M7 narrow
收到空 scope**：拒（语义是扩大到全域 + 静默退出冲突互斥——撤回范围走
retire）**F7 examples 旧路径**：from_zero.py 改顶层导入（10.1 遗留——模块
路径面无守卫的实证）**F10 告警死算 + 伪 run id**：告警结果并入
model_drift_measured payload（可观测——验证缺口 G2(d) 同修：原整段可删仍
全绿）；declare_incident 增 subject 参数（非 Run 治理对象不伪装 run id）
**F11 审计面漏 evaluation 流**：漂移/重验证留痕入企业审计导出
**L1/L2/L3/L4/L6 顺手修**：narrow 非 str 值受控错误码 / revise no-op 拒 /
register 无点分拒 / 布尔 schema 防御 / migrate None 版本净拒

### 验证缺口补锚（+20 测试，788→808）

G1(c) 终态弹出（suspend→resume→revoke 后 _active 不引用——删码实锤项）；
G2(c) billing 精确匹配（gridx 前缀反例）/ G2(d) 告警入事件 payload；
G3 三通道阈值等值 / 审计窗等值端点 / BFS 迁移环终止；F1-F5/F2/M1-M6 全部
高危中危各自锚定；恒真死断言（`or True`）随 F1 测试重写消灭。

## 延后（defer，5）

1. **M8 子包化无 shim + 版本未 bump**：下游 `import vastacore.release` 断
   ——deprecation shim 或 minor bump 属**发布策略**（10.1 顶层符号面已兼容
   一个 Stage 的承诺仍成立；模块路径面从未承诺）——Stage 4 末统一版本策略
2. **F8 release 全链租户盲**：复核落 t-default、registry 跨租户混流——
   挂 **10.8 RBAC**（线程化 tenant/身份本就是该 Story 核心，统一改一次）
3. **F12 cognition 重放侧无校验**（纵深防御——写入侧守卫完整）
4. **L5 validate_stream_versions 对 dict 事件忽略**
5. **L7-L9 低危组**：escape 截断展示瑕疵（无注入面）/ run 撞系统流名
   （预存在设计面）/ 复核门孤儿批准窗口（append-only 审计真实）

## 验收审计结论（修复后复验）

- 阻断项（AD-1 BROKEN）已修——**5 契约实跑全 KEPT**；10.4/10.7 的失实
  「KEPT」声明由本报告+提交信息勘误（根因：当时门禁输出被截断误读）
- 7/7 Story AC 实质达成；W-3 解除合法性维持（审计复核通过）；零行为变更
  声明（10.1）经逐行核验属实
- 保留转 defer：10.3「路由失效」半面（级联对象=计划已交付、路由未接——
  与 F8 同挂 10.8 统一）；10.4 默认 evaluator 为 DSL 结构校验（lab 回放
  注入形态，docstring 已披露）
- **判定：通过（G0-G2 可进入 G3 开发）**

## 模式沉淀

1. **「构造性自检」是验证缺口的温床**：告警联动原实现为无副作用死算+
   构造性 assert——删码验证证明整段可删而全绿。凡「触发即 X」的声明，
   X 必须落在事件流或可观测出口上
2. **启发式守卫会误伤正交场景**：rerun 检测靠「last_seq<0 撞号」推断意图，
  把并发首写竞态误判为重跑——意图检测应显式化（预检），而非从内部状态
  猜测调用方语义
3. **栈式重放对「离开-再进入」不幂等**：active 历史栈假设版本单向行进，
  suspend/resume 打破假设后全链路（_active/rollback/状态查询）连锁出错
  ——去重活跃序（进入/离开对称）是更稳的重放不变量
4. **提交声明要与门禁同跑**：10.4/10.7 的「KEPT」失实源于门禁输出被截断
  只看末行——提交信息里的每条声明应从当次完整输出复制，不凭上一次记忆
