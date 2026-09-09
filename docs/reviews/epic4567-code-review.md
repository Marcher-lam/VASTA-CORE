# Epic 4–7 代码评审报告（2026-09-08）

- **评审对象**：`85f32fb..1fb9466`（Story 4.1–4.4 + Epic 5（5.1–5.4）+ Epic 6（6.1–6.6）+ Epic 7（7.1–7.3），38 文件 3641 行 diff）
- **四层评审**：Blind Hunter / Edge Case Hunter / Verification Gap / Acceptance Auditor 并行独立上下文执行，合计约 60+ 条原始发现（多项含实锤复现）
- **Triage**：合并去重后 —— **patch 34 项 / defer 6 / dismiss 3**
- **验证**：修复后 **379 测试全绿**（+45 守卫/修复测试）、ruff 全绿、import-linter 2 契约 KEPT、CLI 端到端实跑（run → inspect → replay）通过

## 已修复（patch）

### A. 沙箱与安全核心（Epic 6，两项三层共击 + 一项修复期新发现）

- **受限 Python 本地执行不再挂全量 builtins**：`_run_local` 显式注入受限 builtins 集合；**修复期新实锤**——`exec(code, globals_dict, scope)` 在 globals 缺 `__builtins__` 键时会自动注入全量 builtins，测试 `test_local_exec_builtins_restricted` 抓到后改为 `{**_SAFE_BUILTINS, "__builtins__": {}}`（守卫：`iter` 等未入白名单内置 → NameError）
- **静态检查堵 from-import 绕过**：`from socket import socket` 原先不匹配 `^\s*import` 正则——补 from 形态白名单校验；禁止模式扩至 getattr/setattr/vars/globals/locals/breakpoint/input/pathlib/ctypes/importlib（反射逃逸通道）
- **PythonWorldModel 接沙箱**：原 docstring 声称"受限子进程执行"实则进程内 exec 全量 builtins、`_run()` 是 `if False else None` 死代码——现为双模式：`sandbox=SandboxExecutor(...)` 时 transition 走受限子进程（静态检查 + 资源限额 + 最小环境 + 超时墙钟）；无沙箱时受限 builtins 本地直跑（快速验证路径，文档如实标注）
- **SandboxExecutor 强化**：`run()`/`run_sync()` 前置 `_static_check`（原先子进程路径不查）；子进程环境最小化（`PYTHONIOENCODING/PYTHONHASHSEED` + 仅 Windows 透传 `SYSTEMROOT`，清除父进程凭证可达变量）；`proc.kill()` 后 `await proc.wait()`（防僵尸）；超时经可选 `emitter` 落 `system.timeout` 事件（AD-15 留痕，评审实锤缺失）
- **模型清单必填项强制**（FR-043）：`unknowns`/`coverage` 至少一项——空清单表示未做覆盖刻画，构造期拒绝

### B. 评测可复现与任务语义（Epic 7）

- **任务级播种跨进程稳定**（Verification Gap 实锤：同 seed 两次进程 net_gain 0.32 vs 0.44）：`hash(task_id)` 换 `zlib.crc32(task_id)`——子进程两跑首随机数一致（守卫测试实跑验证）
- **wind 隐藏规则落地**：原先纯装饰字段（无转移语义）——现为确定性顺风波（偶数步行 +1，受边界钳制），calm/windy 同动作序列落到不同位置
- **solve() 改真实转移上 BFS**：原 teleport 分支硬编码 4x4 路径且从不经过传送门（死代码）——现对 none/teleport/wind × 4x4/5x5 全组合可证 `run_agent(solve()) == True`（守卫参数化）
- **失败分类**（AC-07）：`TaskResult.failure_kind`（invalid_action/timeout/no_progress/wrong_end_state），`failure_breakdown` 按 kind 统计（原单一 failed 桶）
- **多种子聚合**：`run_ablation(n_seeds=N)` 逐种子运行聚合，组报告携带 `seeds_run` 与成功率标准差——单点净增益不再被当稳定结论
- **verify_config_complete 补 budget**：缺预算或非正整数原判 True（守卫：空 budget / max_actions=0 → False）

