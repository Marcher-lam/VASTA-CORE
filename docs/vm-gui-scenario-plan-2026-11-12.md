# VM × 首个 GUI 场景：开工文档（2026-11-12）

**定位**：用本机 tart macOS VM（`vasta-ci-macos`）承接三件事——

1. **关闭 PRD 开放问题 3**：「首个真实 GUI 场景——需"有历史失败、可读回、非安全关键的后台流程"，Stage 0 选定」（[prd.md §12-3](prds/prd-VastaCore-2026-09-08/prd.md)）
2. **Developer Preview 的"可给别人看"**：一次真实 GUI run 的可复现演示面
3. **把 W-1 确立的 ≥10 种子评测标准落到 GUI 路径**（注意：W-1 本身已于 2026-11-06 解除，见下——此目标不是重开旧门，是把标准施加到新路径）

**用法**：新会话从本文档开工。标 ✅ 的事实均在本机实测（2026-11-11/12），标 ⚠️ 的是开工时要先补的验证。文档不自居已决：场景选定是所有者裁决（决策门），本文给候选与建议。

---

## 一、三个目标的验收口径

### 目标 1：关闭 PRD §12-3

- 场景须同时满足三判据：**有历史失败**（有记录的失败轨迹可回看）、**可读回**（动作效果可确定性读回核验）、**非安全关键**（VM 内天然成立——坏了就删克隆）。
- 注意措辞是「**后台流程**」：纯玩具（计算器算术）只能当基线，不能当"真实场景"本体；要选有后台流程形态的（文档处理 / 文件整理一类，见 §五 Phase 3 候选表）。
- 验收 = 场景跑通 + 三判据逐条有证据 + [decision-log.md](decision-log.md) 增条目（只增不改）+ PRD §12 更新。

### 目标 2：Developer Preview 演示面

- 蓝图 Stage 2 的完整进入门（3 团队每周使用、SM-5）**不在本计划内**；本计划交付的是可给别人看的演示资产。
- 验收 = 三件套：① VM 里选定场景的一次完整 run（六段链全绿）；② 该 run 的自包含 HTML 回放（⚠️ 待验证 [examples/cua](../../examples/cua/README.md) 的 run 能否直接喂 4.3 回放生成器——CUA 声称零侵入走平台公共 API，理论上兼容）；③ 一段录屏或现场脚本。
- 演示叙事建议以**安全面**为主打（仓库已有实证）：「最差一轮 25 次错误定位被闸门全部拦截、零误点击；已执行 7 步全部核验通过；幻觉 agent 被 Supervisor 自动熔断（run 01a1ae63）」——卖点是"拦得住"，不是"成功率高"。

### 目标 3：≥10 种子评测（GUI 路径）

- 先更正一个口径：**W-1（真实模型适配器）已解除**——decision-log 2026-11-06-2：本地 qwen3.8-27b-mlx 经平台管线 5 任务 × 10 种子全对，CI [1.0,1.0]@95% 入 `OfflineEvalReport.seed_ci`，证据 [reviews/w1-recheck-2026-11-06.md](reviews/w1-recheck-2026-11-06.md)。本文目标是把同一标准施加到 GUI 路径。
- 机制全在库里，直接复用：[real_eval.py](../../packages/vastacore-sdk/src/vastacore/agents/real_eval.py)（`W1_MIN_SEEDS=10` 强制、逐种子成功率、`evaluation.real_seed_ci` 留痕、中断时 `evaluation.eval_interrupted` 进度留痕）；CI 数学用 9.11 契约 `seed_confidence_interval`。
- 验收 = 10 种子 × 任务集，每种子一次**从干净环境起跑**的完整 pass，成功率集 → CI@95% 并入 `cua.eval.report` 结构，全程事件留痕。
- **必须处理的种子独立性陷阱**（⚠️ 开工确认）：
  - `vlm.py` 有**跨 run 响应缓存**（README P2-A：「前 3 步 0.0s 命中」）——不关或不用 seed 加盐，10 个种子会回放同一份答案，CI 无效；
  - `auto`/`memory` 模式下 Claim 记忆跨任务累积——每种子的记忆策略要么固定（fresh clone = 空记忆起步，属被测行为），要么分模式各评一轮，开工时定死并写进报告。

---

## 二、为什么是 VM（仓库自己记录在案的痛点）

