"""音视频真实字节处理（Story 8.16，FR-015 收口）——触碰真实字节。

零第三方媒体依赖（stdlib wave / struct / math），三件 deriver：

- ``audio_slice``：WAV PCM 真实字节切片——按帧切出时间窗，产出**可播放**
  的独立 WAV（重写 RIFF 头；非 PCM 形态 fail-closed）；
- ``video_window``：MP4 ISO-BMFF 容器级解析——mvhd 时基 + stbl 采样表
  （stts/stsz/stsc/stco|co64/stss）重建每样本 {pts, offset, size,
  keyframe} 的**真实字节坐标**，按时间窗过滤（坐标可对源字节复核）；
- ``media_align``：跨模态对齐——音/视频两轨窗口按时间相交与对齐键
  配对（peer 时间线以值传入，输出对齐段对）。

与 8.12 清单形态的关系：``media_window``（清单切片）保留不动；本模块
把 FR-015 从「清单不触字节」升级到「真实字节」。全部确定性（同字节
同参数同输出）。
"""

from __future__ import annotations

import io
import json
import struct
import wave
from typing import Any

from vasta_protocols.errors import VastaError


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VastaError(code="derive.bad_params", message=message)


def _win(params: dict[str, Any], total_s: float) -> tuple[float, float]:
    from_s = float(params.get("from_s", 0))
    to_s = float(params.get("to_s", total_s))
    _require(from_s < to_s, f"时间窗倒置: from_s={from_s} ≥ to_s={to_s}")
    _require(from_s >= 0, f"from_s 须 ≥0，得到 {from_s}")
    return from_s, to_s


# ---- audio_slice：WAV PCM 真实字节切片 ----

async def audio_slice(payload: bytes, params: dict[str, Any]) -> bytes:
    """时间窗切片 WAV（PCM）：帧级裁剪 + 独立可播放输出。"""
    try:
        with wave.open(io.BytesIO(payload)) as src:
            _require(
                src.getcomptype() == "NONE",
                f"非 PCM WAV（comptype={src.getcomptype()!r}）——压缩形态不解析",
            )
            nch, sw, fr = (
                src.getnchannels(), src.getsampwidth(), src.getframerate()
            )
            nframes = src.getnframes()
            duration_s = nframes / fr if fr else 0.0
            from_s, to_s = _win(params, duration_s)
            first = max(0, int(from_s * fr))
            last = min(nframes, int(to_s * fr))  # 半开区间 [first, last)
            _require(first < last, "时间窗内无完整帧（窗太窄或越界）")
            src.setpos(first)
            frames = src.readframes(last - first)
    except wave.Error as exc:
        raise VastaError(
            code="derive.bad_params", message=f"源不是合法 WAV: {exc}"
        ) from exc
    out = io.BytesIO()
    with wave.open(out, "wb") as dst:
        dst.setnchannels(nch)
        dst.setsampwidth(sw)
        dst.setframerate(fr)
        dst.writeframes(frames)
    return out.getvalue()


# ---- video_window：MP4 容器级解析（真实字节坐标）----

_BOX_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl"}


def _iter_boxes(buf: bytes, start: int, end: int):
    """ISO-BMFF box 迭代：(type, body_start, body_end)。"""
    pos = start
    while pos + 8 <= end:
        (size32,) = struct.unpack_from(">I", buf, pos)
        box_type = buf[pos + 4:pos + 8]
        header = 8
        if size32 == 1:  # 64 位 largesize
            if pos + 16 > end:
                break
            (size,) = struct.unpack_from(">Q", buf, pos + 8)
            header = 16
        elif size32 == 0:  # 到末尾
            size = end - pos
        else:
            size = size32
        if size < header or pos + size > end:
            break  # 截断/越界——按可解析部分收口
        yield box_type, pos + header, pos + size
        pos += size


def _find_boxes(buf: bytes, start: int, end: int, wanted: bytes):
    for box_type, body_start, body_end in _iter_boxes(buf, start, end):
        if box_type == wanted:
            yield body_start, body_end


def _parse_mvhd(buf: bytes, s: int, e: int) -> tuple[int, int]:
    """mvhd → (timescale, duration_s)（v0/v1 双形态）。"""
    version = buf[s]
    if version == 1:
        timescale = struct.unpack_from(">I", buf, s + 20)[0]
        duration = struct.unpack_from(">Q", buf, s + 28)[0]
    else:
        timescale = struct.unpack_from(">I", buf, s + 12)[0]
        duration = struct.unpack_from(">I", buf, s + 16)[0]
    duration_s = duration / timescale if timescale else 0.0
    return timescale, duration_s


