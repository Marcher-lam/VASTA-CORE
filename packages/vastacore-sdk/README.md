# vastacore-sdk

**组装根（AD-1）**：外部开发者的唯一入口面——把九个核心包装配成可用平台；唯一允许引用适配器的位置。

## 子包地图

| 子包 | 内容 |
|---|---|
| `execution` | **AgentSession**（三步接入）· middleware/sidecar（FR-002 其余两形态）· ToolProxy · 批量 Run |
| `evidence` | 按需派生（清单 + 真实字节：WAV/MP4）· OCR/ASR/embedding 引擎注入面 · 血缘时行 · 轨迹导入 |
| `models` | 五维能力探测 · 策略路由/熔断 · 离线评测 · 版本化 |
| `ops` | HTTP 服务 · **Console**（零 JS 无障碍 + 双语 i18n）· Studio · SLO 达成度与 RTO/RPO 计时演练 · 调度/配额/计费 |
| `governance` | RBAC/OIDC/SCIM/SAML · 审计 · 驻留 · BYOK/airgap · 漂移 · 发布生命周期 |
| `agents` | 多 Agent 治理（委派/共享/角色/自治/风险预算/排行榜）· 真实模型适配器与多种子评测（W-1 已解除） |
| `ecosystem` | 插件清单验签 · 注册表/撤销 · 信任扫描 · 发现与评分 · **商业分发**（定价/凭据/拉取闸）· 边缘编排 |

## 快速上手

见根 [README](../../README.md) 三步接入与 [examples/onboarding](../../examples/onboarding/README.md)。

## 依赖位置（AD-1）

组装根：可依赖全部核心包与 `vasta-adapters`；核心包不得反向依赖本包。

## 测试锚点

`tests/test_agent_sdk.py`、`tests/test_http_service.py`、`tests/test_console.py`、`tests/test_sidecar.py` 等（覆盖面最宽的包）
Story 档案：`docs/stories/story-8-*`～`story-12-*`
