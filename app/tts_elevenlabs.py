from __future__ import annotations

import asyncio
import json
from urllib import error, parse, request


class ElevenLabsTTS:
    def __init__(self, api_key: str, model_id: str, voice_id: str) -> None:
        self.api_key = api_key
        self.model_id = model_id
        self.voice_id = voice_id

    async def synthesize_pcm(self, text: str) -> bytes:
        return await asyncio.to_thread(self._synthesize_pcm_sync, text)

    def _synthesize_pcm_sync(self, text: str) -> bytes:
        voice = parse.quote(self.voice_id, safe="")
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=pcm_24000"
        payload = {
            "text": text,
            "model_id": self.model_id,
        }
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "xi-api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "audio/pcm",
            },
        )
        try:
            with request.urlopen(req, timeout=90) as response:
                audio = response.read()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"ElevenLabs TTS HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"ElevenLabs TTS connection failed: {exc.reason}") from exc

        if not audio:
            raise RuntimeError("ElevenLabs TTS returned empty audio")
        return audio
