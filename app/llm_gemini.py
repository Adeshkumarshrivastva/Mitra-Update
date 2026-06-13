from __future__ import annotations

import asyncio
import json
from urllib import error, parse, request


SYSTEM_PROMPT = "You are a concise voice assistant. Answer naturally in short spoken responses."


class GeminiLLM:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    async def generate(self, conversation_messages: list[dict[str, str]]) -> str:
        return await asyncio.to_thread(self._generate_sync, conversation_messages)

    def _generate_sync(self, conversation_messages: list[dict[str, str]]) -> str:
        model_path = parse.quote(self.model, safe="")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_path}:generateContent?key={parse.quote(self.api_key, safe='')}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [_gemini_message(message) for message in conversation_messages],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 180,
            },
        }
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        data = _open_json(req, timeout=90)
        text = _extract_text(data)
        if not text:
            raise RuntimeError("Gemini returned an empty assistant response")
        return text


def _gemini_message(message: dict[str, str]) -> dict:
    role = "model" if message.get("role") == "assistant" else "user"
    return {"role": role, "parts": [{"text": message.get("content", "")}]}


def _extract_text(payload: dict) -> str:
    texts: list[str] = []
    for candidate in payload.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            text = part.get("text")
            if text:
                texts.append(text)
    return " ".join(text.strip() for text in texts if text.strip()).strip()


def _open_json(req: request.Request, timeout: int) -> dict:
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
    except error.HTTPError as exc:
        raw = exc.read()
        detail = raw.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Gemini HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Gemini connection failed: {exc.reason}") from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        detail = raw.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Gemini returned non-JSON response: {detail}") from exc
