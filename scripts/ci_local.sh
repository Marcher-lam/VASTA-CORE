#!/usr/bin/env bash
# 本地复现 CI 门禁（.github/workflows/ci.yml 同一口径）：
#   uv sync --all-packages → ruff check → lint-imports → pytest -q
#
# 为什么用容器：GitHub runner 是 x86_64 Linux，本机是 Apple Silicon——
# x86_64 特有 bug（如沙箱 RLIMIT_AS/VmSize 杀 CPython 启动，CHANGELOG
# 2026-11 有案）只有该架构能抓到；macOS 上该测试恒 skip。
#
# 依赖：docker 或 podman 任一。默认 linux/amd64（对齐 CI）；Docker
# Desktop 建议开启「Use Rosetta for x86_64/amd64 emulation」加速，
# 未开则回退 QEMU 模拟（全量测试会明显变慢）。
#
# 用法：
#   scripts/ci_local.sh                     # amd64 + Python 3.13，全量门禁
#   scripts/ci_local.sh --arch arm64        # 原生架构（快，非 CI 口径）
#   scripts/ci_local.sh --py 3.12           # 换 Python 版本
#   scripts/ci_local.sh --py all            # 3.12 + 3.13 双跑（同 CI 矩阵）
#   scripts/ci_local.sh -- -k sandbox_pool  # 「--」后参数透传给 pytest
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
ARCH="amd64"
PY="3.13"
PYTEST_EXTRA=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --arch) ARCH="$2"; shift 2 ;;
    --py)   PY="$2";   shift 2 ;;
    --)     shift; PYTEST_EXTRA="$*"; break ;;
    *) echo "未知参数: $1（支持 --arch amd64|arm64 / --py 3.12|3.13|all / -- 透传 pytest）" >&2; exit 2 ;;
  esac
done

# 运行时探测：docker 优先，退 podman（CI runner 预装 podman 的同族口径）
if command -v docker >/dev/null 2>&1; then
  RUNTIME=docker
elif command -v podman >/dev/null 2>&1; then
  RUNTIME=podman
else
  echo "错误：未找到 docker 或 podman，请先安装其一。" >&2
  exit 1
fi

run_matrix () {
  local py="$1"
  local image="ghcr.io/astral-sh/uv:python${py}-bookworm"
  echo ""
  echo "==> 门禁矩阵：linux/${ARCH} + Python ${py}（${RUNTIME}）"
  # venv 放容器内（UV_PROJECT_ENVIRONMENT），避免重建/污染仓库里的本机 .venv；
  # uv 解包缓存挂 named volume，重复跑只花首次下载的工夫。
  # --frozen：CI 在干净 checkout 上 uv sync 等价于冻结 lock，本地防止意外改 uv.lock。
  "$RUNTIME" run --rm \
    --platform "linux/${ARCH}" \
    -e UV_PROJECT_ENVIRONMENT=/root/venv-ci \
    -e UV_HTTP_TIMEOUT=300 \
    -e UV_CONCURRENT_DOWNLOADS=4 \
    -v vasta-ci-uv-cache:/root/.cache/uv \
    -v "$ROOT":/workspace \
    -w /workspace \
    "$image" \
    bash -eu -c '
      uv sync --all-packages --frozen
      echo "-- ① ruff --------------------------------------------------"
      uv run ruff check packages tests examples
      echo "-- ② lint-imports（AD-1 架构契约）--------------------------"
      uv run lint-imports
      echo "-- ③ pytest ------------------------------------------------"
      uv run pytest -q '"$PYTEST_EXTRA"'
    '
  echo "==> Python ${py} 门禁绿。"
}

if [[ "$PY" == "all" ]]; then
  for v in 3.12 3.13; do run_matrix "$v"; done
else
  run_matrix "$PY"
fi
