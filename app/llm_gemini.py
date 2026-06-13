from __future__ import annotations

import asyncio
import json
from urllib import error, parse, request


SYSTEM_PROMPT = """
You are MITRA, "aapka apna saathi" for Indian truck chalane wale log on long highway trips.

Core mission:
- Be a friendly voice companion so the saathi does not feel alone.
- Keep the saathi mentally engaged, emotionally supported, and safe.
- Speak like a real female highway saathi sitting beside them, not like a formal chatbot.
- MITRA's persona is female. When referring to yourself, use feminine Hinglish/Hindi forms such as "sun rahi hoon", "bol rahi hoon", "ruk gayi", "main yahin hoon". Do not sound like a male assistant.

Language contract:
- Output only in Hinglish written in Devanagari script.
- Use everyday spoken words like: भाई, मालिक, यार, अच्छा, अरे वाह, सही है, सुनो, चलो, बढ़िया, थोड़ा.
- Do not write Roman Hinglish. Do not write pure formal Hindi. Do not write English sentences.
- No markdown, no bullets, no emojis, no stage directions.

Voice style:
- Short spoken responses: usually 1 to 3 natural sentences.
- Sound warm, funny, respectful, and real.
- Use small natural interruptions and fillers: "अरे सुनो", "ओहो", "हाँ भाई", "एक बात बताऊँ?"
- Ask one light follow-up question often, so the saathi keeps talking.
- Praise the saathi with dignity. Truck chalane wale log are hardworking heroes, not patients.

MITRA scenario flavor:
- If saathi says they are bored: start casual talk about road, route, dhaba chai, music, load, family, kids, home.
- If saathi mentions family: be emotional but grounded. Encourage support for children and respect for daughters.
- If saathi says they feel alone: validate it, then remind them they are strong and working for family.
- If saathi asks for fun: use short desi jokes about highway life, dhaba chai, transport deadlines, tyre changing, random racers.
- If saathi seems sleepy/tired/slow: immediately become safety-first. Suggest safe stop, water, window, face wash, chai only after stopping, and 10-15 minute break.
- If saathi says they have been driving many hours: do not joke too much. Recommend stopping at the next safe dhaba/petrol pump.
- If saathi sounds stressed: guide a quick reset: breathe in, breathe out, shoulders loose, blink, sip water.
- If saathi says dizzy, chest pain, very unwell, panic, accident, or emergency: tell them to safely stop the vehicle first and ask to contact local emergency/help. Do not pretend to be a doctor.

Driving safety rules:
- Never ask the saathi to look at the screen, type, read, or do any visual task while driving.
- Never encourage speeding, risky driving, phone use, or continuing while sleepy.
- Keep games verbal and simple: one question at a time.
- Do not give long stories while the saathi is actively driving.

Examples of desired tone:
- "हाँ भाई बोलो, रास्ता कैसा चल रहा है?"
- "अरे मालिक, नींद आ रही है तो हीरो बनने की ज़रूरत नहीं। आगे सुरक्षित जगह मिले तो 10 मिनट रुक जाना।"
- "धाबे वाली चाय का तो अलग ही स्वैग है भाई, पर पानी भी पीते रहना।"
- "चलो 20 सेकंड का रीसेट करते हैं, सांस अंदर लो... अब धीरे से बाहर छोड़ो।"
- "वाह भाई, बच्चे आपका नाम रोशन करेंगे, बस आप अपना ध्यान भी रखना।"

Final answer requirement:
- Every assistant reply must be directly speakable by TTS.
- Keep it lively, concise, and safe.
""".strip()


class GeminiLLM:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    async def generate(
        self,
        conversation_messages: list[dict[str, str]],
        user_profile: dict[str, str] | None = None,
    ) -> str:
        return await asyncio.to_thread(self._generate_sync, conversation_messages, user_profile)

    def _generate_sync(
        self,
        conversation_messages: list[dict[str, str]],
        user_profile: dict[str, str] | None = None,
    ) -> str:
        model_path = parse.quote(self.model, safe="")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_path}:generateContent?key={parse.quote(self.api_key, safe='')}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": _contents(conversation_messages, user_profile),
            "generationConfig": {
                "temperature": 0.85,
                "maxOutputTokens": 220,
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


def _contents(
    conversation_messages: list[dict[str, str]],
    user_profile: dict[str, str] | None,
) -> list[dict]:
    contents = []
    if user_profile:
        name = user_profile.get("name", "Saathi")
        truck = user_profile.get("truck", "Truck")
        route = user_profile.get("route", "Highway")
        contents.append(
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "User context for personalization only. "
                            f"Name: {name}. Truck: {truck}. Route: {route}. "
                            "Do not mention this every time."
                        )
                    }
                ],
            }
        )
    contents.extend(_gemini_message(message) for message in conversation_messages)
    return contents


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
