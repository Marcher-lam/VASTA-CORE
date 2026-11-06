---
story_key: 8-16-media-real-bytes
baseline_commit: d07000e
---

# Story 8.16: 多模态真实字节与识别引擎面（G5，FR-015/016 收口）

**Status:** done

## Story

As a 多模态 Agent 开发者,
I want 音视频按真实字节处理、OCR/ASR 有可用的识别路径与模型注入面,
So that 终检登记的 FR-015「清单形态」与 FR-016「OCR/ASR 零实现」两处
拆解层留白闭环。

## Acceptance Criteria

**Given** 证据库中的音视频/图像原始字节
**When** 显式请求派生（audio_slice/video_window/media_align/image_ocr/
audio_asr/text_embedding_lexical）
**Then** WAV 帧级切片产出可独立播放字节且与源逐帧一致；MP4 采样表解析
产出**真实字节坐标**（offset/size 可对源字节复核）；DTMF 音频与 5×7
字形图像被**真实识别**（封闭域参考实现，输出带 method/vocabulary/
charset 溯源）
**And** 真实模型经 EngineRegistry 注入面注册即接（后注册者生效）；
未注册 fail-closed；不请求不派生；全部确定性（FR-015 + FR-016 收口）

## Tasks/Subtasks

- [x] T1: `evidence/media.py`——`audio_slice`（stdlib wave：帧级切片 +
      RIFF 头重写；非 PCM fail-closed）；`video_window`（ISO-BMFF box
      遍历 + mvhd 时基 + stts/stsz/stsc/stco|co64/stss 采样表 → 每样本
      {pts, offset, size, keyframe} 真实坐标 + 时间窗过滤）；`media_align`
      （跨模态时间相交 + align 键配对，peer 时间线值传入）
- [x] T2: `evidence/engines.py` 注入面——`OCREngine`/`ASREngine`
      Protocol + `EngineRegistry`（ocr/asr 两类、可替换注入、
      未注册 fail-closed 带接入指引）
- [x] T3: 参考实现——`DtmfAsrEngine`（Goertzel 低/高组各 argmax +
      组内 0.6 占优门限 + 绝对静音门；16 键封闭词表 + 分段时戳）；
      `TemplateOcrEngine`（PIL 解码 → 二值化 → 行/列投影分割 →
      bbox 缩放 5×7（NEAREST）→ 全字符集汉明匹配；空格阈值相对
      中位字宽 0.6——放大渲染不误判）
- [x] T4: `text_embedding_lexical`——词 + 字符 3-gram 带符号特征哈希、
      次线性 tf、L2 归一（真实词法嵌入；余弦可比）
- [x] T5: deriver 接线（`image_ocr`/`audio_asr` 解注册引擎产溯源
      JSON；六新 kind 入默认注册表；8.12 四件不动）
- [x] T6: 测试 `tests/test_media_real_bytes.py` 13 条——WAV 对帧+
      幂等；MP4 坐标复核（按 offset/size 取源字节 == 样本标记）+
      非 MP4 拒；对齐三对（键匹配/不匹配）；DTMF 转写 "123" 含时
      段/静音空转写；OCR 原生与 ×3 两档全对 + 注入替换 + fail-closed；
      词法嵌入 L2=1 与相关/无关可分；注册表面全集。全量 1273 passed
      + 5 skipped；ruff 全绿；import-linter 5 契约 KEPT

## Dev Notes

- 全部夹具程序合成（WAV 正弦叠加、手搭最小 MP4、字体渲染 PNG）——
  零外部媒体文件入库，确定性。
- 与 Pillow 12 弃用面隔离：getdata/putdata → tobytes/frombytes。
- 诚实边界：参考实现是封闭域真实识别（DTMF 16 键 / 5×7 字符集），
  非通用语音/文字模型——payload 的 method/vocabulary/charset 就是
  消费方判别依据；真实模型（GUI Pack/云 ASR/语义 embedding）走
  EngineRegistry.register 替换即接。
- video_window 不做重封装（remux 出可播放视频）：交付物是可哈希复核
  的字节坐标——与「证据可回源」的平台语义一致。

## Dev Agent Record

### Debug Log

- DTMF 初版成对求和门限（best>total*0.28）对离 bin 纯音泄漏太脆——
  改标准结构（低/高组各 argmax + 组内 0.6 占优）后稳定。
- video_window 时间窗语义 from≤pts<to：1.5s 样本在 [0.4,1.6) 内——
  测试期望值先写错（少算边界样本），修正期望而非实现。

### Completion Notes

- FR-015 由「清单形态」升级「真实字节」；FR-016 由「零实现」升级
  「注入面 + 封闭域真实参考实现」——终检 §一 表两行 partial 闭环。

### Change Log
