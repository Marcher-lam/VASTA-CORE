# VastaCore CUA 原型（examples/cua）

基于 VastaCore「契约六段链 + 无损证据库」范式的 **macOS 桌面 Computer-Use
Agent** 原型：纯视觉感知（SoM 编号辅助）+ AX 确定性核验。
**零侵入**：只调用 packages/ 现有公共 API，不修改任何平台文件；本目录产物不提交 git。

## 范式

```text
感知：screencapture 全屏（原始证据→CAS）→ AX 枚举 → 窗口裁剪（派生）
      → Set-of-Mark 编号叠加（派生，血缘可回溯）→ VLM 只看标记图
执行：VLM/任务计划给出 mark → click_mark 工具（清单 R2）→ RunEngine
      .execute_contracted 六段链：契约→策略→网关→执行→观察→核验
核验：AX 直读显示屏事实（INV-06：不依赖模型自评）；偏差自动走
      FR-037 有界恢复（environment_delay → retry）
```

与浏览器 agent 的本质差异：**桌面没有 DOM**，编号标记来自 Accessibility
树；而现代 macOS 应用的 AX 标签在退化（见坑位表），所以核验走「点击
反推标定 + AX 值语义解析」这条确定性路径，模型只负责感知与选择。

## 已交付

| 阶段 | 命令 | 结果（2026-11 实测） |
|---|---|---|
| P0 grounding probe | `uv run python -m examples.cua.probe_grounding` | **11/11 = 100%**（门禁 80%）：qwen3.5-9b-mlx 十题按钮定位 + 显示屏读数全对，单题 6-20s |
| P1 旗舰任务（计划驱动） | `uv run python -m examples.cua.run_task` | **5/5 六段链 complete + 5/5 核验 passed**：42×3=126 干净跑，30 事件/17 工件，首偏差=无 |
| P2-A VLM 自主闭环 | `uv run python -m examples.cua.loop` | **PASS**：模型看标记图自主选钮 5 步全对、自答 42×3=126 填入契约预测，AX 独立核验 5/5，首偏差=无；响应缓存跨 run 复用（前 3 步 0.0s 命中） |
| P2-B R3 人在环 | `uv run python -m examples.cua.textedit` | **PASS**：type_text（R2）AX 正文核验 passed；save_doc（R3）→ `approval_requested` 挂起 → 批准 → `approved` → executed → v:passed，文件落盘含标记 |
| P3 确定性回放 | `uv run python -m examples.cua.replay --run-id <id>` | **PASS ×2**：P1 计划 run 与 P2-A VLM 自主 run 均归一化事件流**逐字节一致**（30 vs 30 事件）——AD-5 桌面版复现成立 |
| P4 cognition UI-记忆 | `uv run python -m examples.cua.run_memory` | **PASS 三相**：①标定成功→Claim 图（父布局+17 子按钮，propose→support→accept）；②命中：1 次抽查点击替代 ~40 次标定，任务 5/5；③侧栏改版（树 38→70、几何签名不变=记忆盲区）→ 活检查**子直接推翻 10 + 父级联推翻 7**（平台依赖闭包）→ 冷启动还原 → 重标 → v2 记忆（旧 refuted 留痕，36 主张共存 18 活跃） |

## 快速开始

```bash
# 前置：终端宿主需「屏幕录制」+「辅助功能」权限（重启宿主生效）；
#       LM Studio 挂载视觉模型（默认 qwen3.5-9b-mlx）
uv run python -m examples.cua.probe_grounding   # P0：约 1.5 分钟
uv run python -m examples.cua.run_task          # P1：约 30 秒
uv run python -m examples.cua.loop              # P2-A：VLM 自主（约 1 分钟）
uv run python -m examples.cua.textedit          # P2-B：R3 审批（约 30 秒）
uv run python -m examples.cua.replay --run-id <run_id>   # P3：秒级，零 API
uv run python -m examples.cua.run_memory        # P4：三相约 2 分钟
```

配置经环境变量覆盖（`CUA_BASE_URL / CUA_VLM_MODEL / CUA_STORE_ROOT /
CUA_APP_WHITELIST / CUA_AUTO_APPROVE / CUA_NO_THINK`，见 config.py）。
证据库独立于平台示例：`.vasta-cua/`（store + 标定缓存）。

## macOS 27 桌面 CUA 实测坑位表（本原型最值钱的部分）

