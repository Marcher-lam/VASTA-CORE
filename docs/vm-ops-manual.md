# VM 运维手册（vasta-ci-macos）

## 〇、它在项目中的位置：为什么需要 / 用来干嘛 / 怎么创建的

### 为什么项目里需要它

CUA 原型（[examples/cua](../examples/cua/README.md)）要在真实 macOS 桌面上感知、
点击、核验。直接跑在开发者真机上有四个硬伤：**占键鼠**（agent 跑时人不能用电脑）；
**不安全**（截屏进证据库的是真实桌面、存盘落在真实文件系统——不满足 PRD「首个
真实 GUI 场景」的非安全关键判据）；**环境漂移**（系统/应用一更新布局就变，CUA P5
的任务集成功率数字曾因此不可用——README「诚实口径」在案）；**不可复现**（回放与
多种子评测没有稳定基准）。容器给不了 macOS 桌面，真机给不了安全与稳定——VM 是
唯一同时满足四项的形态。GUI 是 PRD 押注的首个商业验证方向，这台 VM 是该方向的
执行基础设施：CUA 的 VM 内六段链冒烟、VLM 自主闭环、≥10 种子基线（mean 0.583，
CI@95% [0.483, 0.684]）全部在此环境完成（详见
[vm-gui-scenario-plan-2026-11-12.md](vm-gui-scenario-plan-2026-11-12.md) §八）。

### 三个用途

1. **CUA 的隔离执行环境（主用途）**：GUI agent 的全部感知/动作/核验在 VM 内进行，
   坏了 `tart clone` 秒级回干净态，宿主机零接触；
2. **稳定的评测基准环境**：每次从金像快照起跑，环境钉死——多种子评测可比性的来源
   （真机做不到，见上「环境漂移」）；
3. **干净 macOS 交叉验证（次要）**：本机环境被污染/升级后，在此复跑三道门禁做
   干净对照（macOS 口径 1318 passed + 7 skipped）。注意：对齐 CI 的 x86_64 Linux
   口径用的是宿主机容器 `scripts/ci_local.sh`，与这台 VM 分工不同，别混用。

### 怎么创建的（2026-11-11/12，概要）

- **选型**：Apple 芯上 QEMU 没有 macOS 客户机的可行路径；选用 **tart 2.41.1**
  （Cirrus Labs 开源，基于 Apple 虚拟化框架，原生 ARM 性能；苹果许可允许在苹果
  硬件上并发最多 2 个 macOS 实例）。
- **装载**：本机 Homebrew 是 USTC 镜像 fork（无 tart 公式）→ GitHub Releases 直下
  二进制（SHA256 + codesign 双校验）；镜像 `macos-tahoe-vanilla` 22.24GB——tart
  自带下载器 60s 超时必死、docker pull 大层停滞、ghcr 的 HTTP/2 连接被掐——最终
  自写 **16 路并行分块断点续传**（curl `--http1.1` + 分块等值校验）逐层搬运入
  本地 registry（`localhost:5055`；5000 端口被 macOS AirPlay 接收器占用），
  `tart clone` 建机。镜像层备份在 `~/.vasta-oci-mirror/`（22GB，暂留）。
- **初始化**：VM 内装 uv + 独立 Python 3.13（宿主机拷贝，不走慢网络）；经屏幕
  共享一次性授予 Terminal 三项 TCC 权限（屏幕录制/辅助功能/自动化——SSH 发起的
  进程不在图形会话内拿不到，`launchctl asuser` 也绕不过，实测）；授权后打金像
  快照 `vasta-golden`。
- 期间沉淀 macOS 26 兼容坑位 #24–#26（[坑位表](../examples/cua/README.md)）与
  全部运维教训（计划文档 §八）。

### 两台 VM

| 名字 | 角色 |
|---|---|
| `vasta-ci-macos` | 工作机（日常用一个） |
| `vasta-golden` | 金像快照（含全部 TCC 授权 + 热缓存；重置源，别拿来跑） |

`tart` 已在 PATH（`~/.homebrew/bin/tart`）。

---

## 一、启动

```bash
# 方式 A：常规——开一个终端窗口跑着别关（关窗口 / Ctrl+C = 关 VM）
tart run vasta-ci-macos

# 方式 B：后台无窗口（日常推荐；省开销，看画面走屏幕共享）
tart run --no-graphics vasta-ci-macos &

# 方式 C：要跑 VLM 相关（probe / loop / eval / seeds）的完整三件套
nohup caffeinate -dims -t 21600 >/dev/null 2>&1 &              # ① 防宿主机睡眠
nohup python3 /tmp/vasta_vlm_relay.py >/tmp/vasta_vlm_relay.log 2>&1 &  # ② VLM 转发
tart run --no-graphics vasta-ci-macos &                        # ③ 起 VM
```

**三件套缺一不可的场景**：① 只跑 `run_task`（计划驱动，无需模型）时 ② 不用起；
长跑（≥10 种子评测）时 ① 必须有——**宿主机睡眠会杀 VM**（实测踩过），且
caffeinate 在电池供电下不可靠，**长跑请保持 Mac 接电**。