CUA README「P5 诚实口径（2026-11-06 实测）」原文：eval 全链路可跑、报告可出，**但当日成功率数字不可用**，两个环境级干扰——① 计算器偏好被清空后布局进入漂移态、标定不稳；② 模型长跑后 thinking 失控。结论句：「**稳定环境**（重启计算器偏好归位 + lms 重载）后重跑即得干净基线」。

23 条坑位表里，环境不可控正是反复出现的根因：#4 应用状态跨重启恢复、#6 活桌面焦点争抢（用户在用微信打断标定）、#18 defaults 漂移「治侧栏的药比病更毒」。**真机给不了"稳定环境"，VM 给得了**：`tart clone` 是 APFS 写时复制（秒级），每次评测从同一镜像起跑，环境差异被彻底钉死；同时动作被封在 VM 里（非安全关键成立）、跑批时宿主机照常使用（无人值守成立）。这三件事容器替代不了（没有 macOS 桌面）、真机做不到（不安全、不可复现、占机器）。

---

## 三、资产盘点（已验证 ✅）

### 宿主机

| 项 | 状态 |
|---|---|
| tart 2.41.1 | ✅ `~/.homebrew/bin/tart`（GitHub Releases 直装；本机 brew 是 USTC 镜像 fork，装不了 tart） |
| VM | ✅ `vasta-ci-macos`：macOS 26.6.2 (25G83) arm64，4 核 / 8GB / 50GB 盘（余约 14GB），图形会话 admin 自动登录，运行中 |
| 连接 | ✅ `ssh admin@$(tart ip vasta-ci-macos)` 免密（宿主机公钥已装）；密码默认 `admin`（建议 Phase 0 改掉）；sudo 免密；屏幕共享 `open vnc://admin@<ip>`（:5900 开放） |
| 本地 registry | ✅ Docker 容器 `vasta-registry`，`127.0.0.1:5055/vasta/macos-tahoe:latest`（需 Docker Desktop 在跑）；镜像分层在 `~/.vasta-oci-mirror/`（22GB，**用户已裁决暂不回收**） |
| 重建 VM | ✅ `tart clone --insecure localhost:5055/vasta/macos-tahoe:latest <新名>`（本地回环，数分钟） |
| CI 对齐 | ✅ `scripts/ci_local.sh`（amd64 容器三道门禁，与 CI 一致）；日常验证用它，不是 VM |

### VM 内

| 项 | 状态 |
|---|---|
| 工具链 | ✅ `/usr/local/bin/uv` 0.12.5；Python 3.13.15 独立构建于 `~/.local/share/uv/python/cpython-3.13-macos-aarch64-none` |
| 仓库 | ✅ `~/VastaCore`（HEAD `3762599`，git archive 同步）；uv 缓存热，`uv sync --all-packages --frozen` 约 3 秒 |
| 门禁 | ✅ 三道全绿（1318 passed + 7 skipped，macOS 口径；7 个 skip 是 darwin 平台差异，与本计划无关） |
| CUA 依赖 | ✅ `screencapture` / `osascript` / `open` / `pbcopy` 系统自带；Pillow 在锁内；Calculator、TextEdit 在 |

### CUA 原型现状（[README](../../examples/cua/README.md)，全部真机实测）

P0–P4 已交付全绿（grounding 11/11、计划驱动 5/5、VLM 自主闭环、R3 人在环、逐字节回放一致、UI 记忆三相）；P5 guardrails+任务集 eval **代码全交付、真机数字不可用（环境漂移，见 §二）**；安全面数字有效（见目标 2）。任务集 `tasks/tasks.jsonl` 现有 6 条计算器任务；eval 指标：成功率/步数/VLM 决策/核验/闸拦/熔断/耗时，报告入库 `source=cua.eval.report`。

### 阻塞点（✅ 已实测定位）

- `screencapture`（SSH 发起）→ `could not create image from display`
- `osascript` → System Events → AppleEvent 超时（-1712，授权框无人点）

根因：TCC 隐私权限（屏幕录制 / 辅助功能 / 自动化）未授予，且 SSH 启动的进程不在图形会话内。**解法见 Phase 0**。

---

## 四、执行计划

### Phase 0：VM 权限与基线适配（一次性，含人工 GUI 步骤）

