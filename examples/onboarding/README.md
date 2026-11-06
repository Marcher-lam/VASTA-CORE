# 从零接入演练（examples/onboarding）

把「外部团队第一次接入 VastaCore」完整走一遍——自定义环境 + 自定义工具 + 契约模板 + 确定性回放，单文件可读：

```bash
uv run python examples/onboarding/from_zero.py
```

- `from_zero.py` 分五段注释（① 你的环境 → ② 你的工具 → ③ 契约模板 → ④ 会话执行六段链 → ⑤ 回放验证），每段独立可抄
- 路径与 README「三步接入」一一对应；计时口径见 [docs/onboarding-log.md](../../docs/onboarding-log.md)（SM-5 证据，端到端 1–3 小时）

其余接入形态（HTTP 服务 / 轨迹导入 / Tool Proxy / middleware / sidecar）见根 [README](../../README.md) 与 [docs](../../docs/README.md)。
