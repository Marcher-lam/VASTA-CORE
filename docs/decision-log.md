# 决策日志（跨切裁决记录）

> 记录**跨 Story/跨 Epic** 的项目级裁决（Story 内决策见各自档案；
> 架构决策见 ARCHITECTURE-SPINE 的 15 条 AD）。带日期、只增不改。

## 2026-11-06-1：本 Mac 仓库即主仓

**背景**：根目录曾存在 `MIGRATED-TO-Dev.txt`（2026-09-14 声称已迁
Windows 并「本目录可安全删除」），但 11 月的全部提交（examples/cua、
examples/rag、缺口清偿）实际都发生在此 Mac 仓库——两地分叉，簿记
失实。

**裁决**：以本 Mac 仓库（github.com/Marcher-lam/VASTA-CORE）为唯一
主仓；删除失实注记；examples/rag 入库（BYOK 密钥全环境变量，无硬
编码）。提交 `72103cc`。

## 2026-11-06-2：W-1 正式解除

**背景**：W-1（真实模型适配器）豁免的解除条件三要素——执行路径、
≥10 种子、CI 并入评测报告——机制由 11.11/12.10 交付，缺真实运行
证据；原门控「集成测试」是占位（只断言环境变量不在）。

**裁决**：真实运行证据齐备即解除——本地 `qwen3.8-27b-mlx`（LM
Studio，OpenAI 兼容）经平台管线跑 5 任务 × 10 种子全对，CI
[1.0,1.0]@95% 入 `OfflineEvalReport.seed_ci` 并留痕
`evaluation.real_seed_ci`；vision 探测同步真 PNG 化 + 多模态接线，
真 VLM 从像素读出密标。记录见
[reviews/w1-recheck-2026-11-06.md](reviews/w1-recheck-2026-11-06.md)。
提交 `927ba18` / `d711080`。

## 2026-11-06-3：许可证 = Apache-2.0（全仓）

**背景**：PRD 开放问题 2（Developer Preview 前必须定）。

**裁决**：Apache-2.0（显式专利授权）。淘汰理由：AGPL 被大量企业
法务一刀切，堵死 SM-5 企业伙伴路径；MIT 无专利条款；闭源切分违背
完整项目形态且商业上不必要。商业口径：核心永久开源自托管，变现走
托管服务 + 企业支持（land-and-expand，PRD §10 默认方案）。11 个包
元数据同步 SPDX 声明；CONTRIBUTING 补 inbound=outbound 条。提交
`556eae6`。

## 2026-11-06-4：登记缺口清偿提前实施（SM-5 信号前）

**背景**：终检（2026-09-14）判定 PASS with registered gaps——FR
partial 4 条、NFR partial 4 + absent 1 条，其中 FR-002 余下两形态
原排序「待 SM-5 伙伴信号确认需求后补拆」。

**裁决**：由用户指令提前实施（与 8.11 ToolProxy 同裁决模式）——
middleware/sidecar（8.14/8.15）、音视频真实字节与 OCR/ASR 引擎面
（8.16）、商业分发子面（12.12）、Console 无障碍与 i18n（10.14）、
运营达标工程面（9.15）六 Story 清偿全部登记缺口。对拍见
[project-final-review-addendum-2026-11-06.md](project-final-review-addendum-2026-11-06.md)。

## 2026-11-07-1：企业付费意愿——所有者裁决关闭

**背景**：PRD 开放问题 1（蓝图 A5），原为 Stage 0 硬前提——20–30 个
企业访谈验证付费假设，直接影响 Stage 2+ 排期。

**裁决**（所有者）：关闭。诚实登记：付费假设**未经访谈验证**（零
访谈），风险自担——Stage 2+ 排期以自有节奏推进，不挂访谈门；后续
若引入投资/合伙人需重开此条。

## 2026-11-07-2：首批模型支持 = DeepSeek（OpenAI 兼容）

**背景**：PRD 开放问题 4，默认建议「一个 OpenAI 兼容接口 + 一个
独立适配器」。

**裁决**：首批正式选定 **DeepSeek**（`https://api.deepseek.com/v1`，
OpenAI 兼容方言）——现有 `OpenAICompatAdapter` + BYOK SecretRef
零改动即接（W-1 门控面同路径）；本地 LM Studio（qwen VLM）保留为
离线/airgap 档参考实现。门控实测形态：

```bash
VASTA_REAL_ADAPTER=https://api.deepseek.com/v1 \
VASTA_REAL_API_KEY=<BYOK 环境变量> \
VASTA_REAL_MODEL=deepseek-chat \
uv run pytest tests/test_real_adapter.py -q
```

## 2026-11-07-3：公共插件市场开放条件——暂缓

**背景**：PRD 开放问题 8（Stage 5 评估）。

**裁决**：暂不开放公共市场——保持私有注册表形态（12.12 已交付
定价/凭据/拉取闸全套机制，开放只差运营决定）；无时间表，触发条件
为生态信号（出现第三方发行方申请上架）。

## 2026-11-13-1：首个真实 GUI 场景 = TextEdit 文档流程（PRD 开放问题 3 关闭）