| # | 坑 | 对策（代码落点） |
|---|---|---|
| 1 | 新版计算器按钮 glyph 矢量绘制，AXTitle/Description/Help **全空** | 点击反推标定协议（calib.py：Phase1 单击读屏 + Phase2 序列消歧） |
| 2 | AX 显示屏值是**中文语音渲染**（126→「一百二十六」，ln 结果→「自然对数(…)」） | 标定分类兼容中文数字 + verifiers.py 内置中文数字解析 |
| 3 | **表达式计算器**：Esc 只清当前项；`=` 后表达式行**保留**、结果行**新增**（两行各包一层容器，非同父） | read_display：祖父子树扫 static 取 max-y（打字=当前数，求值后=结果行） |
| 4 | 应用状态**跨重启恢复**（pkill+open 挂起表达式原样回来） | hard_reset = pkill + 删 SavedState + open -a |
| 5 | System Events `activate` **抢不到焦点**（后台窗口 Esc 键码不落地）；AXRaise 不切 Space | 一律 `open -a`（LaunchServices）+ 前台守卫重试 |
| 6 | 活桌面焦点争抢（用户在用微信）会打断 40+ 次点击的标定 | 标定按**键盘几何签名缓存**（命中后每 run 仅 3 次点击抽查） |
| 7 | `CGDisplayPixelsWide` 本机返回**点**而非像素 | scale 从实际截图 PIL 宽 / 屏幕点宽实测（2.0x） |
| 8 | qwen3.5-9b：`chat_template_kwargs.enable_thinking=false` **压不住** thinking（空 content 烧满 3600 token，~2min/题） | prompt 尾缀 `/no_think`（30s→11s），vlm.py 默认开 |
| 9 | VLM JSON 输出 mark 时而字符串时而整数 | 计分处 `int()` 归一 |
| 10 | `=` 求值渲染慢于固定 settle（0.35s 读到旧值） | 工具内**轮询至显示变化**（有界 1.5s）——首次触发被 FR-037 记为 environment_delay 偏差，正好演示了平台的有界恢复 |
| 11 | VLM 开放式输出契约（mark+expect+reason）→ thinking 失控空 content；一次错点（把 5 当 2）连续偏差被 **Supervisor 熔断**（正确行为） | 改**意图-定位分离**：模型只答 `{"button", "mark"}`，标定表做意图一致性闸（不一致不点击、反馈重试）；期望由 runner 按意图确定性推导（数字拼接/运算符包含/=时模型报答案由 AX 裁决） |
| 12 | 编号牌外置会与上一行按钮视觉打架（错点率反升） | 13pt + 框内左上（probe 10/10 的形态） |
| 13 | 中文 IME 拦截 `keystroke`：ASCII 被转成候选汉字（"taCore"→"他"） | **剪贴板粘贴**（pbcopy → ⌘V → 还原剪贴板），绕开 IME |
| 14 | **S 的键码是 1**（误用 23 → ⌘S 从未触发，保存静默失败） | 核对键码表；保存面板交互先手动复现再入代码 |
| 15 | 保存面板按富文本格式**追加 .rtf 后缀**且 RTF 转义中文（内容核验挂） | 词干 glob 找文件 + ASCII 标记段核验；run 前清旧文件防「替换确认」弹窗 |
| 16 | ⌘W 清理残留脏文档触发「保留此新文稿？」三键对话框（⌘D 无效），吞掉后续全部键入 | 不做键盘式窗口清理；每 run ⌘N 自建新文档；残留窗口用 AX 点关闭钮/删除钮 |
| 17 | R3 挂起后 Run 进 **paused** 态，直接重放被状态机拒 | 批准后先 `engine.resume()`（重观察 + `run.resumed` 事件）再 `execute_contracted(approved=True)`；平台校验「真实挂起请求」防伪造批准 |
| 18 | 侧栏/模式等 UI 状态存于 **defaults**（非 SavedState）——只删 SavedState 冷启动后侧栏仍开（键区 13 钮异签名） | hard_reset 加 `defaults delete com.apple.calculator`（沙盒应用偏好全清） |
| 19 | 4 秒内**双杀重开**（调用方 reset + engine.reset 各一次 hard_reset）→ AX 树重建流态，读屏撞「无效的索引」 | DesktopEnv 加 `hard_on_reset=False`（env 只 Esc 清零）；read_display 全函数化（流态返回 None 不抛） |
| 20 | 任务镜像读屏（runner 自读 display 对分）在流态下不可靠 | 计分只认**事件流** verification.passed（核验器裁决）——P1 就该这么写 |
| 21 | 上一次枚举的 AX 路径在树变化后过期（`=` 出结果行也会变树） | 交互前重枚举（侧栏钮定位、活检查均自取新鲜树） |

## 平台 API 接线要点

- 直接组装 `RunEngine` + `ToolGateway`（不走 `AgentSession.act`）——
  拿到 `execute_contracted(verifiers=...)` 注入点挂自定义核验器
  `ax_display` / `text_contains`（AgentSession 不透传 verifiers，
  rag 直开 store 同理）；
- 契约期望 DSL：`display=126` / `display_contains=×` /
  `text_contains=<子串>`（changes 段），核验器读 evidence
  （result.detail，AX 直读）；
- R3 人在环原生路径：清单 risk=R3 → 默认策略 `request_approval` →
  `ApprovalRequestedError` + Run paused → 批准 → `engine.resume()` →
  同一契约 `approved=True` 重放（平台校验挂起事件，批准不可伪造）；