### C. 认知服务加固（Epic 5）

- **seq 分配器冲突**（Edge Case 实锤：桥接写 cognition run 后服务再写 → DuplicateEventError）：`_emit` 每次发射前从存储同步 seq/parent（与 `_bookkeeping_stub.emit_world_model_event` 全量扫描策略一致）
- **存在性校验**：support/dispute/refute/retire 对不存在主张原静默发事件（投影里造出孤儿状态）——现 `claim.not_found` 拒绝
- **终态不可迁移**：refuted/retired 主张可被 accept/support"复活"——现 `claim.terminal` 拒绝（重复 refute 同样拒绝）
- **重复 propose 拒绝**：同 claim_id 二次 propose 原静默覆盖投影——现 `claim.duplicate`（事件溯源不覆盖）
- **Claim.version**（FR-021）：状态迁移版本化（迁移即 +1，事件携带）
- **级联穿透已推翻中间节点**：原实现跳过 refuted 节点导致 A←B(已推翻)←C 漏传播——现按依赖闭包遍历（穿透 refuted、不穿透 retired、visited 防环）；守卫含"C 在 B 推翻后才提出"的时序场景与依赖环
- **冲突检测落地**：propose 路径自动检测同范围互斥主张并落 `claim.conflict_detected` 事件（带触发者）；`ConflictService.detect` 幂等（同主张集合不重复建）；默认按完整 scope 分组（原 `scope_key="statement"` 取 `scope.get("statement", statement)` 几乎永不分组）；`resolve` 落 `claim.conflict_resolved` 事件 + resolved/kept 状态 + 重复解决拒绝
- **ContextBuilder 补维度**（FR-025）：默认相关性函数目标感知（goal 与 statement 词元重合 + 状态加成）；风险分（反证计数 + 争议态）入排序键；reason 携带 `relevance=`/`risk=` 数值
- **租户参数化**：`CognitionService(store, tenant_id=..., project_id=...)`（原硬编码 t-default 不可配）

### D. 回放与存储（Epic 4）

- **HTML Replay 全量转义**（Edge Case 实锤：payload 经 `<script>` 注入可执行）：summary/type/run_id/families/契约与计划 ref 全部 `html.escape`；`_summarize` 补 `external_source` 键（外部变化定位入口，转义后可见）
- **depth 计算环护**：原递归在 parent 环上死循环、长链爆栈——改迭代式（链上探 + 锚点回填，环按 0 锚定）
- **replay_non_model_events 真过滤**：docstring 承诺跳过模型交换事件、原实现全量重放——现按 `kind=model.exchange` / 引用串含 `model.exchange` 跳过
- **复现包配置快照补全**（FR-063）：seed/policy 原缺失，还原要件不完整
- **DeviationHit.plan_ref**：补最近 plan.* 上下文标识（排障从"哪个动作偏了"到"哪个计划步偏了"）
- **RegressionTask 契约上移 protocols**（AD-1）：`vasta_protocols/regression.py`（含 `REGRESSION_FORMAT_VERSION` semver，AD-9）；storage 侧兼容再导出
- **死代码清除**：`_FAMILY_OF`（恒等映射从未被读）

### E. 规划器 / 元决策（Epic 6）

- **max_cost 生效**：`cost_fn`（默认 action["cost"] 或 1.0）累计成本超限剪枝（原字段完全不参与搜索）
- **深度边界修正**：目标判定先于深度截断——恰落在 max_depth 的目标路径不再被丢弃（守卫：max_depth=1 时 `[finish]` 可达）
- **MetaDecision.STOP 可达**：持续预测失败（≥5）且无可修模型 → STOP（原枚举永不可达）
- **元决策留痕**（FR-040，评审实锤）：`emit_meta_decision()` 落 `world_model.meta_decision` 事件（决策 + 理由 + 六信号全量）
- **`PlanningLimitExceededError` / `_run()` 死代码 / `_PYTHON_TEMPLATE` 残片**：删除

### F. CLI 与卫生