1. `tart ip` 取 IP → `open vnc://admin@<ip>` 进屏幕共享。
2. VM 内系统设置 → 隐私与安全性：**屏幕录制**加 Terminal；**辅助功能**加 Terminal；首次 `osascript` 弹**自动化**授权时允许。
3. 顺手改掉 admin 默认密码（系统设置 → 用户与群组），并更新本文档记录。
4. 之后的 agent 一律从 **VM 内的 Terminal.app** 启动（TCC 归因干净）；SSH 只用于文件同步与查询。
5. ⚠️ 确认并记录：VM 系统语言（若为英文，坑位 #2 的中文数字解析在 verifiers.py 需加英文分支——主机是中文系统才触发中文语音渲染）与显示分辨率/缩放（坑位 #7 的 scale 是运行时实测的，理论上自适应）。
6. 授权全部就绪后打金像快照：`tart clone vasta-ci-macos vasta-golden`（TCC 库随盘克隆，以后每种字/每次演示从金像起跑，秒级）。

**验收**：VM Terminal 内 `screencapture -x /tmp/t.png` 出非空图；`osascript -e 'tell app "System Events" to count processes'` 返回数字；金像 VM 存在。

### Phase 1：冒烟——计划驱动任务（无需 VLM）

```bash
# 宿主机同步最新代码
cd ~/Desktop/VastaCore && IP=$(~/.homebrew/bin/tart ip vasta-ci-macos)
ssh admin@$IP 'rm -rf ~/VastaCore && mkdir -p ~/VastaCore'
git archive HEAD | ssh admin@$IP 'tar -x -C ~/VastaCore'
ssh admin@$IP 'export PATH=/usr/local/bin:$PATH; cd ~/VastaCore && uv sync --all-packages --frozen'
# VM 内 Terminal（经屏幕共享）：uv run python -m examples.cua.probe_grounding && uv run python -m examples.cua.run_task
```

- 预期工作：macOS 26.6 的计算器 AX 树/行为与主机（27，坑位表即按 27 写）必有差异，标定（calib.py）大概率要跑新标定；所有差异**记入 README 新坑位条目**（那表是原型最值钱的部分）。
- 已就地修正（2026-11-12）：probe_grounding 依赖 VLM（README 前置），归入 Phase 2；Phase 1 只跑无需 VLM 的 run_task。**验收 = run_task 六段链 complete、核验 passed、首偏差=无（对齐 README P1 口径）**。

### Phase 2：VLM 接线

- LM Studio（宿主机）开启 Serve on Local Network；VM 侧 `CUA_BASE_URL=http://192.168.64.1:1234/v1`（⚠️ tart NAT 网关地址待实测确认；tart 默认网段 192.168.64.0/24）。
- 冒烟 `uv run python -m examples.cua.loop`（P2-A 口径：5 步全对 + AX 独立核验）。
- 备选：模型用 W-1 同款 `qwen3.8-27b-mlx`（已证可过 10 种子门），CUA 默认 `qwen3.5-9b-mlx`（坑位 #8/#23 的 thinking 问题已对策）。

### Phase 3：场景选定（关 §12-3 的实质动作——所有者裁决）

候选与三判据对照（建议，不代决）：

| 候选 | 历史失败 | 可读回 | 非安全关键 | 备注 |
|---|---|---|---|---|
| A. TextEdit 文档流程（新建→录入→存盘→读回） | ✅ 坑位 13–17（IME/键码/rtf/对话框），P2-B 实测 | ✅ 文件落盘 + AX 正文，双重读回 | ✅ VM 内 | **最接近「后台流程」的现成资产**，推荐首选 |
| B. Finder 文件整理（批量重命名/归档） | 需新造 | ✅ 文件系统确定性核验（最强） | ✅ | 真实感强，但要新写工具面（Finder AX 较糙） |
| C. 计算器任务集（现有 6 任务） | ✅ 23 条坑位 + P5 失败史 | ✅ AX 读屏 | ✅ | 定位是**基线与评测载体**，不满足「真实/后台流程」 |

- 建议路径：**A 为主场景关 §12-3，C 继续当评测基线**（Phase 4 的 10 种子先跑 C 拿通机制，再跑 A 出对外数字）。
- 裁决后落账：decision-log 新条目（三判据逐条引证据）+ PRD §12-3 关闭 + README 场景登记。

