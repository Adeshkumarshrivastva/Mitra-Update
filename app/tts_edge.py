from __future__ import annotations

import asyncio

import edge_tts

from .audio import TTS_PCM_SAMPLE_RATE, mp3_to_pcm


class EdgeTTS:
    """Free Microsoft Edge online neural voices. No API key needed."""

    def __init__(self, voice: str) -> None:
        self.voice = voice

    async def synthesize_pcm(self, text: str) -> bytes:
        mp3_bytes = bytearray()
        try:
            async for chunk in edge_tts.Communicate(text, self.voice).stream():
                if chunk["type"] == "audio":
                    mp3_bytes.extend(chunk["data"])
        except Exception as exc:
            raise RuntimeError(f"Edge TTS failed: {exc}") from exc

        if not mp3_bytes:
            raise RuntimeError("Edge TTS returned empty audio")
        return await asyncio.to_thread(mp3_to_pcm, bytes(mp3_bytes), TTS_PCM_SAMPLE_RATE)
