---
story_key: 6-2-沙箱执行器-受限子进程
baseline_commit: 289465b
---

# Story 6.2: 沙箱执行器（受限子进程）

**Status:** review

## Story
见 docs/epics.md Epic 6 Story 6.2。

## Acceptance Criteria
见 docs/epics.md 对应条目——全部经 tests/test_model_lab.py 验证。

## Dev Notes
- vasta-model-lab/lab.py 单模块交付六 Story（接口/沙箱/验证/元控/规划/桥接）
- Windows 无 resource 模块：CPU/内存限额 POSIX 专属（skip 记录），墙钟超时跨平台兜底
- 规划器安全时钟经 _bookkeeping_stub 供给（AD-15；AD-5 扫描已纳入 model-lab 包）

## Change Log
- 2026-09-09：Story 6.2 实现完成（与 Epic 6 同批交付）；323 全绿；状态 review。
- 2026-11-06：darwin 可移植性修复——一步式 setrlimit 在 macOS 抛
  ValueError（hard 不得一步降到 soft 下），改两步式 + 按资源独立
  容错（RLIMIT_AS 在 darwin 内核不支持——EINVAL，与 Windows 同边界
  由墙钟兜底）；本机内存限额测试由「假通过」改诚实 skip。
- 2026-11-06：RLIMIT_AS 改**增长量上限**（=VmSize 基线 + mem_mb 预算）
  ——按预算设总量上限会在真 x86_64 Linux 杀死 CPython 启动
  （VmSize≈200-320MB≫128MB，GitHub Actions 首跑六连红实测；
  Windows ImportError / macOS EINVAL 双跳过致从未暴露）。mem_mb
  语义不变（超预算增长仍被杀），arm64 容器 + macOS 双验证。