- **inspect/replay 注册顺序**（Edge Case 实锤：`python -m vastacore.cli` 直跑报 No such command）：命令定义移到 `if __name__ == "__main__"` 之前；子进程直跑 `--help` 守卫验证
- **存储句柄 finally 关闭**：inspect/replay 双命令统一 try/finally
- **run_id 路径校验**：含 `/`、`\`、`:` 拒绝（防 `../` 逃逸写 HTML）
- **runner `_last_external_source` 死状态**：删除（只写不读）
- **determinism guards PACKAGES 去重**：vasta_model_lab 原列两次
- **`os.environ` 读取入供给点**：沙箱环境构造移 `_bookkeeping_stub.sandbox_subprocess_env`（与安全墙钟同类的 AD-16 供给点，determinism 扫描不再误报）
- **AD-1 图补 COG→LAB 边**：AD-13（cognition 是桥接唯一 owner）产生的依赖边补入 spine 依赖图

### 守卫测试（+45）

- cognition 12 项（存在性/终态/重复/版本/穿透/环/seq 同步/冲突事件/解决事件/relevance-risk）
- model-lab 12 项（STOP/留痕/from-import/反射/清单必填/零重叠回放/沙箱拒绝/超时事件/沙箱接线/builtins 受限/BFS 真目标/深度边界/max_cost）
- evaluation 8 项（跨进程种子稳定/同 seed 全报告复现/全规则 solve 可达/wind 转移/teleport 传送/失败分类/多种子/配置完整性 False 分支）
- timeline 7 项（XSS 转义/环护/模型事件过滤/8 信号全覆盖/source=tool 不标外变/plan_ref/契约上移）
- CLI 6 项（命令注册/模块直跑/路径逃逸/未知 run/端到端 run→inspect→replay）

## 延后（defer，Stage 2+ 有明确去处）

1. **评测即 Run**：AgentSimulator 为可插拔执行器位的确定性模拟，未复用 RunEngine 六段链——消融数字是框架自证的相对差而非真实 Agent 净增益。Stage 2 接真实模型适配器时替换（`AgentSimulator` docstring 已如实标注）
2. **净增益统计检验**：多种子标准差已交，t 检验/置信区间留 Stage 2（需真实任务方差数据定样本量）
3. **沙箱进程级隔离强化**：MVP 子进程 + 静态检查 + 受限 builtins 不是生产边界（rootless 容器 / seccomp 属 Stage 3，AD-6 原文即如此分级）
4. **Epic 6/7 九份 Story 文档偏薄**（验收映射不完整）：代码与测试为准，文档补全随下轮文档整理
5. **conflict 级联细节**：resolve 后非保留方的批量 dispute 仍由调用方处理（API 形态已留，自动化留 Stage 3）
6. **跨包集成接线**（runtime → cognition 桥接的引擎侧自动调用）：API 均已就位且有集成测试（桥接 + seq 同步），引擎钩子自动化属 Stage 3 编排

## 驳回（dismiss）

1. "depth 计算应缓存跨调用"——投影纯函数语义（AD-11 可删除重建），缓存属存储层优化非正确性
2. "ContextBuilder 应支持向量检索相关性"——FR-025 MVP 是可追溯规则装配，学习型检索不在此范围
3. "failure_breakdown 应含逐步归因"——AC-07 要求分类计数，逐步归因需真实执行器（同 defer 1）

## 模式沉淀（供下轮评审参考）

1. **docstring 与实现漂移是 Epic 4–7 最大缺陷源**（沙箱"子进程执行"、replay"跳过模型事件"、PythonWorldModel 双形态）——承诺语义必须配套守卫测试，否则等于没有承诺
2. **两个写路径共用一个键空间必然冲突**（cognition seq ×2）——任何"唯一 owner"架构约束（AD-13）都要检查是否有第二个隐藏分配器
3. **Python 假沙箱的三个层次**都要过：静态检查（可绕过）→ restricted builtins（exec 自动注入坑）→ 子进程（环境/资源/超时）——缺一层都是假边界
4. **"恒真断言"测试比没有测试更危险**（isinstance(list)、goal 不可达的 BFS 测试）——验收审计层应把"测试是否可能失败"作为必查项