def _parse_hdlr(buf: bytes, s: int, e: int) -> str:
    """hdlr → handler_type 四字符（vide/soun/…）。"""
    if e - s >= 12:
        return buf[s + 8:s + 12].decode("latin-1")
    return ""


def _parse_stts(buf: bytes, s: int, e: int) -> list[int]:
    """stts → 每样本时长（采样数 × count 展开）。"""
    out: list[int] = []
    (count,) = struct.unpack_from(">I", buf, s + 4)
    pos = s + 8
    for _ in range(min(count, (e - pos) // 8)):
        run, dur = struct.unpack_from(">II", buf, pos)
        out.extend([dur] * run)
        pos += 8
    return out


def _parse_stsz(buf: bytes, s: int, e: int) -> list[int]:
    """stsz → 每样本字节数。"""
    sample_size, count = struct.unpack_from(">II", buf, s + 4)
    if sample_size:  # 固定尺寸捷径
        return [sample_size] * count
    return list(struct.unpack_from(f">{count}I", buf, s + 12))


def _parse_stco(buf: bytes, s: int, e: int, box_type: bytes) -> list[int]:
    """stco/co64 → 每 chunk 文件偏移。"""
    (count,) = struct.unpack_from(">I", buf, s + 4)
    if box_type == b"co64":
        return list(struct.unpack_from(f">{count}Q", buf, s + 8))
    return list(struct.unpack_from(f">{count}I", buf, s + 8))


def _parse_stsc(buf: bytes, s: int, e: int) -> list[tuple[int, int, int]]:
    """stsc → [(first_chunk, samples_per_chunk, sample_desc_idx)]。"""
    (count,) = struct.unpack_from(">I", buf, s + 4)
    entries = []
    pos = s + 8
    for _ in range(min(count, (e - pos) // 12)):
        entries.append(struct.unpack_from(">III", buf, pos))
        pos += 12
    return entries


def _parse_stss(buf: bytes, s: int, e: int) -> set[int]:
    """stss → 关键帧样本号集合（1 基）。"""
    (count,) = struct.unpack_from(">I", buf, s + 4)
    return set(struct.unpack_from(f">{count}I", buf, s + 8))


def _sample_table(buf: bytes, s: int, e: int) -> dict[str, Any]:
    """stbl → {durations, sizes, offsets, keyframes}。"""
    table: dict[str, Any] = {"durations": [], "sizes": [],
                             "offsets": [], "keyframes": set()}
    for box_type, bs, be in _iter_boxes(buf, s, e):
        if box_type == b"stts":
            table["durations"] = _parse_stts(buf, bs, be)
        elif box_type == b"stsz":
            table["sizes"] = _parse_stsz(buf, bs, be)
        elif box_type in (b"stco", b"co64"):
            table["offsets"] = _parse_stco(buf, bs, be, box_type)
        elif box_type == b"stsc":
            table["stsc"] = _parse_stsc(buf, bs, be)
        elif box_type == b"stss":
            table["keyframes"] = _parse_stss(buf, bs, be)
    return table


def _samples_of_track(
    buf: bytes, table: dict[str, Any], timescale: int,
) -> list[dict[str, Any]]:
    """采样表 → 每样本 {idx, pts_s, offset, size, keyframe}（真实字节坐标）。"""
    sizes = table["sizes"]
    durations = table["durations"]
    offsets = table["offsets"]
    stsc: list[tuple[int, int, int]] = table.get("stsc", [])
    n = min(len(sizes), len(durations))
    if n == 0 or not offsets or not stsc:
        return []
    # stsc 展开：每 chunk 含哪些样本
    chunk_samples: list[list[int]] = []
    for i, (first, per, _desc) in enumerate(stsc):
        last_chunk = stsc[i + 1][0] - 1 if i + 1 < len(stsc) else len(offsets)
        for _chunk in range(first, last_chunk + 1):
            chunk_samples.append(list(range(first, first + per)))  # 1 基样本号
    samples: list[dict[str, Any]] = []
    pts = 0
    offset_of: dict[int, int] = {}
    for chunk_idx, sample_ids in enumerate(chunk_samples):
        if chunk_idx >= len(offsets):
            break
        off = offsets[chunk_idx]
        for sid in sample_ids:
            if sid <= len(sizes):
                offset_of[sid] = off
                off += sizes[sid - 1]
    for i in range(1, n + 1):
        samples.append({
            "idx": i - 1,  # 0 基
            "pts_s": round(pts / timescale, 6) if timescale else 0.0,
            "offset": offset_of.get(i, -1),
            "size": sizes[i - 1],
            "keyframe": i in table["keyframes"] or not table["keyframes"],
        })
        pts += durations[i - 1]
    return samples


async def video_window(payload: bytes, params: dict[str, Any]) -> bytes:
    """MP4 容器解析 + 时间窗过滤 → 真实字节坐标清单。

    输出样本的 offset/size 是源文件内的**真实字节坐标**——复核方式：
    按坐标取源字节重算内容摘要与窗口声明一致（测试锚定此性质）。
    """
    if len(payload) < 8 or b"ftyp" not in payload[:16]:
        raise VastaError(
            code="derive.bad_params",
            message="源不是 MP4（未见 ftyp）——容器级解析 fail-closed",
        )
    moov = next(_find_boxes(payload, 0, len(payload), b"moov"), None)
    if moov is None:
        raise VastaError(
            code="derive.bad_params", message="MP4 缺 moov box（无采样表）"
        )
    ms, me = moov
    timescale, duration_s = 0, 0.0
    tracks: list[dict[str, Any]] = []
    for box_type, bs, be in _iter_boxes(payload, ms, me):
        if box_type == b"mvhd":
            timescale, duration_s = _parse_mvhd(payload, bs, be)
        elif box_type == b"trak":
            handler, samples = "", []
            for t2, s2, e2 in _iter_boxes(payload, bs, be):
                if t2 == b"mdia":
                    for t3, s3, e3 in _iter_boxes(payload, s2, e2):
                        if t3 == b"hdlr":
                            handler = _parse_hdlr(payload, s3, e3)
                        elif t3 == b"minf":
                            for t4, s4, e4 in _iter_boxes(payload, s3, e3):
                                if t4 == b"stbl":
                                    table = _sample_table(payload, s4, e4)
                                    samples = _samples_of_track(
                                        payload, table, timescale)
            tracks.append({"handler": handler, "samples": samples})
    from_s, to_s = _win(params, duration_s)
    out_tracks = []
    for track in tracks:
        windowed = [
            {**s, "pts_s": round(s["pts_s"], 6)}
            for s in track["samples"]
            if from_s <= s["pts_s"] < to_s and s["offset"] >= 0
        ]
        out_tracks.append({
            "type": track["handler"] or "unknown",
            "sample_count": len(windowed),
            "samples": windowed,
        })
    result = {
        "container": "mp4",
        "timescale": timescale,
        "duration_s": duration_s,
        "window": {"from_s": from_s, "to_s": to_s},
        "tracks": out_tracks,
        "byte_coords_verifiable": True,  # offset/size 可对源字节复核
    }
    return json.dumps(result, ensure_ascii=False, sort_keys=True).encode()


# ---- media_align：跨模态对齐 ----

async def media_align(payload: bytes, params: dict[str, Any]) -> bytes:
    """音/视频窗口对齐：本轨窗口（源）× peer 时间线 → 相交/同键配对段。

    源 = 本侧窗口清单（media_window/video_window 的输出或等价形态）；
    peer = params["peer"]（对侧轨道时间线：[{start, end, align?}]，值传入）。
    对齐规则：时间相交即配对；双侧 align 键非空且相等时显式标注。
    """
    try:
        own = json.loads(payload.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise VastaError(
            code="derive.bad_params", message=f"源不是合法窗口清单 JSON: {exc}"
        ) from exc
    peer = params.get("peer")
    _require(
        isinstance(peer, list),
        "params.peer 须为对侧时间线 list[{start, end, align?}]",
    )
    own_window = own.get("window") or {}
    own_segments = own.get("segments") or []
    if not own_segments and own_window:
        own_segments = [dict(own_window)]  # video_window 输出无 segments 时以窗代
    pairs = []
    for seg in own_segments:
        s1, e1 = float(seg["start"]), float(seg["end"])
        for p in peer:
            s2, e2 = float(p["start"]), float(p["end"])
            lo, hi = max(s1, s2), min(e1, e2)
            if lo >= hi:
                continue
            entry = {
                "overlap": {"from_s": lo, "to_s": hi,
                            "duration_s": round(hi - lo, 6)},
                "own": {"start": s1, "end": e1, "align": seg.get("align")},
                "peer": {"start": s2, "end": e2, "align": p.get("align")},
            }
            keys = {seg.get("align"), p.get("align")}
            if None not in keys and len(keys) == 1:
                entry["aligned_by_key"] = keys.pop()
            pairs.append(entry)
    return json.dumps({"kind": "media_align", "pairs": pairs,
                       "pair_count": len(pairs)}, ensure_ascii=False,
                      sort_keys=True).encode()


__all__ = ["audio_slice", "video_window", "media_align"]
