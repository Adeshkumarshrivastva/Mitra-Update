from __future__ import annotations

import asyncio
import base64
import json
from urllib import parse, request

from .llm_gemini import _open_json


NO_SPEECH_MARKER = "NO_SPEECH"
TRANSCRIBE_PROMPT = (
    "Transcribe this voice clip from an Indian truck driver exactly as spoken. "
    "Write Hindi words in Devanagari script and English words in English. Do not translate or reply. "
    "Output only the transcript text, with no quotes, labels, or notes. "
    f"If there is no clear human speech, output exactly {NO_SPEECH_MARKER}"
)


class GeminiSTT:
    """Speech-to-text through Gemini audio understanding, using the same key as the LLM."""

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    async def transcribe_wav(self, wav_bytes: bytes) -> str:
        return await asyncio.to_thread(self._transcribe_wav_sync, wav_bytes)

    def _transcribe_wav_sync(self, wav_bytes: bytes) -> str:
        model_path = parse.quote(self.model, safe="")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_path}:generateContent?key={parse.quote(self.api_key, safe='')}"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": TRANSCRIBE_PROMPT},
                        {
                            "inline_data": {
                                "mime_type": "audio/wav",
                                "data": base64.b64encode(wav_bytes).decode("ascii"),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 512},
        }
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        return parse_transcript(_open_json(req, timeout=90))


def parse_transcript(payload: dict) -> str:
    """Return the transcript, or an empty string when Gemini heard no speech."""
    texts = [
        part.get("text", "")
        for candidate in payload.get("candidates", [])
        for part in candidate.get("content", {}).get("parts", [])
    ]
    transcript = " ".join(text.strip() for text in texts if text and text.strip()).strip()
    if transcript.strip(" .").upper() == NO_SPEECH_MARKER:
        return ""
    return transcript
