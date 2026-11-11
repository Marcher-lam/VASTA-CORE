#!/usr/bin/env bash
# Tart macOS 测试 VM：在 Apple Silicon 上跑干净的 macOS 客户机执行门禁。
#
# 为什么是 Tart 而不是 QEMU：QEMU 在 Apple Silicon 上没有可用的
# macOS ARM64 客户机路径（只能跑 Linux/Windows ARM）；Tart 基于
# Apple Virtualization.framework，原生 ARM 性能。苹果许可允许在
# 苹果硬件上每台机器跑最多 2 个 macOS VM 实例。
#
# 用途边界（如实）：VM 内核同为 darwin——本机 skip 的测试（如
# tests/test_model_lab.py 的 RLIMIT_AS 内存限额，macOS 内核 EINVAL）
# 在 VM 里同样 skip。VM 的价值是「干净环境跑全量门禁不污染本机」，
# 不是解锁平台差异测试（那要用 scripts/ci_local.sh 的 Linux 容器）。
#
# 镜像：ghcr.io/cirruslabs/macos-*-vanilla（~15-20 GB 下载）。
#
# 用法：
#   scripts/tart_macos_vm.sh            # 环境检查 + 后续步骤说明（不下载）
#   scripts/tart_macos_vm.sh --go       # 真执行：装 tart + 拉镜像 + 建 VM
set -euo pipefail

VM_NAME="vasta-ci-macos"
IMAGE="ghcr.io/cirruslabs/macos-tahoe-vanilla:latest"

echo "==> 环境检查"
ok=1
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "  ✗ 非 Apple Silicon（Tart 仅支持苹果芯跑 macOS guest）" >&2; ok=0
else
  echo "  ✓ Apple Silicon"
fi
if ! command -v brew >/dev/null 2>&1; then
  echo "  ✗ 未找到 Homebrew（tart 经 brew 安装）" >&2; ok=0
else
  echo "  ✓ Homebrew: $(brew --version | head -1)"
fi
DF=$(df -g / | awk 'NR==2 {print $4}')
if [[ "$DF" -lt 40 ]]; then
  echo "  ✗ 磁盘剩余 ${DF}GB（镜像+VM 需 ~40GB）" >&2; ok=0
else
  echo "  ✓ 磁盘剩余 ${DF}GB"
fi
[[ "$ok" == 1 ]] || { echo "环境不满足，退出。" >&2; exit 1; }

if [[ "${1:-}" != "--go" ]]; then
  cat <<EOF

环境就绪。加 --go 执行（将下载 ~15-20GB 镜像）：

  scripts/tart_macos_vm.sh --go

执行后手动步骤（VM 内跑门禁）：
  1. tart run ${VM_NAME}          # 启动 VM（首次进系统完成设置助理）
  2. VM 内装工具链：
     xcode-select --install
     curl -LsSf https://astral.sh/uv/install.sh | sh
  3. 同步仓库（任选）：
     - 在 VM 里 git clone <repo-url>；或
     - 宿主机挂共享目录后 cp -R（Tart 目录共享见 tart push --dir）
  4. 跑门禁（与 CONTRIBUTING 三道门禁同口径）：
     cd VastaCore && uv sync --all-packages
     uv run ruff check packages tests examples
     uv run lint-imports
     uv run pytest -q
  5. 用完：tart stop ${VM_NAME}；彻底删：tart delete ${VM_NAME}
EOF
  exit 0
fi

echo "==> 安装 tart"
command -v tart >/dev/null 2>&1 || brew install tart
tart --version

echo "==> 拉取镜像并创建 VM：${VM_NAME}（${IMAGE}）"
tart clone "$IMAGE" "$VM_NAME"

echo "==> 完成。启动：tart run ${VM_NAME}（后续步骤见上方 1-5）"
