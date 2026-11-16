# VISTA 机制吸收方案（2026-11-16）

**定位**：对 [joshhhhhan/VISTA](https://github.com/joshhhhhan/VISTA)（MIT，arXiv 2610.02200）
做**源码级深读**后的机制吸收方案。VISTA 与本仓的关系见
[../VASTA-BRAINSTORM.md](../VASTA-BRAINSTORM.md)（原始调研）与
[../plan.md](../plan.md) §2 吸收方式表——本方案是那张表在「视觉复查工具」与
「上下文续接治理」两个方向上的续篇，**不是**复刻计划。

**证据基础**（2026-11-16 逐文件读，非 README 层结论）：`src/vista/core/` 下
`tools.py` / `artifacts.py` / `contracts.py` / `session.py`（恢复与视觉工具段）/
`player.py` / `timeouts.py` / `prompts/claude.md`，`backends/claude/compact_hook.py`，
`benchmarks/arc3/claude/recovery.py`（恢复提示词段），及仓库完整文件树。

**用法与决策门**：本文档**不自居已决**——是否吸收、吸收范围与开工顺序是
所有者裁决。裁决通过后按 §七 顺序实施，并在 [decision-log.md](decision-log.md)
增条目（只增不改）。标 ⚠️ 的是实施时要先补的验证。

> **状态（2026-11-16）**：所有者已下令开工，六序全批执行完毕——
> 执行留痕见 [decision-log 2026-11-16-1](decision-log.md) 与
> [story-va-1](stories/story-va-1-error-as-observation.md) 至
> [story-va-6](stories/story-va-6-micro-absorptions.md)；⚠️ 两条先决
> 已收口（pt↔px 映射走 scene.scale 活体惯例；检查点落 CAS 工件）。

---

## 一、判定总表

| # | VISTA 机制（源文件） | 判定 | VastaCore 落点 | 工程量 |
|---|---|---|---|---|
| A | 压缩检查点治理：PreCompact 拦截 + request/ready 协议 + 三态恢复（`backends/claude/compact_hook.py`、`core/session.py`） | 🔴 必吸收 | CUA 循环 + 运行时 | 3–5 天 |
| B | `inspect` / `read_pixels` 视觉复查工具对（`core/tools.py` + `core/session.py` 实现） | 🔴 必吸收 | examples/cua 新 R0 工具 | 1–2 天 |
| C | 错误即观测：`{"ok": False, "error": …}` 回喂而非抛异常（`core/session.py`） | 🟡 吸收 | examples/cua `vlm.py` 重试链 | 0.5 天 |
| D | 构造期能力-效果一致性矩阵（`core/contracts.py`） | 🟡 吸收 | vasta-protocols ToolSpec 校验 | 1 天 |
| E | 评测器状态隔离：PublicTask 与 evaluator state 分离（`core/contracts.py`） | 🟡 吸收 | vasta-eval 防作弊边界 | 1 天 |
| F | derived 证据强制声明 `derived_from`（`core/contracts.py`） | 🟡 吸收 | 观测信封 | 0.5 天 |
| G | prompt 纪律：动作前说预期、动作后报全部变化含意外（`core/prompts/claude.md`） | 🟢 微吸收 | examples/cua `loop.py` 提示词 | 0.5 天 |
| H | 工程小件：帧 0o400 只读位 / manifest `"x"` 写一次 / 原子写 0600 / `bounded_task_timeout` / 紧凑 JSON provider 中立序列化 | 🟢 择优 | vasta-storage / runtime | 1 天 |
| — | sha256 CAS 帧存储（`core/artifacts.py`） | ⚪ 已超集 | 不吸收（摘 H 两小件） | — |
| — | GUIDE.md / WORKING.md 文件记忆 | ⚪ 超集（A 例外） | 不吸收文件、吸收续接语义 | — |
| — | Codex/Claude 后端 runtime、`play`、RHAE 指标、四 benchmark 适配器 | ⛔ 不吸收 | — | — |

---

## 二、必吸收项

### A. 压缩检查点治理（VastaCore 当前真空区，优先级最高）

**VISTA 源码机制**：

1. PreCompact 钩子拦截宿主（Claude Code）的上下文压缩：checkpoint 未就绪则
   `block`，强制模型先把「完整续接状态」写入 WORKING.md（≤16KB），`ready`
   标记文件出现才放行；
2. 三态恢复，各有边界标记与投递前校验：
   - **compact recovery**：压缩前快照 guide → 恢复后校验数据未变；失败则
     `forced_termination_reason = "compact_recovery_failed"`——fail-closed；
   - **retry recovery**：设边界后拒绝 guide 在投递前被改动
     （"Retry recovery guide changed before delivery"）；
   - **runtime recovery**：运行时崩溃重启，校验 `boundary_step == step_index`
     后续跑；
3. `save_compact_checkpoint` 工具：原子写（临时文件 + chmod 0600 + replace）；
   working_memory 只存「无法从 GUIDE.md 和当前视觉恢复的状态」——最小续接集；
4. 四类恢复提示词（`arc3/claude/recovery.py`）：环境记录 JSON + 带存档
   provenance 的笔记 + 目标，`separators=(",", ":")` 紧凑序列化保证
   provider 中立。

**本仓缺口（实测证据）**：[examples/cua/loop.py:76](../examples/cua/loop.py#L76)
与 [loop.py:94](../examples/cua/loop.py#L94) 的提示词构造是 `history[-4:]`
**硬滑窗截断**——第 5 步之前的状态对模型静默消失，无任何续接状态保全。
TextEdit 文档流程（首个真实 GUI 场景，见
[vm-gui-scenario-plan](vm-gui-scenario-plan-2026-11-12.md)）任务一长必然撞上。

**吸收形态**（不做 Claude Code 钩子，本仓有自有循环）：`LoopContext`
检查点协议——上下文预算触线 → 强制 `save_checkpoint`（续接状态进**事件流**
而非 markdown；可挂 Claim 图 working 态）→ `boundary` 事件 + 恢复时校验
边界一致性，不一致 fail-closed 终止。WORKING.md 唯一未被 Claim 图覆盖的
角色是**续接载体**语义——搬语义，不搬文件。

**验收**：① 长任务（>滑窗步数）续跑后模型能复述边界前关键状态；② 边界
校验失败路径有测试（fail-closed 生效）；③ 事件流中 checkpoint 事件可回放。

### B. `inspect` / `read_pixels` 工具对

**VISTA 源码规格**：

- 帧寻址：`turn`（0–999999）+ 可选 `frame`（缺省取该 turn 最后一帧）；
- 区域：display_size（1024）归一化整数坐标矩形；裁剪后**最近邻放大回
  1024（"without smoothing"**，防插值伪造像素）；
- `inspect`：`question`（≤1024 字符）+ ≤16 个 view，按请求顺序返回
  base64 PNG；
- `read_pixels`：区域均分 rows×cols，采样每格**中心像素**；上限 64 views /
  4096 采样点；输出 RGB 符号调色板 + 每采样行紧凑字符串，且声明
  「不对齐、不变换、不比较、不解释」；
- 存档帧尺寸必须等于 `visual_size`，不符拒绝渲染。

**本仓落点**：两个 R0 只读 ToolAdapter（样例参照
[examples/cua/tools.py](../examples/cua/tools.py) 的 ClickMarkTool）。帧按
**CAS 哈希**引用（强于 VISTA 的 turn 索引——天然确定性重放兼容）；视觉
通道复用 [vlm.py](../examples/cua/vlm.py) 的多图 base64 输入。macOS 桌面
非调色板网格，`read_pixels` 的用途转为**状态取证**：目标区域像素 diff 判
「点击后屏到底变没变」。

**直接消费者**：P6 遗留调查项——点击失灵根因（AX/System Events 持续负载
退化 / Calculator 表达式态累积 / VM 特有，见
[vm-gui-scenario-plan:218](vm-gui-scenario-plan-2026-11-12.md)）——三假设
的对照实验正缺一条**不依赖 AX 的独立观测通道**。

**验收**：① 对同一 CAS 帧 + 同一区域参数，重放结果逐字节一致；② P6 对照
实验用它能区分「屏变没变」与「AX 读数偏差」。

---

## 三、对症已知失败（来自 Phase 4 基线报告）

### C. 错误即观测

VISTA 全部工具校验失败**不抛异常**，返回 `{"ok": False, "metadata":
{"error": …}}` 让模型看到错误自我纠正。本仓基线次因「VLM 坏 JSON 重试
耗尽」对症：坏 JSON 应作为观测回喂模型（带错误原文），而非静默重试到
耗尽。改 [vlm.py](../examples/cua/vlm.py) 重试链，半天。

---

## 四、契约层可摘取件（vasta-protocols / vasta-eval 迭代时带上）

### D. 构造期能力-效果一致性矩阵

`core/contracts.py` 用 frozen dataclass 在**构造期**强制
`ACTION→{ENVIRONMENT}`、`MEMORY→{NONE, MEMORY}` 等能力-副作用矩阵，
声明与效果不符构造即炸。本仓清单风险分级是平行的，「矩阵一致性构造期
校验」可加入 vasta-protocols 的 ToolSpec 端口契约测试。

### E. 评测器状态隔离

`PublicTask` 只有 task_id / objective / 冻结 context——"Evaluator state is
deliberately absent"，模型永远看不到评分器状态。VastaLab 评测防作弊应照此
加投影边界（与 PUA-harness 治理的「评分权分离」同构）。

### F. derived 证据强制 `derived_from`

派生观测必须声明源证据，非派生不得声明。CUA 的 SoM 标注图、B 项的
inspect 裁剪图都该挂血缘，闭环到观测级。

---

## 五、微吸收

### G. prompt 纪律

「动作前简述预期、动作后报告全部可见变化（含意外）」。本仓已有契约层
预期（[loop.py:109](../examples/cua/loop.py#L109) `derive_expect` /
[loop.py:125](../examples/cua/loop.py#L125) `build_contract`），补提示词
一句双保险。

### H. 工程小件（择优）

- 帧文件 chmod **0o400** 只读防篡改位（`core/artifacts.py`）；
- manifest 独占 `"x"` 模式写一次（同上）；
- 原子写三步：临时文件 + chmod 0600 + replace（`core/session.py`）；
- `bounded_task_timeout = min(单工具超时 × 最大调用数, 总上限)` 封顶公式
  （`core/timeouts.py`：上限 2,000,000s / 连接 10s / 读 120s / 重试 3 次）；
- 恢复提示紧凑 JSON 序列化（provider 中立）。

---

## 六、确认不吸收（源码证据）

- **CAS**：VISTA 为平铺 `evidence/<sha256>` + manifest.json + events.jsonl
  （追加、无哈希校验）；本仓 vasta-storage 为分桶 CAS + 事件引用 + 血缘，
  反向更强。仅摘 H 中两小件；
- **GUIDE.md/WORKING.md 文件本体**：全量替换式写入、无失效机制，Claim 图
  严格超集（plan.md §2 首版判断维持）；A 项续接语义除外；
- **runtime 与 benchmark**：`backends/`（codex+claude runner 合计 >110KB）
  与 `benchmarks/` 四套件占仓库约七成体积，与本仓 RunEngine/自有循环零
  交集，判定维持前两轮结论。

---

## 七、落地方案（决策门：待所有者通知后开工）

按证据强度排序，每项独立可停：

| 序 | 项 | 工程量 | 先决 | 验收信号 |
|---|---|---|---|---|
| ① | C 错误即观测 | 0.5 天 | 无 | 坏 JSON 回喂后任务续跑不中断（对照基线失败模式） |
| ② | B `read_pixels`（先行单件） | 0.5 天 | 无 | 同帧同区域重放逐字节一致；P6 对照实验可执行 |
| ③ | B `inspect` + history 投影 | 1–1.5 天 | ② | 多 view 请求顺序返回；CAS 哈希寻址测试绿 |
| ④ | A 压缩检查点治理 | 3–5 天 | ① | §二 A 三条验收全过 |
| ⑤ | D/E/F 契约小件 | 2–2.5 天 | 无 | vasta-protocols 契约测试扩展绿 |
| ⑥ | G/H 微吸收 | 1 天 | 无 | 提示词 diff + storage 权限位测试 |

**风险登记**：① B 的 region 坐标系要与本仓 SoM 坐标对齐（⚠️ 实施时先
标定映射）；② A 的上下文预算阈值需实测 VLM 上下文窗口后定（⚠️）；③ 全套
属 v0.1.0 后新工作，不动已交付 FR 面；MIT 许可机制移植法律面干净（保留
attribution）。

---

## 八、与在册开放问题的关联

- 名称混淆风险（plan.md §36 已登记「VastaCore 与 VISTA 名称混淆」；
  PRD §12 余项「品牌核查」）：吸收 VISTA 机制不加深该风险，裁决时可在
  decision-log 一并留痕无隶属声明；
- P6 点击失灵调查：本方案 ② 是其对照实验的前置工具。
