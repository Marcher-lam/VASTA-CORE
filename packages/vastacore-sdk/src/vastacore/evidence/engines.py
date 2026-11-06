"""多模态识别引擎面（Story 8.16，FR-016 收口）——注入面 + 真实参考实现。

三层结构：

1. **注入面**：``EngineRegistry``（ocr/asr 两类）——真实模型（GUI Pack、
   云端 ASR、语义 embedding 模型）注册即接入，deriver 零改动；
2. **参考实现（工程内真实、零依赖、确定性）**：
   - ``DtmfAsrEngine``：Goertzel 双音检测——对真实 WAV 字节做封闭词表
     （DTMF 16 键）转写，含分段时戳；
   - ``TemplateOcrEngine``：5×7 字形模板匹配——PIL 解码真实图像字节、
     二值化、行/列投影分割、缩放匹配（封闭字符集 digits+A-Z+常用符号）；
   - ``text_embedding_lexical`` deriver：词 + 字符 3-gram 特征哈希
     （带符号哈希、次线性 tf、L2 归一）——真实词法嵌入（非演示级；
     语义模型经注入面接入）。
3. **deriver**：``image_ocr`` / ``audio_asr`` 解析注册引擎、产出带
   method/词表/字符集溯源的 JSON；引擎未注册 fail-closed。

诚实边界：参考实现是**封闭域真实识别**（不是通用语音/文字模型）——
输出 payload 自带 method/vocabulary/charset 溯源，消费方可判别。
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import wave
from collections import Counter
from typing import Any, Protocol

from vasta_protocols.errors import VastaError


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VastaError(code="derive.bad_params", message=message)


# ---- 注入面 ----

class OCREngine(Protocol):
    """OCR 引擎面：图像字节 + 参数 → {text, chars?, method, ...}。"""

    async def recognize(self, image: bytes, params: dict[str, Any]) -> dict[str, Any]:
        ...  # pragma: no cover


class ASREngine(Protocol):
    """ASR 引擎面：音频字节 + 参数 → {transcript, segments?, method, ...}。"""

    async def transcribe(self, audio: bytes, params: dict[str, Any]) -> dict[str, Any]:
        ...  # pragma: no cover


class EngineRegistry:
    """引擎注册表（ocr/asr）——可替换注入（升级参考实现为真实模型）。"""

    def __init__(self) -> None:
        self._engines: dict[str, Any] = {}

    def register(self, kind: str, engine: Any) -> None:
        """注册/替换（注入点语义：后注册者生效）。"""
        _require(kind in ("ocr", "asr"), f"引擎类别 {kind!r} 未知（ocr/asr）")
        self._engines[kind] = engine

    def get(self, kind: str) -> Any:
        engine = self._engines.get(kind)
        if engine is None:
            raise VastaError(
                code="derive.engine_unregistered",
                message=f"{kind} 引擎未注册（fail-closed）——注入面在 "
                        "vastacore.evidence.engines（GUI Pack/云模型接此）",
            )
        return engine

    def kinds(self) -> list[str]:
        return sorted(self._engines)


# ---- 参考实现：DTMF ASR（Goertzel）----

_DTMF_ROWS = (697.0, 770.0, 852.0, 941.0)
_DTMF_COLS = (1209.0, 1336.0, 1477.0, 1633.0)
_DTMF_DIGITS = (
    ("697", "1209", "1"), ("697", "1336", "2"), ("697", "1477", "3"),
    ("697", "1633", "A"), ("770", "1209", "4"), ("770", "1336", "5"),
    ("770", "1477", "6"), ("770", "1633", "B"), ("852", "1209", "7"),
    ("852", "1336", "8"), ("852", "1477", "9"), ("852", "1633", "C"),
    ("941", "1209", "*"), ("941", "1336", "0"), ("941", "1477", "#"),
    ("941", "1633", "D"),
)
_DTMF_MAP = {(int(lo), int(hi)): ch for lo, hi, ch in _DTMF_DIGITS}


def _goertzel_power(samples: list[float], freq: float, rate: int) -> float:
    n = len(samples)
    if n == 0:
        return 0.0
    k = round(n * freq / rate)
    if k == 0 or k > n // 2:
        return 0.0
    coeff = 2.0 * math.cos(2.0 * math.pi * k / n)
    s1 = s2 = 0.0
    for x in samples:
        s0 = x + coeff * s1 - s2
        s2, s1 = s1, s0
    return abs(s1 * s1 + s2 * s2 - coeff * s1 * s2)


def _wav_mono_samples(payload: bytes) -> tuple[list[float], int]:
    """WAV → 单声道归一化浮点采样（首声道；8/16/32-bit int PCM）。"""
    try:
        with wave.open(io.BytesIO(payload)) as src:
            _require(src.getcomptype() == "NONE",
                     f"非 PCM WAV（comptype={src.getcomptype()!r}）")
            nch, sw, fr = (src.getnchannels(), src.getsampwidth(),
                           src.getframerate())
            raw = src.readframes(src.getnframes())
    except wave.Error as exc:
        raise VastaError(
            code="derive.bad_params", message=f"源不是合法 WAV: {exc}"
        ) from exc
    import struct as _struct

    fmt = {1: "b", 2: "h", 4: "i"}.get(sw)
    _require(fmt is not None, f"不支持的字宽 {sw}（1/2/4 字节 int PCM）")
    values = _struct.unpack(f"<{len(raw) // sw}{fmt}", raw)
    scale = float(1 << (8 * sw - 1))
    mono = [v / scale for i, v in enumerate(values) if i % nch == 0]
    return mono, fr


class DtmfAsrEngine:
    """DTMF 双音检测（Goertzel）——封闭词表真实 ASR 参考实现。"""

    async def transcribe(self, audio: bytes,
                         params: dict[str, Any]) -> dict[str, Any]:
        samples, rate = _wav_mono_samples(audio)
        frame_len = max(1, int(rate * float(params.get("frame_s", 0.02))))
        min_frames = int(params.get("min_frames", 2))
        frame_digits: list[str | None] = []
        for start in range(0, len(samples) - frame_len + 1, frame_len):
            frame = samples[start:start + frame_len]
            energy = sum(x * x for x in frame) / frame_len
            if energy < 1e-6:  # 绝对静音门
                frame_digits.append(None)
                continue
            lows = {int(f): _goertzel_power(frame, f, rate) for f in _DTMF_ROWS}
            highs = {int(f): _goertzel_power(frame, f, rate) for f in _DTMF_COLS}
            lo = max(lows, key=lows.get)  # type: ignore[arg-type]
            hi = max(highs, key=highs.get)  # type: ignore[arg-type]
            # 组内占优门限：真双音在两组各占主导（离 bin 泄漏不吃掉主导位）
            if lows[lo] > sum(lows.values()) * 0.6 and \
                    highs[hi] > sum(highs.values()) * 0.6:
                frame_digits.append(_DTMF_MAP.get((lo, hi)))
            else:
                frame_digits.append(None)
        segments = []
        i = 0
        while i < len(frame_digits):
            digit = frame_digits[i]
            if digit is None:
                i += 1
                continue
            j = i
            while j < len(frame_digits) and frame_digits[j] == digit:
                j += 1
            if j - i >= min_frames:
                segments.append({
                    "digit": digit,
                    "from_s": round(i * frame_len / rate, 4),
                    "to_s": round(j * frame_len / rate, 4),
                })
            i = j
        return {
            "transcript": "".join(s["digit"] for s in segments),
            "segments": segments,
            "method": "dtmf-goertzel(closed-vocabulary)",
            "vocabulary": sorted({ch for _, _, ch in _DTMF_DIGITS}),
        }


# ---- 参考实现：模板 OCR（5×7 字形）----

_FONT5X7: dict[str, tuple[str, ...]] = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11111", "00010", "00100", "00010", "00001", "10001", "01110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11100", "10010", "10001", "10001", "10001", "10010", "11100"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "10001", "11001", "10101", "10011", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "00110", "00110"),
    ":": ("00000", "00110", "00110", "00000", "00110", "00110", "00000"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    "*": ("00100", "10101", "01110", "11111", "01110", "10101", "00100"),
    "#": ("01010", "11111", "01010", "01010", "01010", "11111", "01010"),
}


class TemplateOcrEngine:
    """5×7 字形模板匹配 OCR——封闭字符集真实识别参考实现。

    流程：PIL 解码 → 灰度 → 二值化（暗为墨）→ 行投影分割 → 列投影
    分割（空列即字符界、宽空隙为空格）→ bbox 缩放 5×7（NEAREST）→
    全字符集汉明距离匹配。确定性；抗噪边界如实标注（tolerance 内
    最优，否则 ``?``）。
    """

    tolerance = 10  # 35 像素中至多容忍 10 位失配

    async def recognize(self, image: bytes,
                        params: dict[str, Any]) -> dict[str, Any]:
        from PIL import Image

        try:
            img = Image.open(io.BytesIO(image)).convert("L")
        except Exception as exc:  # PIL 解码面广，统一收口
            raise VastaError(
                code="derive.bad_params", message=f"图像解码失败: {exc}"
            ) from exc
        width, height = img.size
        pixels = list(img.tobytes())  # 模式 L：每像素 1 字节
        lo, hi = min(pixels), max(pixels)
        threshold = float(params.get("threshold", (lo + hi) / 2))
        ink = [p < threshold for p in pixels]
        at = lambda x, y: ink[y * width + x]  # noqa: E731

        # 行分割
        row_ink = [any(at(x, y) for x in range(width)) for y in range(height)]
        lines: list[tuple[int, int]] = []
        y = 0
        while y < height:
            if row_ink[y]:
                y2 = y
                while y2 < height and row_ink[y2]:
                    y2 += 1
                if y2 - y >= 3:
                    lines.append((y, y2))
                y = y2
            else:
                y += 1
        _require(lines, "未检出行（空白图或阈值失当）")

        text_lines: list[str] = []
        chars: list[dict[str, Any]] = []
        space_ratio = float(params.get("space_ratio", 0.6))
        for (ly0, ly1) in lines:
            col_ink = [any(at(x, y) for y in range(ly0, ly1))
                       for x in range(width)]
            cells: list[tuple[int, int]] = []
            x = 0
            while x < width:
                if col_ink[x]:
                    x2 = x
                    while x2 < width and col_ink[x2]:
                        x2 += 1
                    cells.append((x, x2))
                    x = x2
                else:
                    x += 1
            # 空隙阈值相对字宽（中位宽 × ratio，下限 2）——原 1px 放大
            # N 倍后成为 N 列，固定阈值会把字间空隙误判为词空格
            widths = [x1 - x0 for x0, x1 in cells] or [5]
            med = sorted(widths)[len(widths) // 2]
            space_w = max(2, round(med * float(space_ratio)))
            pieces: list[str] = []
            prev_end: int | None = None
            for (cx0, cx1) in cells:
                if prev_end is not None and cx0 - prev_end >= space_w:
                    pieces.append(" ")
                match, confidence = self._match_cell(
                    ink, width, cx0, cx1, ly0, ly1)
                pieces.append(match)
                chars.append({
                    "char": match, "x0": cx0, "x1": cx1,
                    "y0": ly0, "y1": ly1, "confidence": round(confidence, 4),
                })
                prev_end = cx1
            text_lines.append("".join(pieces))
        return {
            "text": "\n".join(text_lines),
            "chars": chars,
            "method": "template-5x7(hamming,closed-charset)",
            "charset": sorted(_FONT5X7),
        }

    def _match_cell(
        self, ink: list[bool], width: int, x0: int, x1: int,
        y0: int, y1: int,
    ) -> tuple[str, float]:
        """bbox → 缩放 5×7 → 全字符集汉明匹配 → (char, confidence)。"""
        from PIL import Image as _Image

        cell_w, cell_h = x1 - x0, y1 - y0
        _require(cell_w >= 1 and cell_h >= 1, "空单元格（分割异常）")
        raw = bytes(
            0 if ink[y * width + x] else 255
            for y in range(y0, y1) for x in range(x0, x1)
        )
        img = _Image.frombytes("L", (cell_w, cell_h), raw)
        scaled = img.resize((5, 7), _Image.NEAREST)
        bits = [b < 128 for b in scaled.tobytes()]  # 行主序 5×7
        best_ch, best_miss, second_miss = "?", 36, 36
        for ch, rows in _FONT5X7.items():
            misses = sum(
                1
                for r in range(7)
                for c in range(5)
                if (rows[r][c] == "1") != bits[r * 5 + c]
            )
            if misses < best_miss:
                best_ch, second_miss, best_miss = ch, best_miss, misses
            elif misses < second_miss:
                second_miss = misses
        if best_miss > self.tolerance:
            return "?", 1 - best_miss / 35
        margin = (second_miss - best_miss) / 35
        return best_ch, min(1.0, 1 - best_miss / 35 + margin / 2)


# ---- 词法 embedding（真实，非演示）----

def _signed_hash(token: str, dim: int) -> tuple[int, int]:
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") % dim
    sign = 1 if digest[8] & 1 else -1
    return bucket, sign


async def text_embedding_lexical(
    payload: bytes, params: dict[str, Any],
) -> bytes:
    """词 + 字符 3-gram 特征哈希嵌入（带符号、次线性 tf、L2 归一）。

    真实词法嵌入：可分词、可余弦比相似度（同词表近、异词表远）；
    语义级模型经 EngineRegistry 注入面接入（本 deriver 为零依赖基线）。
    """
    dim = int(params.get("dim", 256))
    _require(dim >= 8, f"dim 须 ≥8，得到 {dim}")
    text = payload.decode("utf-8", errors="replace")
    words = [w for w in text.lower().split() if w]
    features: Counter[str] = Counter()
    for w in words:
        features[f"w:{w}"] += 1
        padded = f"#{w}#"
        for i in range(len(padded) - 2):
            features[f"c:{padded[i:i + 3]}"] += 1
    vector = [0.0] * dim
    for token, tf in features.items():
        bucket, sign = _signed_hash(token, dim)
        vector[bucket] += sign * (1.0 + math.log(tf))
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    vector = [round(v / norm, 10) for v in vector]
    doc = {
        "vector": vector, "dim": dim,
        "nnz": sum(1 for v in vector if v != 0.0),
        "words": len(words),
        "method": "feature-hashing(word+char3,signed,sublinear-tf,l2)",
    }
    return json.dumps(doc, ensure_ascii=False, sort_keys=True).encode()


# ---- deriver：解注册引擎 ----

async def image_ocr(payload: bytes, params: dict[str, Any]) -> bytes:
    """图像 → 注册 OCR 引擎（默认 TemplateOcrEngine）→ 溯源 JSON。"""
    engine = default_engines().get("ocr")
    result = await engine.recognize(payload, dict(params))
    return json.dumps(result, ensure_ascii=False, sort_keys=True).encode()


async def audio_asr(payload: bytes, params: dict[str, Any]) -> bytes:
    """音频 → 注册 ASR 引擎（默认 DtmfAsrEngine）→ 溯源 JSON。"""
    engine = default_engines().get("asr")
    result = await engine.transcribe(payload, dict(params))
    return json.dumps(result, ensure_ascii=False, sort_keys=True).encode()


_DEFAULT_ENGINES = EngineRegistry()
_DEFAULT_ENGINES.register("ocr", TemplateOcrEngine())
_DEFAULT_ENGINES.register("asr", DtmfAsrEngine())


def default_engines() -> EngineRegistry:
    """默认引擎注册表（参考实现已装；真实模型 register 替换即接）。"""
    return _DEFAULT_ENGINES


__all__ = [
    "ASREngine",
    "DtmfAsrEngine",
    "EngineRegistry",
    "OCREngine",
    "TemplateOcrEngine",
    "audio_asr",
    "default_engines",
    "image_ocr",
    "text_embedding_lexical",
]
