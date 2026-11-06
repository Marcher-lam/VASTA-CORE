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