**背景**：PRD §12-3「首个真实 GUI 场景——需"有历史失败、可读回、非安全
关键的后台流程"，Stage 0 选定」。此前无安全承载环境致长期悬置；tart
macOS VM（vasta-ci-macos，macOS 26.6.2）落地后三判据可同时满足
（CUA 原型已于该 VM 内全链路三连绿：run_task 六段链 5/5、probe
10/11、VLM 自主闭环 PASS——见
[vm-gui-scenario-plan §八](vm-gui-scenario-plan-2026-11-12.md)）。

**裁决**（所有者 2026-11-13 确认）：主场景 = **TextEdit 文档流程**
（新建→录入→存盘→读回），三判据逐条：

- **历史失败**：README 坑位表 13–17（中文 IME 拦截 keystroke、S 键码
  误值、保存面板 .rtf 追加与转义、⌘W 三键对话框吞键入、R3 挂起重放
  被拒）+ P5 诚实口径的环境漂移记录——失败史完整可回看；
- **可读回**：双通道确定性核验（文件落盘内容 + AX 正文直读，
  P2-B 实测 type_text/save_doc 全 passed）；
- **非安全关键**：动作全部发生在 VM 克隆环境内，坏即弃（tart clone
  秒级重建），宿主机与真实数据零接触。

计算器任务集**不承担**「真实场景」（纯玩具），定位保持为评测基线
（Phase 4 ≥10 种子的载体）。口径同前四条关闭：账面记本日志，
PRD §12 原文不动。

## 2026-11-16-1：VISTA 机制吸收六序全批执行

**背景**：VISTA 源码深读（11 文件）产出
[vista-absorption-plan-2026-11-16.md](vista-absorption-plan-2026-11-16.md)
（A–H 判定 + 六序落地，决策门「待所有者裁决」）。所有者下令开工
（纪律栈：superpowers 外环 / matt TDD+类型检查+末尾 review / bmad
story 簿记）。

**裁决**（所有者）：六序全批。执行留痕（TDD 红转绿，每 story 独立
提交 + code-review）：

- ① 错误即观测（d37b4f2，9 测试）：VLM 坏 JSON 从盲重试改错误观测
  回喂——根因深挖：盲重试 × 响应缓存 = 必然二连炸；
- ② read_pixels 取证原语（0daa163，12 测试）：P6 独立观测通道
  （不依赖 AX 的像素 diff）；
- ③ inspect + history 投影（7a508ec，16 测试）：CAS ref 寻址回看 +
  分页投影，含 code-review 补强 ×2（fail-closed）；
- ④ 压缩检查点治理（cbba5e9，11 测试）：修 loop.py history[-4:]
  裸滑窗静默丢失实测隐患；有据偏离：检查点落 CAS 工件+实体索引
  而非手搓事件信封（seq 由 engine sequencer 独管）；
- ⑤ 契约三件（6641540，10 测试）：矩阵构造期强制 / public_view
  评测隔离 / Observation derived 血缘；测试演进 ×1（R0+写清单
  构造期即非法——防线前移，纯函数层保纵深防御语义）；
- ⑥ 微吸收（0528b82，5 测试）：ex-ante 预期落史 + CAS 只读位；
  篡改模拟测试演进 ×5（解锁行）。

**门禁**：全量 1381 passed / 7 skipped；ruff 全绿；lint-imports
契约 5 kept / 0 broken（AD-1 保有）。集成数字（基线失败模式占比
变化、检查点实拍）待 VM 评测窗口与 P6 同批回填（story 遗留已登记）。

**不吸收清单维持**（方案 §六）：runtime / play / RHAE / 四 benchmark
适配器；GUIDE.md 文件本体（Claim 图超集，仅吸收续接语义）。

## 2026-11-16-2：P6 点击失灵根因 = 幂等键跨重试碰撞（真机实证）

**背景**：Phase 4 基线主力失败模式「点击间歇性不生效（executed 而
屏值不变，退化随持续交互加深）」登记为 P6 候选（三假设：AX 负载
退化 / 表达式态累积 / VM 特有）。VISTA 吸收集成为其交付了独立观测
通道，真机两轮取证。

**根因**（run 01a1e466 证据链）：loop 不传 `plan_step_id`（缺省
`"default"`）→ 同 run 内**同 mark 的所有点击共享 AD-11 幂等键** →
核验失败后的同键重试被网关**重放原 ToolResult 而非真执行**
（`replayed=True ×13 连`）。「executed 而屏值不变」、AX 读数漂移
（重放携带首次旧值）、失败率随任务位次递增（后期重复键概率高）
全部同源。主机侧另采得 AX 表达式行/结果行漂移样本（次要因）。

**修复**：loop 传 `plan_step_id=f"decision-{steps}"`（每次决策是
新意图操作——AD-11 语义内正确使用，平台零改动）。判别实验
`77+7`（mark12 ×3 重复点击，修复前必死循环）：**5/5 全核验 PASS，
132s**。run 01a1e48c。

**连带**：闸拒活锁修复（反馈带次数+候选——同 prompt × 缓存 = 同
答案的族根因）；陈旧部分标定缓存清除（W-1 时代 13/14 键缺 0/=/AC）。
VM 多种子基线重跑（预期 mean 显著变化）→ 下一 VM 评测窗口。