- 截图（前/后）在动作链内落 CAS（ToolResult.artifact_ref），
  事件流引用工件；时间线/首偏差/六段链审计 `vasta_storage`/`vasta_contracts`
  公共 API 直出；
- VLM 响应缓存入 store 实体索引（请求哈希 → 工件）——loop 的相同
  步骤跨 run 零 API 复放；
- 已知化妆问题：engine 事件 tenant 为 t-default（RunContext 默认），
  工件为 t-cua——demo 不影响，接治理面时对齐。

## 安全边界

- 白名单应用（默认 Calculator/TextEdit），白名单外前台 → fail-closed；
- click_mark 清单 R2（清单强制，AD-4），Budget max_actions 硬顶；
- probe 只读 + 仅点击沙盒应用内部按钮；hard_reset 只删 Calculator
  的 SavedApplicationState。

## Roadmap（未做，接口已留）

- 任务集 eval（tasks/ JSONL + 批量成功率/步数/首偏差统计）；
  guardrails action_guard（角色/委派白名单/风险预算）接入。
- P2-A 的安全侧战果（值得复用）：模型错点 → 连续核验偏差 →
  **Supervisor 熔断**自动暂停 Run——「幻觉的 agent 被平台拦停」
  已有事件流实证（run 01a1ae63）。

## P4 UI-记忆语义（cognition Claim 图）

- **布局即主张**：父（布局整体：display path + 元素数）+ 子（每按钮
  AX 路径，`depends_on=[父]`，scope={app, layout sig}）；标定成功 →
  propose，任务全核验 → support → accept（evidence=学习 run id）；
- **命中即提速**：recall 只认 accepted/supported + 键盘 ≥12 钮完整；
  1 次抽查点击替代 ~40 次标定协议——记忆收益可度量；
- **改版即反例**：侧栏改变树而几何签名不变（记忆盲区的精确刻画）→
  `record_env_upgrade` 锚点 → 逐主张活检查（`revalidated` 留痕 +
  `decay_confidence` 0.1×）→ 低于线 `refute`——**父先翻，子由平台
  依赖闭包级联失效**（子直接推翻 10 + 级联 7）；
- **重学即 v2**：同签名新主张版本 +1（事件溯源不覆盖），新旧并存
  可审计；
- 认知事件入 "cognition" 系统流（AD-2 投影），全部公共 API。

## P3 回放语义（AD-5 桌面版）

- 替身守卫：`RunContext(replay_mode=True)` + 适配器 `deterministic=True`
  过 `require_replay_adapter`——真实桌面适配器在回放模式被一律拒绝；
- ReplayEnv 按录制序供给观察帧（reset 帧的 detail 从**采集工件**还原，
  事件 payload 本身不带）；ReplayClickTool 返回原 ToolResult——
  `model_dump_json()` 字节相同 ⇒ CAS sha 相同 ⇒ result_ref 相同；
- 契约从录制的 contract 工件原样重建（不重新构造）；核验器照常
  跑在回放证据上（确定性函数 ⇒ 同结论）；
- 终判口径与 quickstart 一致：归一化（抹 run_id/ts/event_id/parent）
  后逐字节对比；两个来源 run（计划驱动 + VLM 自主）均一次通过。

## 模块地图

```text
config.py    # CUA_* 环境变量（BYOK，密钥不落库）
ax.py        # 纯 osascript/JXA：AX 枚举/读值/点击/键码/截图/屏幕信息（零外部依赖）
calib.py     # 点击反推标定 + hard_reset（清零自证）+ 几何签名缓存
marks.py     # SoM：build_marks / crop_window / render_marked
scene.py     # 场景捕获（截图→裁剪→标记；标记表跨步复用）
vlm.py       # OpenAI 兼容 VLM（rag cloud.py 姿势）+ 响应缓存入 store 实体索引
probe_grounding.py  # P0 门禁：grounding 命中率（GT=标定，零模型接触）
env.py       # DesktopEnv（EnvironmentAdapter 五协议）
tools.py     # ClickMarkTool（R2 清单 + 前后截图证据 + AX 读屏）
verifiers.py # AxDisplayVerifier（中文数字解析）/ TextContainsVerifier
run_task.py  # P1 旗舰：42×3 六段链 + 审计 + 时间线
loop.py      # P2-A：VLM 自主闭环（意图-定位分离 + 一致性闸 + 自纠错反馈）
textedit.py  # P2-B：type_text(R2) + save_doc(R3 审批) + 剪贴板输入
replay.py    # P3：确定性回放（替身环境/工具 + 归一化流逐字节对比）
memory.py    # P4：布局/按钮 Claim 图（record/recall/refute 级联）
run_memory.py # P4：三相演示（学习→命中→改版反例→v2 重学）
```
