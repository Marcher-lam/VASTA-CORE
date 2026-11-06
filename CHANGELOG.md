# Changelog

本仓按 Story 提交（git log 即细目）；本文件按**阶段里程碑**汇总。
版本约定：协议/schema 兼容窗内小步前进，破坏性变更进新主版本
（PRD §10 弃用四阶段 + N-1 窗口）。

## v0.1.0（2026-11-06）——六阶段全量 + 登记缺口清偿 + W-1 解除

首个完整版本：82 条 FR 全 delivered、NFR 工程可验面 15/15、
1317 测试全绿（+7 门控 skip）、ruff/import-linter 5 契约 KEPT。

### Stage 1（Epic 1–7）：MVP 核心 ★34 FR
- 协议基座（事件信封 + 五协议 + 契约测试套件，AD-1 依赖根）
- Run 生命周期/三档预算/Supervisor 兜底；五类 Observation 全量采集
- Evidence Store：SQLite 事件库 + sha256 分桶 CAS（防篡改检测）
- 多维检索、图像回看工具集、派生血缘回链
- ActionContract 六段链（缺段拒执行）、ToolGateway 清单强制、
  策略引擎四态 fail-closed、组合核验、有界恢复、人工控制（R3）
- 因果时间线、首个偏差定位、自包含 HTML Replay、复现包离线重放
- Claim 图四类记忆全生命周期（互斥冲突/级联失效/预算内装配）
- 世界模型沙箱（受限子进程/静态检查/回放性质/规则版 meta/
  受约束规划）+ 认知↔模型失效桥接（AD-13）
- 评测框架 + VastaLab 任务集 + 六组消融

### Stage 2（Epic 8）：开发者接入（FR-002 五形态全量）
- SDK（AgentSession 三步接入）、HTTP 服务、轨迹导入、Tool Proxy
- 模型五维能力探测（行为化，fail-closed）、按策略路由熔断
- 血缘时行、版本化、离线轨迹评测、脚手架
- **2026-11-06 补齐**：middleware（编排器 dict 进出零改造）+
  sidecar（loopback 单伴生，任意语言 HTTP）两形态（Story 8.14/8.15）
- **2026-11-06 补齐**：音视频真实字节（WAV 帧级切片/MP4 采样表
  字节坐标/跨模态对齐）+ OCR/ASR 引擎注入面与封闭域真实参考实现
  （DTMF Goertzel/5×7 模板）+ 词法 embedding（Story 8.16）

### Stage 3（Epic 9）：规模化运行
- 双存储后端 + 统一 Sequencer、实体索引、删除证明、证据权限
- 批准记录五要素、发布金丝雀、事务批（补偿回滚）
- 配额/成本三级归集、定时/批量 Run、跨进程恢复、批量重验证衰减
- 运维基线（备份/恢复演练/告警/事故）、Domain Studio、沙箱生产化
- **2026-11-06 补齐**：运营达标工程面——SLO 达成度测量（错误预算）、
  计时演练（RTO/RPO 实测 + SLO 门判）、cron 定期演练接线、
  多进程共享单库形态锚定（Story 9.15）

### Stage 4（Epic 10）：企业治理
- 子包重构、测试卫生、模型全生命周期（吊销不可逆级联）、漂移告警
- 认知三算子、审计导出（无内容）、开放 schema 迁移
- RBAC、OIDC/SCIM、审计日志、驻留保留、BYOK/airgap、用量计费
- **2026-11-06 补齐**：Console 最小可用面——零 JS 无障碍（skip link/
  原生元素/label/caption+scope）+ 双语 i18n（UI/时间/数字/事件描述）
  + payload 四组可读对比（Story 10.14，NFR-012/013 收口）

### Stage 5（Epic 11）：平台化与多 Agent
- 目录生成/发布脚本、委派契约（输入范围/预算 fail-closed）、
  记忆隐私（默认私有，仅 accepted 可发布）、Agent 角色、共享边界
- 动态自治、组织风险预算、概率/组合模型、并行竞赛、排行榜、
  流式/边缘底座（帧 CAS）

### Stage 6（Epic 12）：开放生态
- 流注册守卫、enforcement 接线、模型事件留痕、插件清单验签、
  私有注册表（不可变条目）、撤销闭包、可信发行方扫描门
- 公开发现与评分（证据引用语义）、证据签名（第三方可验）
- 边缘编排（驻留/清单编组/fail-closed 路由）
- **2026-11-06 补齐**：插件商业分发子面——定价单（不可变）/购买
  凭据（支付网关可注入）/pull_plugin 商业闸（Story 12.12，FR-084）

### 2026-11-06 其他
- darwin 可移植性修复（沙箱降限两步式——macOS RLIMIT_AS EINVAL）
- 真实模型面：vision 探测真 PNG 化 + 适配器多模态接线（真 VLM 从
  像素读出密标）；**W-1 正式解除**（本地 qwen3.8-27b-mlx × 10 种子
  全对，CI [1.0,1.0]@95% 入评测报告并留痕——
  docs/reviews/w1-recheck-2026-11-06.md）

### 端到端原型（examples/，零侵入）
- **examples/cua——macOS 桌面 CUA（P0–P5 全 PASS，只调公共 API）**：
  SoM 视觉感知（qwen3.5-9b-mlx 本地）+ 点击反推标定（AX 零标签的
  确定性反解）+ 六段链执行 + AX 独立核验（INV-06）+ R3 人在环
  （原生 approval 事件 + resume 重放）+ 字节级确定性回放（AD-5
  桌面版）+ Claim 图 UI-记忆（改版=反例，平台级联失效）+
  guardrails 四层闸（角色/委派/矩阵/预算负例全实证）+ 任务集 eval。
  附 23 条 macOS 27 桌面实测坑位表（AX 退化/焦点战争/IME 拦截/
  SavedState×defaults 双层恢复等）。
- **examples/rag——多模态 RAG**：L1 向量粗筛 + L2 原始兜底两层检索、
  引用回源核验、消融量化（+13.1pp 关键词覆盖）；嵌入选型实测记录。
  （产物不入库约定）

### 已知边界（登记在册）
- 属地运营三项：生产 SLO 月度统计、真跨机分布式部署、多区域演练
  执行（测量/编排机制已交付，数字待真实运营数据）
- OCR/ASR/支付为封闭域或开票形态参考实现（注入面就绪）
- PRD §12 九条开放问题（决策门）：许可证、付费意愿、GUI 场景、
  首批模型（默认答案已具备：本地 OpenAI 兼容 VLM）、品牌、团队、
  SaaS 优先级、插件市场开放条件、简报口径
