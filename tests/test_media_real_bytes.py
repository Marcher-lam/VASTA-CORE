"""Story 8.16：音视频真实字节 + 识别引擎面（FR-015/016 收口）。

- audio_slice：WAV PCM 真实字节帧级切片（输出可独立播放、内容与源对帧）
- video_window：MP4 采样表解析——真实字节坐标可对源复核
- media_align：跨模态时间相交/对齐键配对
- audio_asr：DTMF Goertzel 真实转写（合成音频 → 键序列 + 分段时戳）
- image_ocr：5×7 模板匹配（字体渲染 → 原生与 ×3 缩放两档）
- text_embedding_lexical：词法嵌入余弦可分性 + 注入面 fail-closed
"""

from __future__ import annotations

import io
import json
import math
import struct
import wave

import pytest

from vasta_protocols.errors import VastaError
from vasta_storage import SqliteStorage
from vastacore.evidence.derive import default_registry, derive_on_demand
from vastacore.evidence.engines import (
    EngineRegistry,
    TemplateOcrEngine,
    default_engines,
)


@pytest.fixture
def store(tmp_path):
    s = SqliteStorage(tmp_path / "s")
    yield s
    s.close()

# ---- 夹具合成（零外部媒体文件——全部程序生成，确定性）----

def synth_wav(segments: list[tuple[tuple[float, float] | None, float]],
              *, rate: int = 8000, amp: float = 0.25) -> bytes:
    """合成 WAV：segments = [((低频, 高频) | None 静音, 时长秒)]。"""
    out = io.BytesIO()
    with wave.open(out, "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(rate)
        for tones, dur_s in segments:
            n = int(rate * dur_s)
            frames = bytearray()
            for i in range(n):
                t = i / rate
                value = 0.0
                if tones is not None:
                    for f in tones:
                        value += math.sin(2 * math.pi * f * t)
                    value *= amp / len(tones)
                frames += struct.pack("<h", int(value * 32767))
            dst.writeframes(bytes(frames))
    return out.getvalue()


def _box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + box_type + payload


def synth_mp4() -> tuple[bytes, list[bytes]]:
    """手搭最小 MP4：ftyp + mdat + moov（vide 单轨 4 样本，时基 1000）。

    返回 (mp4_bytes, sample_marker_bytes)——样本内容为可核对的标记字节。
    """
    samples = [f"SMPL-{i}!!".encode() for i in range(4)]  # 各 8 字节
    mdat_payload = b"".join(samples)
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2")
    mdat = _box(b"mdat", mdat_payload)
    sample_size, count = len(samples[0]), len(samples)
    mdat_data_offset = len(ftyp) + 8  # mdat 体起点（stco 指向它）
    mvhd = _box(b"mvhd", b"\x00" * 4 + struct.pack(">IIII", 0, 0, 1000, 2000)
                + b"\x00" * 80)  # v0：时基 1000、时长 2000（2s）
    hdlr = _box(b"hdlr", b"\x00" * 8 + b"vide" + b"\x00" * 12)
    stts = _box(b"stts", b"\x00" * 4 + struct.pack(">I", 1)
                + struct.pack(">II", count, 500))  # 每样本 500 tick（0.5s）
    stsz = _box(b"stsz", b"\x00" * 4
                + struct.pack(">II", sample_size, count))
    stsc = _box(b"stsc", b"\x00" * 4 + struct.pack(">I", 1)
                + struct.pack(">III", 1, count, 1))
    stco = _box(b"stco", b"\x00" * 4 + struct.pack(">I", 1)
                + struct.pack(">I", mdat_data_offset))
    stss = _box(b"stss", b"\x00" * 4 + struct.pack(">I", 1)
                + struct.pack(">I", 1))  # 样本 1 为关键帧
    stbl = _box(b"stbl", stts + stsz + stsc + stco + stss)
    minf = _box(b"minf", stbl)
    mdia = _box(b"mdia", hdlr + minf)
    trak = _box(b"trak", mdia)
    moov = _box(b"moov", mvhd + trak)
    return ftyp + mdat + moov, samples


def render_text(text: str, *, scale: int = 1) -> bytes:
    """用引擎同款 5×7 字体渲染 PNG（白底黑字；字间 1px、空格 3px，按 scale 放大）。"""
    from PIL import Image

    from vastacore.evidence.engines import _FONT5X7

    gap_char, gap_word = 1, 3
    width = 0
    for ch in text:
        width += (gap_word if ch == " " else 5) * scale + gap_char * scale
    height = 7 * scale + 2
    img = Image.new("L", (max(width, 1), height), 255)
    x = 0
    for ch in text:
        if ch == " ":
            x += gap_word * scale
        else:
            rows = _FONT5X7[ch]
            for r in range(7):
                for c in range(5):
                    if rows[r][c] == "1":
                        for dy in range(scale):
                            for dx in range(scale):
                                img.putpixel(
                                    (x + c * scale + dx, r * scale + dy), 0)
            x += 5 * scale
        x += gap_char * scale
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _derive(store, payload: bytes, kind: str, params: dict):
    sha = await store.save_artifact(payload, mime="application/octet-stream",
                                    source="test.media")
    return await derive_on_demand(store, sha, kind, params)


def _load(payload: bytes) -> dict:
    return json.loads(payload.decode())


class TestAudioSlice:
    async def test_slice_frames_match_source(self, store) -> None:
        payload = synth_wav([((440.0, 880.0), 2.0)])
        ref = await _derive(store, payload, "audio_slice",
                            {"from_s": 0.5, "to_s": 1.0})
        out = await store.get_artifact(ref.derived_sha256)
        with wave.open(io.BytesIO(out)) as sliced, \
                wave.open(io.BytesIO(payload)) as src:
            assert sliced.getnframes() == 4000  # 0.5s × 8000Hz
            assert (sliced.getframerate(), sliced.getnchannels(),
                    sliced.getsampwidth()) == (
                src.getframerate(), src.getnchannels(), src.getsampwidth())
            src.setpos(4000)
            assert sliced.readframes(4000) == src.readframes(4000)  # 对帧
        # 同参数幂等同址
        again = await _derive(store, payload, "audio_slice",
                              {"from_s": 0.5, "to_s": 1.0})
        assert again.derived_sha256 == ref.derived_sha256

    async def test_non_pcm_rejected(self, store) -> None:
        with pytest.raises(VastaError) as excinfo:
            await _derive(store, b"not-a-wav", "audio_slice", {})
        assert excinfo.value.code == "derive.bad_params"


class TestVideoWindow:
    async def test_real_byte_coordinates_verifiable(self, store) -> None:
        mp4, samples = synth_mp4()
        ref = await _derive(store, mp4, "video_window",
                            {"from_s": 0.4, "to_s": 1.6})
        result = _load(await store.get_artifact(ref.derived_sha256))
        track = result["tracks"][0]
        assert track["type"] == "vide"
        picked = [s for s in track["samples"]]
        assert [s["idx"] for s in picked] == [1, 2, 3]  # pts 0.5/1.0/1.5
        assert [s["pts_s"] for s in picked] == [0.5, 1.0, 1.5]
        assert picked[0]["keyframe"] is False  # 仅样本 1（idx 0）是关键帧
        # 真实字节坐标复核：按 offset/size 取源字节 == 样本标记
        for s in picked:
            got = mp4[s["offset"]:s["offset"] + s["size"]]
            assert got == samples[s["idx"]]

    async def test_non_mp4_rejected(self, store) -> None:
        with pytest.raises(VastaError) as excinfo:
            await _derive(store, b"\x00" * 64, "video_window", {})
        assert excinfo.value.code == "derive.bad_params"


class TestMediaAlign:
    async def test_overlap_and_key_alignment(self, store) -> None:
        window = json.dumps({
            "kind": "audio", "window": {"from_s": 0, "to_s": 100},
            "segments": [
                {"start": 0, "end": 30, "align": "intro"},
                {"start": 40, "end": 80, "align": "order"},
            ],
        }).encode()
        peer = [
            {"start": 20, "end": 50, "align": "intro"},
            {"start": 60, "end": 90, "align": "order"},
        ]
        ref = await _derive(store, window, "media_align", {"peer": peer})
        result = _load(await store.get_artifact(ref.derived_sha256))
        # 三对合法相交：intro(20,30) / 键不匹配(40,50) / order(60,80)
        assert result["pair_count"] == 3
        by_key = [p for p in result["pairs"] if "aligned_by_key" in p]
        assert {p["aligned_by_key"] for p in by_key} == {"intro", "order"}
        intro = next(p for p in by_key if p["aligned_by_key"] == "intro")
        assert intro["overlap"] == {"from_s": 20, "to_s": 30, "duration_s": 10}
        order = next(p for p in by_key if p["aligned_by_key"] == "order")
        assert order["overlap"]["from_s"] == 60
        cross = next(p for p in result["pairs"] if "aligned_by_key" not in p)
        assert cross["overlap"] == {"from_s": 40, "to_s": 50, "duration_s": 10}


class TestDtmfAsr:
    async def test_transcribe_digit_sequence(self, store) -> None:
        # "1"=697+1209, "2"=697+1336, "3"=697+1477
        tones = {
            "1": (697.0, 1209.0), "2": (697.0, 1336.0), "3": (697.0, 1477.0),
        }
        segments = []
        for d in "123":
            segments.append((tones[d], 0.08))
            segments.append((None, 0.06))  # 静音分隔
        payload = synth_wav(segments)
        ref = await _derive(store, payload, "audio_asr", {})
        result = _load(await store.get_artifact(ref.derived_sha256))
        assert result["transcript"] == "123"
        assert len(result["segments"]) == 3
        assert result["segments"][0]["digit"] == "1"
        assert result["segments"][0]["from_s"] == 0.0
        assert 0.12 < result["segments"][1]["from_s"] < 0.16  # 80ms 键 + 60ms 静音
        assert result["method"].startswith("dtmf-goertzel")

    async def test_silence_transcribes_empty(self, store) -> None:
        payload = synth_wav([(None, 0.5)])
        ref = await _derive(store, payload, "audio_asr", {})
        result = _load(await store.get_artifact(ref.derived_sha256))
        assert result["transcript"] == ""


class TestTemplateOcr:
    @pytest.mark.parametrize("scale", [1, 3])
    async def test_recognizes_rendered_text(self, store, scale) -> None:
        payload = render_text("VASTA 12", scale=scale)
        ref = await _derive(store, payload, "image_ocr", {})
        result = _load(await store.get_artifact(ref.derived_sha256))
        assert result["text"] == "VASTA 12"
        assert result["method"].startswith("template-5x7")
        assert all(c["confidence"] > 0.7 for c in result["chars"])

    async def test_engine_injection_replaces_default(self, store) -> None:
        class FakeOcr:
            async def recognize(self, image, params):
                return {"text": "INJECTED", "method": "fake"}

        engines = default_engines()
        engines.register("ocr", FakeOcr())
        try:
            payload = render_text("OK")
            ref = await _derive(store, payload, "image_ocr", {})
            result = _load(await store.get_artifact(ref.derived_sha256))
            assert result["text"] == "INJECTED"
        finally:
            engines.register("ocr", TemplateOcrEngine())

    def test_engine_unregistered_fail_closed(self) -> None:
        with pytest.raises(VastaError) as excinfo:
            EngineRegistry().get("ocr")
        assert excinfo.value.code == "derive.engine_unregistered"


class TestLexicalEmbedding:
    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True)) / (
            math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))

    async def test_similarity_separates_lexically_related(self, store) -> None:
        texts = ["订单 已 完成 发货", "订单 已 完成 退货", "量子 波函数 坍缩"]
        vectors = []
        for text in texts:
            ref = await _derive(store, text.encode(), "text_embedding_lexical",
                                {"dim": 128})
            doc = _load(await store.get_artifact(ref.derived_sha256))
            vectors.append(doc["vector"])
            assert doc["method"].startswith("feature-hashing")
            assert abs(math.sqrt(sum(v * v for v in doc["vector"])) - 1.0) < 1e-6
        sim_related = self._cosine(vectors[0], vectors[1])
        sim_unrelated = self._cosine(vectors[0], vectors[2])
        assert sim_related > 0.5, "词法相关应对显著为正"
        assert sim_unrelated < sim_related - 0.3, "词法无关应对显著更低"


class TestRegistrySurface:
    def test_default_registry_extended(self) -> None:
        kinds = default_registry().kinds()
        # 8.12 四件 + 8.16 六件
        assert set(kinds) >= {
            "text_summary", "text_embedding", "text_extract", "media_window",
            "audio_slice", "video_window", "media_align",
            "image_ocr", "audio_asr", "text_embedding_lexical",
        }
