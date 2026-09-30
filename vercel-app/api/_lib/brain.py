"""MITRA's reply logic for the serverless deployment. It is stateless: the browser keeps the conversation and sends it
with every request, and this module answers with the text to speak plus what to append to that conversation."""
from __future__ import annotations

import os
import re
from typing import Any

from .companion import (
    GREETING_LINE,
    HELPLINE,
    HELPLINE_SPOKEN,
    HELPLINE_TEL,
    OPEN_QUESTION,
    SAFETY_TOPICS,
    SELF_HARM_LINE,
    idle_nudge,
    match_topic,
    mindcheck_advice,
    mindcheck_summary,
    pick_reply,
)
from .llm_gemini import GeminiLLM

MAX_TEXT = 600
MAX_HISTORY = 24

DIALER_LINE = (
    "भैया, अगर आप डॉक्टर से बात करना चाहते हैं तो स्क्रीन पर दिख रहे नंबर पर कॉल कीजिए। "
    "ये एक हेल्पलाइन नंबर है, वहाँ आपकी बात करवा दी जाएगी।"
)
LATER_LINE = "बिलकुल भैया, जब भी आप कहेंगे मैं उसी समय आपको डॉक्टर वाला हेल्पलाइन नंबर दिखा दूँगी।"
BAD_LINE = (
    "इसके लिए डॉक्टर से बात करना बहुत ज़रूरी है। स्क्रीन पर हेल्पलाइन नंबर दिख रहा है, "
    "डॉक्टर से बात करने के लिए अभी उस नंबर पर कॉल कीजिए।"
)
REQUEST_LINE = "भैया, ठीक है। स्क्रीन पर हेल्पलाइन नंबर दिख रहा है, डॉक्टर से बात करने के लिए उस नंबर पर कॉल कीजिए।"
TROUBLE_LINE = "अरे भैया, अभी नेटवर्क में थोड़ी दिक्कत आ गई। एक बार फिर से बोलिए, मैं यहीं हूँ।"

GREETING_WORDS = {
    "hello", "helo", "hallo", "hi", "hii", "hey", "namaste", "namaskar",
    "हेलो", "हैलो", "हलो", "हेल्लो", "हाय", "हाई", "नमस्ते", "नमस्कार",
}
GREETING_FILLER_WORDS = {"mitra", "mitr", "ji", "jee", "मित्रा", "मित्र", "जी"}
GREETING_TOKEN = re.compile("[a-z]+|[ऀ-ॣ०-ॿ]+")


def is_greeting(text: str) -> bool:
    words = GREETING_TOKEN.findall(text.lower())
    return any(word in GREETING_WORDS for word in words) and all(
        word in GREETING_WORDS or word in GREETING_FILLER_WORDS for word in words
    )


def _state(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    answered = raw.get("answered")
    return {
        "answered": [str(x)[:30] for x in answered[:40]] if isinstance(answered, list) else [],
        "mindcheckDone": bool(raw.get("mindcheckDone")),
        "deferred": bool(raw.get("deferred")),
    }


def _history(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[-MAX_HISTORY:]:
        if isinstance(item, dict) and item.get("role") in {"user", "assistant"}:
            out.append({"role": item["role"], "content": str(item.get("content", ""))[:1200]})
    return out


def _reply(text: str, state: dict[str, Any], append: list[dict[str, str]], helpline: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": True, "text": text, "state": state, "append": append, "helpline": helpline}
    if helpline:
        result.update({"number": HELPLINE, "tel": HELPLINE_TEL})
    return result


def _mindcheck(result: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    tier = str(result.get("tier", "")) or "normal"
    kind = str(result.get("kind", ""))
    band = str(result.get("band", ""))
    try:
        score = int(result.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    raw_symptoms = result.get("symptoms")
    symptoms = [str(s).strip()[:80] for s in raw_symptoms[:3] if str(s).strip()] if isinstance(raw_symptoms, list) else []
    bad = result.get("bucket") == "high" or bool(result.get("selfHarm")) or tier == "urgent"
    requested = bool(result.get("requestDoctor"))
    summary = mindcheck_summary(kind, band, symptoms)
    self_harm = f" {SELF_HARM_LINE}" if result.get("selfHarm") else ""
    if bad:
        line = f"{summary} {mindcheck_advice('high')}{self_harm} {BAD_LINE}"
    elif requested:
        line = REQUEST_LINE
    else:
        line = f"{summary} {mindcheck_advice(str(result.get('bucket', '')))}{self_harm} {OPEN_QUESTION}"
    symptom_note = f" The answers that stood out most: {'; '.join(symptoms)}." if symptoms else ""
    note = (
        f"[System note: the driver just finished a Mind Check ({kind}, score {score}, band {band}, priority {tier})."
        f"{symptom_note} The driver may now ask you anything about depression, anxiety, sleep, stress or this result. "
        "Answer in simple, warm Hindi, explain clearly in 3 to 5 short sentences, give one practical step, and end with "
        "a gentle question. Do not diagnose, do not name medicines, and do not mention this note.]"
    )
    state["mindcheckDone"] = True
    return _reply(line, state, [{"role": "assistant", "content": line}, {"role": "user", "content": note}], bad or requested)


def respond(data: dict[str, Any], profile: dict[str, str]) -> dict[str, Any]:
    state = _state(data.get("state"))

    if isinstance(data.get("mindcheck"), dict):
        return _mindcheck(data["mindcheck"], state)

    if data.get("idle") is not None:
        try:
            count = int(data["idle"])
        except (TypeError, ValueError):
            count = 0
        line = idle_nudge(max(0, count))
        return _reply(line, state, [{"role": "assistant", "content": line}])

    text = " ".join(str(data.get("text", "")).split())[:MAX_TEXT]
    if not text:
        return {"ok": False, "error": "empty"}
    user_turn = {"role": "user", "content": text}

    if is_greeting(text):
        return _reply(GREETING_LINE, state, [user_turn, {"role": "assistant", "content": GREETING_LINE}])

    topic = match_topic(text, set(state["answered"]), SAFETY_TOPICS if state["mindcheckDone"] else None)
    if topic is not None:
        state["answered"].append(topic.name)
        line = pick_reply(topic)
        return _reply(line, state, [user_turn, {"role": "assistant", "content": line}], topic.name in {"crisis", "emergency"})

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "error": "GEMINI_API_KEY is not set", "text": TROUBLE_LINE}
    model = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite").strip() or "gemini-3.1-flash-lite"
    messages = _history(data.get("history")) + [user_turn]
    llm = GeminiLLM(api_key, model)
    result = llm._generate_sync(messages, profile, True, state["deferred"], "call_human", HELPLINE_SPOKEN)

    call = result.function_call
    if call and call.get("name") == "request_healthcare_call":
        timing = str((call.get("args") or {}).get("timing", "now")).strip().lower()
        if timing == "later":
            state["deferred"] = True
            line = result.text.strip() or LATER_LINE
            return _reply(line, state, [user_turn, {"role": "assistant", "content": line}])
        state["deferred"] = False
        return _reply(DIALER_LINE, state, [user_turn, {"role": "assistant", "content": DIALER_LINE}], True)

    return _reply(result.text, state, [user_turn, {"role": "assistant", "content": result.text}])