### Phase 4：≥10 种子评测

1. 定种子语义并写死：**种子 i = 金像克隆起跑 + VLM 以 seed 独立采样 + 响应缓存按 seed 隔离（或评测期关闭）**；记忆策略固定为 fresh-clone 冷启动。
2. 复用 `real_eval.py` 的骨架（≥10 强制 / 逐种子成功率 / CI / 留痕），执行面换成 CUA eval（每种子一轮 `python -m examples.cua.eval`，证据库落 VM 克隆内或回传宿主机，开工时定）。
3. 时长估算：每种子 = 克隆重置（秒级）+ 6 任务跑批（真机 P1 约 30s/任务，VM 加 VLM 网络往返估 5–10 分钟/种子）→ 10 种子约 1–2 小时，无人值守可完成；macOS VM 并发上限 2 台（Apple 限制），先串行。
4. **验收**：10 种子成功率集 → `seed_confidence_interval`@0.95 → CI 并入 `cua.eval.report`；`evaluation.real_seed_ci` 留痕；中断有 `evaluation.eval_interrupted`（机制已在库）。
5. 附带交付：VM 上的干净基线正是 README P5 那句「稳定环境后重跑即得干净基线」的兑现——真机不可用数字的补齐。

### Phase 5：演示包（Developer Preview 面）

1. ⚠️ 先验证：CUA run 能否直接过 4.3 自包含 HTML 回放生成器出一个可分发文件（零侵入声称支持，未试）。
2. 产物：场景 A 的一次全绿 run → HTML 回放 + 2–3 分钟录屏（屏幕共享录 VM 桌面）+ 一页讲稿（主打安全面叙事，见目标 2）。
3. 现场演示备选：双窗——左边 VM 桌面看 agent 操作，右边宿主机终端 tail 事件流（六段链/闸拦截/核验实时滚动）。

---

## 五、风险清单（开工先看）

| # | 风险 | 对策 |
|---|---|---|
| 1 | VM 系统语言与坑位 #2 的中文数字解析不匹配 | Phase 0.5 确认语言；英文则 verifiers 加英文数字分支，或 VM 切中文系统语言 |
| 2 | macOS 26 vs 27 的 AX 差异远超预期（标定协议失效级） | 坑位表本就按 27 写；差异全部记录，若真失效可换 tahoe 之外的镜像重克隆（本地 registry 里有） |
| 3 | VLM 网关地址不对 / LM Studio 不听局域网 | Phase 2 第一步就实测；实在不通退而求其次在 VM 内跑小模型（不推荐，内存紧） |
| 4 | SSH 发起进程的 TCC 归因问题反复 | 规矩定死：agent 只从 VM 内 Terminal/LaunchAgent 起，SSH 只做同步查询 |
| 5 | 种子独立性被响应缓存/记忆破坏 | Phase 4.1 的定义先写死并代码化（缓存开关或 seed 盐） |
| 6 | VM IP 每次开机变 | 一律 `tart ip` 取，不写死 192.168.64.2 |
| 7 | 本机网络对 ghcr/GitHub 极慢（本计划全程已付过学费） | VM 内不做大下载：依赖走 VM uv 缓存，重建 VM 走本地 registry 5055 |
| 8 | 2 台 macOS VM 并发上限 | 评测先串行；要并行只能 2 台，或改 Linux guest（那是后话） |

## 六、速查

```bash
# 宿主机
~/.homebrew/bin/tart list|ip|run|stop vasta-ci-macos   # ip 每次开机取
ssh admin@$(~/.homebrew/bin/tart ip vasta-ci-macos)
open vnc://admin@$(~/.homebrew/bin/tart ip vasta-ci-macos)
tart clone vasta-ci-macos vasta-golden                  # 金像快照（含 TCC 授权）
tart clone --insecure localhost:5055/vasta/macos-tahoe:latest <名>  # 从本地 registry 重建
# 同步代码到 VM（只含已提交内容）
cd ~/Desktop/VastaCore && IP=$(~/.homebrew/bin/tart ip vasta-ci-macos)
ssh admin@$IP 'rm -rf ~/VastaCore && mkdir -p ~/VastaCore' && git archive HEAD | ssh admin@$IP 'tar -x -C ~/VastaCore'
# VM 内
export PATH=/usr/local/bin:$PATH; cd ~/VastaCore && uv sync --all-packages --frozen
uv run python -m examples.cua.probe_grounding|run_task|loop|textedit|eval
```

