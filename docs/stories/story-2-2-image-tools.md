---
story_key: 2-2-image-tools
baseline_commit: f65e139b5036eee80f14319439053b3ca9b3e7d3
---

# Story 2.2: 图像回看工具集

**Status:** review

## Story

As a Agent 开发者,
I want 对历史帧做原分辨率 inspect、区域 crop、精确 pixel/color read 与并排 Diff,
So that 细粒度视觉疑问（边框？残影？颜色变化？）能用证据回答。

## Acceptance Criteria

**Given** 历史帧已入库
**When** 调用 inspect/crop/read_pixels/diff
**Then** 历史帧按原分辨率恢复；read_pixels 返回指定区域精确颜色值；Diff 输出同源区域并排对齐（FR-014）
**And** 工具输出带帧号与回合号引用，可直接用于新 Claim 的证据

## Tasks/Subtasks

- [x] 1. EvidenceImages（vasta-storage.images）：基于 SqliteStorage 的图像证据工具；inspect（元数据+原始字节原样返回，get_artifact 哈希校验复用）
- [x] 2. crop(box) → PNG 区域字节；read_pixels(box) → 精确 (x,y,(r,g,b,a)) 列表
- [x] 3. diff(sha_a, sha_b) → 同尺寸校验、变更像素数、变更包围盒、并排对齐 PNG（A|分隔|B）
- [x] 4. provenance(sha) → 反查引用该证据的事件（run_id/seq/type = 回合/帧号引用），输出携带可直接作 Claim 证据
- [x] 5. 非图像证据/跨作用域 → 清晰错误；作用域成对强制
- [x] 6. 测试：确定性生成图像（PIL 网格），四工具逐项 + provenance + 作用域 + 非图像错误
- [x] 7. 对照 AC 验证并更新记录

## Dev Notes

- 新依赖 Pillow：AC 要求图像解码/裁剪/像素读取/拼接，标准库无此能力——属 story 内涵依赖（同 pytest-asyncio 先例），版本经 web 核证后钉入 storage 包。
- "原分辨率恢复" = 返回存储原始字节（不经重编码）+ 解码元数据；crop/diff 的输出是新派生 PNG。
- box 规范 (left, top, right, bottom) 半开区间，越界裁剪拒绝。
- provenance 用 json_each 反查 payload.artifact_refs，带作用域过滤。

## Dev Agent Record

### Implementation Plan

1. `images.py`：Box（半开区间+越界校验）/ImageInfo/InspectResult/PixelReading/DiffResult（pydantic，输出可序列化入 Claim evidence）；EvidenceImages 四工具 + provenance（json_each 反查，作用域过滤，SLF001 组合内访问注记）。
2. 依赖：Pillow 12.3.0（2026-07-01 web 核证）钉 `>=12.3,<13` 入 storage。
3. 测试：make_png 确定性网格生成；四工具逐项断言（含字节原样、精确 RGBA、并排几何与左右半区内容、包围盒半开一致）+ provenance + 跨作用域/非图像/半作用域拒绝。

### Debug Log

- 首轮 2 处失败：
  1. provenance 测试设计错误——引擎 capture 的观察载荷是 JSON 而非图像字节，对 JSON 证据 inspect 图像必然失败；改为"PNG 证据 + 引用它的事件"直接构造（这才是生产路径：环境帧落 CAS，观察事件引用 sha）。
  2. diff 包围盒用 ImageChops.getbbox 在 RGBA 全不透明时语义不可靠 → 改与计数同一像素循环推导（半开区间，与 Box 一致），并删除 ImageChops 导入。
- ruff 3 处自动修复（未用导入/排序）。

### Completion Notes

AC 逐条验证：
1. **原分辨率恢复** — `test_original_bytes_and_metadata`：inspect 返回字节与入库原始 PNG 全等（不重编码），元数据 format/width/height/mode/sha 齐备。✅
2. **精确颜色值** — `test_read_pixels_exact_values`：read_pixels 返回 (x,y,(r,g,b,a)) 逐像素断言（RGB→RGBA 补 alpha）。✅
3. **并排对齐 Diff** — `test_side_by_side_and_stats`：变更像素数=1、包围盒=(2,2,3,3)（半开区间）；并排画布宽 = 2w+gap，左半=A 右半=B 内容逐像素验证；同图 diff 零变更且包围盒 None；尺寸不匹配拒绝。✅
4. **帧号/回合号引用（可作 Claim 证据）** — `test_provenance_run_and_frame_reference`：provenance 反查引用事件返回 {run_id(回合), seq(帧), type}，直接可入 Claim.evidence；他作用域反查不可见。✅
5. **边界与错误** — crop 半开区间（right=width 合法、越界拒绝）、非图像证据 `image.not_decodable`、跨作用域不可达、半作用域 `scope.half_pair`。✅

回归：全套 148 passed（前序 137 + 本故事 11）；ruff 全绿；import-linter 契约 KEPT。Pillow 12.3.0 经 PyPI 核证（2026-07-01）。

## File List

- packages/vasta-storage/pyproject.toml（修改：+pillow>=12.3,<13）
- packages/vasta-storage/src/vasta_storage/images.py（新建）
- packages/vasta-storage/src/vasta_storage/__init__.py（修改：导出图像工具族）
- tests/test_image_tools.py（新建，11 测试）
- docs/stories/story-2-2-image-tools.md（本文件）

## Change Log

- 2026-09-08：Story 2.2 实现完成——EvidenceImages 四工具（inspect 原样字节/crop/精确 read_pixels/并排 diff）+ provenance 反查（回合/帧号引用）；Pillow 12.3 核证入库；148 测试全绿；全部 AC 验证通过，状态置 review。
