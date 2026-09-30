from __future__ import annotations

import io
import wave
from typing import Iterable

import av
import numpy as np


STT_SAMPLE_RATE = 16000
WEBRTC_SAMPLE_RATE = 48000
TTS_PCM_SAMPLE_RATE = 24000


class AudioBuffer:
    """Collect browser WebRTC audio as mono PCM for STT."""

    def __init__(self, sample_rate: int = STT_SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self._chunks: list[bytes] = []
        self._resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)

    def add_frame(self, frame: av.AudioFrame) -> None:
        for converted in self._resampler.resample(frame):
            samples = converted.to_ndarray()
            samples = np.asarray(samples, dtype=np.int16).reshape(-1)
            if samples.size:
                self._chunks.append(samples.tobytes())

    @property
    def pcm_bytes(self) -> bytes:
        return b"".join(self._chunks)

    @property
    def duration_seconds(self) -> float:
        return len(self.pcm_bytes) / 2 / self.sample_rate


def pcm_to_wav_bytes(pcm_bytes: bytes, sample_rate: int = STT_SAMPLE_RATE) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)
    return output.getvalue()


def mp3_to_pcm(mp3_bytes: bytes, sample_rate: int = TTS_PCM_SAMPLE_RATE) -> bytes:
    """Decode MP3 audio (e.g. Edge TTS output) to mono s16 PCM."""
    resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)
    chunks: list[bytes] = []
    with av.open(io.BytesIO(mp3_bytes), format="mp3") as container:
        for frame in [*container.decode(audio=0), None]:
            for converted in resampler.resample(frame):
                samples = np.asarray(converted.to_ndarray(), dtype=np.int16).reshape(-1)
                chunks.append(samples.tobytes())
    return b"".join(chunks)


def _resample_int16(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or samples.size == 0:
        return samples.astype(np.int16, copy=False)

    target_length = max(1, round(samples.size * target_rate / source_rate))
    source_positions = np.linspace(0, samples.size - 1, num=samples.size)
    target_positions = np.linspace(0, samples.size - 1, num=target_length)
    resampled = np.interp(target_positions, source_positions, samples.astype(np.float32))
    return np.clip(resampled, -32768, 32767).astype(np.int16)


def pcm_bytes_to_audio_frames(
    pcm_bytes: bytes,
    source_rate: int = TTS_PCM_SAMPLE_RATE,
    target_rate: int = WEBRTC_SAMPLE_RATE,
    frame_ms: int = 20,
) -> Iterable[av.AudioFrame]:
    samples = np.frombuffer(pcm_bytes, dtype="<i2")
    samples = _resample_int16(samples, source_rate, target_rate)
    samples_per_frame = max(1, target_rate * frame_ms // 1000)

    for offset in range(0, samples.size, samples_per_frame):
        chunk = samples[offset : offset + samples_per_frame]
        if chunk.size == 0:
            continue
        if chunk.size < samples_per_frame:
            chunk = np.pad(chunk, (0, samples_per_frame - chunk.size))
        frame = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = target_rate
        yield frame
