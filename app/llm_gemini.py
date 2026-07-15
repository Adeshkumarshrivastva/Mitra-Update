from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
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

Healthcare support flow:
- MITRA is not a doctor. Your job is to keep the saathi calm, suggest basic self-care, and connect them to the Healthcare Support team when they want it.
- When the saathi reports a health problem (thakan, sir dard, stress, ghabrahat, chakkar, halka bukhar, body pain, etc.):
  1. Show empathy calmly. Do not create panic.
  2. Suggest simple self-care: aaram, paani, halka khana, gehri saans, surakshit jagah par ruk jana.
  3. Then ask once: "अगर इसके बाद भी ठीक न लगे तो मैं डॉक्टर से आपकी बात करवा सकती हूँ। क्या आप डॉक्टर से बात करना चाहेंगे?"
- If the saathi says haan/yes: ask "क्या आप अभी बात करना चाहेंगे या थोड़ी देर बाद?"
- Only when the saathi clearly confirms they want the call NOW (abhi, haan abhi, kar do, jod do): call the tool request_healthcare_call with timing="now" and a short issue_summary. In the SAME reply also speak one short calm line telling them to wait, for example: "ठीक है भाई, एक सेकंड रुकिए, मैं अभी कॉल जोड़ रही हूँ।" Never call the tool before the saathi has confirmed.
- If the saathi says thodi der baad / journey ke baad / abhi nahi: call request_healthcare_call with timing="later", and reassure them, for example: "बिलकुल, जब भी आप कहेंगे मैं उसी समय डॉक्टर से आपकी बात करवा दूँगी।"
- If earlier the saathi deferred the call and now says "डॉक्टर से बात करवा दो" (or similar), do NOT ask again: directly call request_healthcare_call with timing="now" plus the short wait line.
- Never diagnose an illness. Never suggest, name, or prescribe any medicine or dose. If asked which medicine to take, gently decline and offer to connect them to the healthcare team instead.
- Never invent or guess a phone number. Only ever say a phone number that the system has explicitly given you in a system note. If no number was given and the saathi asks for one, say you are getting it connected instead of making one up.

Final answer requirement:
- Every assistant reply must be directly speakable by TTS.
- Keep it lively, concise, and safe.
""".strip()


HEALTHCARE_CALL_TOOL = {
    "name": "request_healthcare_call",
    "description": (
        "Connect the driver to the Healthcare Support team via a phone call. "
        "Only use this AFTER the driver has clearly agreed to talk to a doctor and confirmed the timing. "
        "Never call it on a plain health complaint before the driver has said yes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "timing": {
                "type": "string",
                "enum": ["now", "later"],
                "description": (
                    "now = the driver wants to be connected immediately; "
                    "later = the driver wants the call after some time or after the journey."
                ),
            },
            "issue_summary": {
                "type": "string",
                "description": "Short plain-language summary of the driver's health concern for the healthcare team.",
            },
        },
        "required": ["timing"],
    },
}


@dataclass
class LLMResult:
    text: str
    function_call: dict | None = None


class GeminiLLM:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    async def generate(
        self,
        conversation_messages: list[dict[str, str]],
        user_profile: dict[str, str] | None = None,
        healthcare_enabled: bool = False,
        healthcare_deferred: bool = False,
        call_preference: str = "ai_agent",
        call_number: str = "",
    ) -> LLMResult:
        return await asyncio.to_thread(
            self._generate_sync,
            conversation_messages,
            user_profile,
            healthcare_enabled,
            healthcare_deferred,
            call_preference,
            call_number,
        )

    def _generate_sync(
        self,
        conversation_messages: list[dict[str, str]],
        user_profile: dict[str, str] | None = None,
        healthcare_enabled: bool = False,
        healthcare_deferred: bool = False,
        call_preference: str = "ai_agent",
        call_number: str = "",
    ) -> LLMResult:
        model_path = parse.quote(self.model, safe="")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_path}:generateContent?key={parse.quote(self.api_key, safe='')}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": _contents(
                conversation_messages, user_profile, healthcare_deferred, call_preference, call_number
            ),
            "generationConfig": {
                "temperature": 0.85,
                "maxOutputTokens": 220,
            },
        }
        if healthcare_enabled:
            payload["tools"] = [{"function_declarations": [HEALTHCARE_CALL_TOOL]}]
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        data = _open_json(req, timeout=90)
        text, function_call = _parse_response(data)
        if not text and function_call is None:
            raise RuntimeError("Gemini returned an empty assistant response")
        return LLMResult(text=text, function_call=function_call)


def _gemini_message(message: dict[str, str]) -> dict:
    role = "model" if message.get("role") == "assistant" else "user"
    return {"role": role, "parts": [{"text": message.get("content", "")}]}


def _preference_note(call_preference: str, call_number: str) -> str | None:
    if call_preference == "ai_agent":
        return (
            "System note: the driver's chosen support mode is AI AGENT. When they confirm, an AI "
            "healthcare agent will call the driver's phone. Speak naturally about connecting them. "
            "Do not read out any phone number."
        )
    if call_preference == "human_agent":
        return (
            "System note: the driver's chosen support mode is HUMAN AGENT. When they confirm, a real "
            "person from the healthcare team will be connected on a phone call. Reassure them a human "
            "will talk to them. Do not read out any phone number."
        )
    if call_preference == "call_human":
        number_line = (
            f"The healthcare number is {call_number}. If the driver asks which number to call, read "
            "out exactly this number, digit by digit, and never invent any other number."
            if call_number
            else "You have not been given a number; do not invent one."
        )
        return (
            "System note: the driver's chosen support mode is CALL HUMAN AGENT. When they confirm, you "
            "cannot dial for them; the app shows the healthcare number on their phone screen so they "
            f"can tap it to call. Tell them you are opening the number for them to tap. {number_line}"
        )
    return None


def _contents(
    conversation_messages: list[dict[str, str]],
    user_profile: dict[str, str] | None,
    healthcare_deferred: bool = False,
    call_preference: str = "ai_agent",
    call_number: str = "",
) -> list[dict]:
    contents = []
    preference_note = _preference_note(call_preference, call_number)
    if preference_note:
        contents.append({"role": "user", "parts": [{"text": preference_note}]})
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
    if healthcare_deferred:
        contents.append(
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "System note: the driver earlier chose to talk to the doctor LATER. "
                            "If the driver now asks to be connected, call request_healthcare_call "
                            "with timing=now immediately, without asking again."
                        )
                    }
                ],
            }
        )
    contents.extend(_gemini_message(message) for message in conversation_messages)
    return contents


def _parse_response(payload: dict) -> tuple[str, dict | None]:
    texts: list[str] = []
    function_call: dict | None = None
    for candidate in payload.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            text = part.get("text")
            if text:
                texts.append(text)
            call = part.get("functionCall")
            if call and function_call is None:
                function_call = {
                    "name": call.get("name", ""),
                    "args": call.get("args", {}) or {},
                }
    combined = " ".join(text.strip() for text in texts if text.strip()).strip()
    return combined, function_call


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