② 的作用：LM Studio 只监听 `127.0.0.1:1234`，VM 够不着；relay 把 NAT 网桥
`192.168.64.1:1235` 转发进去，VM 内 `CUA_BASE_URL=http://192.168.64.1:1235/v1`。
（更省事的永久替代：LM Studio 里开「本地网络服务」，就不需要 relay。）

## 二、接入

```bash
tart ip vasta-ci-macos                    # 拿 IP——每次开机可能变，别写死
ssh admin@$(tart ip vasta-ci-macos)       # 免密直进（宿主机公钥已装）
open vnc://admin@$(tart ip vasta-ci-macos)  # 看画面（屏幕共享，密码 admin）
```

- 账号 `admin`，密码 `admin`，sudo 免密——**仅 NAT 内网可达**（192.168.64.x），
  要长期用建议改密码。
- Terminal 已获三项授权（屏幕录制 / 辅助功能 / 自动化）——**agent 必须从 VM 内的
  Terminal 启动**（桌面双击 `.command`，或宿主机 `ssh … 'open -a Terminal ~/Desktop/xxx.command'`），
  SSH 直接发起的进程不在图形会话内，截屏与 AX 都会被 TCC 拒（实测 `launchctl asuser` 也绕不过）。

## 三、VM 里有什么

| 路径 | 内容 |
|---|---|
| `~/VastaCore` | 仓库（`git archive` 同步的已提交内容；**不含未提交改动**） |
| `/usr/local/bin/uv` | uv 0.12.5（非登录 shell 要 `export PATH=/usr/local/bin:$PATH`） |
| `~/.local/share/uv/python/` | 独立构建 Python 3.13.15 |
| `~/Desktop/cua-first-run.command` | 权限自检 + Phase 1 冒烟（run_task） |
| `~/Desktop/cua-phase2.command` | probe_grounding + loop（需 VLM = 需 relay） |
| `~/Desktop/cua-seeds.command` | ≥10 种子评测（需 VLM + caffeinate） |
| `~/VastaCore/.vasta-seeds/` | 种子评测产物（summary.json / seed-N.log / 留痕 store） |

### 同步最新代码（宿主机执行）

```bash
cd ~/Desktop/VastaCore && IP=$(tart ip vasta-ci-macos)
ssh admin@$IP 'rm -rf ~/VastaCore && mkdir -p ~/VastaCore'
git archive HEAD | ssh admin@$IP 'tar -x -C ~/VastaCore'     # 只含已提交内容
```

### 跑门禁 / 跑 CUA（VM 内）

```bash
export PATH=/usr/local/bin:$PATH; cd ~/VastaCore
uv sync --all-packages --frozen           # 缓存热，约 3 秒
uv run ruff check packages tests examples # 三道门禁（macOS 口径 1318+7）
uv run lint-imports && uv run pytest -q
uv run python -m examples.cua.run_task    # 计划驱动冒烟（无需 VLM）
CUA_BASE_URL=http://192.168.64.1:1235/v1 uv run python -m examples.cua.loop   # 需 VLM
```

（CI 对齐口径的 Linux 门禁在宿主机 `scripts/ci_local.sh`，与 VM 无关，别混用。）

## 四、重置与重建

```bash
# 工作机用坏了 → 从金像重置（秒级，APFS 写时复制；授权/缓存都在）
tart stop vasta-ci-macos
tart delete vasta-ci-macos
tart clone vasta-golden vasta-ci-macos

# 金像也没了 → 从本地 registry 重建（约几分钟；需 Docker Desktop 在跑）
docker start vasta-registry    # 若没在跑
tart clone --insecure localhost:5055/vasta/macos-tahoe:latest vasta-ci-macos
# 重建后是裸系统：授权要重点（见计划文档 Phase 0）、工具链要重装
```

镜像层备份在 `~/.vasta-oci-mirror/`（22GB，用户裁决暂留）；registry 容器
`vasta-registry` 绑 `127.0.0.1:5055`（5000 被 macOS AirPlay 接收器占用）。

## 五、关机

```bash
tart stop vasta-ci-macos
```

## 六、排障速查

| 症状 | 处置 |
|---|---|
| 宿主机睡眠后 VM 消失 | 正常（tart run 随宿主机睡眠退出）——重新 `tart run`；长跑前起 caffeinate |
| 强停后首次开机又立刻关机 | 客户机可能有未完成的重启流程——**再开一次**即稳（实测） |
| VM 里 VLM 连不上 | 依次查：relay 活着吗（`pgrep -f vasta_vlm_relay`）→ LM Studio 活着吗（宿主机 `curl 127.0.0.1:1234/v1/models`）→ 闲置很久先发一个小请求预热 |
| agent 报「显示屏非零」/ 权限类错误 | 确认是从 VM 内 Terminal 启动（不是宿主机 SSH 直跑）；权限自检跑 `cua-first-run` |
| `ssh` 报 Connection closed | VM 还在引导，等 30-60 秒重试；就绪信号以 ssh 通为准（拿到 IP 不算） |

---

*历史坑位（macOS 26 的 U+200E、减号字形、点击失灵调查项等）见
[examples/cua/README.md](../examples/cua/README.md) 坑位表与
[vm-gui-scenario-plan-2026-11-12.md](vm-gui-scenario-plan-2026-11-12.md) §八。*