## 七、本计划不覆盖（避免范围漂移）

Stage 2 完整进入门（3 团队每周使用、SM-5）、其余四条开放问题（品牌核查/团队规模/SaaS 优先级/受众口径）、44GB 中间产物的回收（用户已裁决暂留）、GUI 代码沙箱化（另一条线，见 [scripts/ci_local.sh](../scripts/ci_local.sh) 与 sandbox 探针 /tmp/vm_backend_probe.py 的讨论记录）。

---

## 八、实施进展补记（2026-11-12/13 实测）

### Phase 0 ✅

- 三项 TCC 授权就位（Terminal 的屏幕录制/辅助功能/自动化，经屏幕共享 GUI 一次性点击）；`launchctl asuser` 绕行实验证伪（截屏与 AX 均被封），GUI 授权是唯一路径。
- 金像快照 `vasta-golden`（含授权 + 热缓存 + 已同步仓库，APFS 写时复制）。
- VM 系统语言 = **简体中文**（坑位 #2 中文数字解析直接适用）；显示 1024pt、截图 2048px（2x），scale 运行时实测自适应无误。

### Phase 1 ✅（2026-11-12）

- `run_task` 六段链 **5/5 complete、核验 5/5 passed、display=126、首偏差=无、30 事件/17 工件**——与主机 P1 基线同口径。
- 期间产出坑位 **#24**（macOS 26 屏值带 U+200E 不可见方向标记）与 **#25**（减号渲染为 ASCII 连字符 U+002D）——修复入 `ax.py`/`calib.py`，README 坑位表已登记；标定失败报错现附 raw 步值。

### Phase 2 ✅（2026-11-12）

- VLM 接线：LM Studio 仅绑 127.0.0.1，宿主机起 `/tmp/vasta_vlm_relay.py`（只绑 NAT 网桥 192.168.64.1:1235 → 127.0.0.1:1234），VM 侧 `CUA_BASE_URL=http://192.168.64.1:1235/v1`；备选更永久方案 = LM Studio 开「本地网络服务」。
- `probe_grounding` **10/11 = 91%**（门禁 80%，API 12 次）；`loop` VLM 自主闭环 **PASS**（vision 模式 5 步全对、核验 5✓/0✗、链 5/5、首偏差无、144s）。

### Phase 3 ✅（2026-11-13 所有者确认）

主场景 = **TextEdit 文档流程**（关 PRD §12-3）；计算器任务集 = 评测基线。三判据证据与完整裁决见 [decision-log.md](decision-log.md) 2026-11-13-1。

### Phase 4 关键前置发现

`vlm.py` 采样 `temperature=0`（贪心）——**多种子评测必须开温度并按种子注入 seed、且隔离响应缓存**，否则 10 个种子是同一次贪心解码的重放，CI 无意义（计划 §一目标 3 的预警经代码核实成立）。

### Phase 4 首个基线（2026-11-13/14 第四跑）

- 种子语义落地为 `seeds.py`：独立 store（fresh 标定+缓存）+ VLM 请求注入 temperature/seed + **≥10 强制**（复用 `W1_MIN_SEEDS`）+ `seed_confidence_interval`（9.11 契约）+ `evaluation.real_seed_ci` 留痕（summary store 实测验证）。
- **temperature=0.3 × 10 种子 × 6 任务：mean 0.617，CI@95% [0.507, 0.726]**，10/10 种子完整出数（830-1170s/种子）——首个 GUI 路径多种子基线。
- 基线含已知缺陷（诚实口径）：**坑位 #26**（含减号任务 sub/mix 因期望 U+2212 vs 屏值 ASCII `-` 系统性 deviation——修复后重跑出干净基线）；VLM 坏 JSON ×2 重试失败的样态**保留不修**（属被测的模型健壮性属性）。
- 运维教训入档：①宿主机睡眠会杀 VM——彻夜跑须 `caffeinate` 守护（监视器自愈重挂）；②单种子预算须按实测单任务时长定容（170-700s/任务，6 任务 + 标定 = 20-35 分钟）；③`.command` 硬编码参数会压掉代码默认值（乌龙实录：0.7 覆盖了 0.3）。
