# MITRA Voice Assistant

MITRA is a minimal browser voice app. The browser sends microphone audio over WebRTC, the Python backend transcribes it (ElevenLabs Scribe v2 or Gemini), sends the transcript to Gemini, synthesizes the reply (ElevenLabs TTS or free Edge TTS), and returns audio over the same WebRTC session.

The UI only talks to the local MITRA server. Provider hosts and keys stay in `.env`.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Add the required values to `.env`:

```env
USE_DHWANI=False
ELEVENLABS_API_KEY=...
ELEVENLABS_STT_MODEL=scribe_v2
ELEVENLABS_TTS_MODEL=...
ELEVENLABS_TTS_VOICE_ID=...
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-3.1-flash-lite
APP_HOST=0.0.0.0
APP_PORT=8010
MITRA_LOGIN_PIN=1234
```

### Free setup (no ElevenLabs key)

MITRA can run with only a free Gemini API key from https://aistudio.google.com/apikey:

```env
STT_PROVIDER=gemini
TTS_PROVIDER=edge
EDGE_TTS_VOICE=hi-IN-SwaraNeural
GEMINI_API_KEY=...
```

- `STT_PROVIDER=gemini` transcribes the driver's audio with the same Gemini model and key.
- `TTS_PROVIDER=edge` speaks replies with Microsoft Edge's free online neural voices via `edge-tts` (no key). `hi-IN-SwaraNeural` is female, `hi-IN-MadhurNeural` is male.
- Both default to `elevenlabs` when unset. Edge TTS uses an unofficial endpoint, so treat it as a development option.

## Run

```powershell
.\.venv\Scripts\Activate.ps1
python server.py
```

Open:

```text
http://127.0.0.1:8010
```

Login with the PIN from `.env`, then tap the MITRA mic once to start the conversation. The app keeps one live WebRTC session open, keeps listening after each reply, sends a turn after a natural pause, shows transcripts, and plays MITRA's answer back through WebRTC until you end the session. If you start speaking while MITRA is replying, MITRA automatically stops and listens.

This workspace uses `8010` because VS Code is already listening on `127.0.0.1:8000`. Change `APP_PORT` if you want a different port.

## Prompt

The active Gemini system prompt is stored in code at `app/llm_gemini.py` and documented at:

```text
docs/mitra-system-prompt.md
```

It forces MITRA replies into short, speakable Hinglish in Devanagari script with the highway companion tone from the supplied docs.

## Healthcare Escalation (Dhwani call)

MITRA is not a doctor. When a driver reports a health problem, MITRA responds with
empathy and basic self-care, then asks if they want to talk to the Healthcare Support
team. The escalation uses Gemini **tool calling**: only after the driver clearly
confirms does Gemini invoke `request_healthcare_call`, and only then does the server
act on the driver's chosen calling preference.

### Calling preference

Before starting, the driver picks one of three options in the UI. The choice is sent to
the server on connect and **locked for the rest of the conversation** (radios disable
once the session starts); MITRA is told which mode is active so its wording matches.

1. **Receive call from AI Agent** — Dhwani places an outbound AI-agent call to the
   driver's number, followed by the "did you receive the call?" confirm + 30s retry flow.
2. **Receive call from Human Agent** — a single Acefone `click_to_call` bridge rings the
   human agent (`HUMAN_AGENT_NUMBER`) and the driver and connects them directly. MITRA
   then shows the confirm popup and goes quiet so the driver and agent can talk; tap the
   mic to bring MITRA back.
3. **Call Human Agent** — the browser opens `tel:<HUMAN_AGENT_NUMBER>` so the driver taps
   to dial directly. MITRA goes quiet.

> Note on the Human Agent bridge: it uses `/v1/click_to_call` (Bearer auth) which bridges
> `agent_number` + `destination_number` in one call. Acefone **cannot bridge a number to
> itself**, so `HUMAN_AGENT_NUMBER` must differ from `HEALTHCARE_DRIVER_NUMBER` — otherwise
> the call fails fast with a clear message. (The earlier `click_to_call_support` +
> `/call/options` transfer path was dropped: the transfer needs the live call id from a
> webhook, not the originate-response id, so it always returned "Invalid Call ID".)

Flow:

1. Driver reports an issue -> MITRA gives empathy + self-care, then asks to connect.
2. Driver says yes -> MITRA asks "abhi ya thodi der baad?".
3. "Abhi" -> Gemini calls the tool with `timing=now`. MITRA first speaks a short
   "ruko, main call jod rahi hoon" line while the call is placed, then confirms.
4. "Thodi der baad" -> `timing=later`; MITRA remembers. When the driver later says
   "doctor se baat karwa do", MITRA connects without asking again.

After the call is placed, MITRA **pauses** and a popup asks "Kya aapko call aa gayi?"
with a 30s window that starts the moment the call is placed:

- **Haan** (or "Call aa gayi") -> MITRA stays paused while the driver is on the call.
  Tap the mic to resume MITRA afterwards.
- **Nahi** -> a countdown shows the remaining time. If the call still has not arrived
  when it hits 0, MITRA resumes with the context that the call was not received,
  apologizes, and offers to try again.

Config (`.env`):

```env
HEALTHCARE_ENABLED=True
DHWANI_CALL_API_KEY=...
DHWANI_CALL_BASE_URL=https://dhwani.timbleglance.com
DHWANI_CALL_AGENT=default
HEALTHCARE_DRIVER_NUMBER=6265833992
HEALTHCARE_SUPPORT_NUMBER=8920530832
```

Testing note: Dhwani places the call to `HEALTHCARE_DRIVER_NUMBER` and handles the
driver side itself. `HEALTHCARE_SUPPORT_NUMBER` (8920530832) is conceptual only and is
**not** dialed during testing. If `DHWANI_CALL_API_KEY` is missing, the tool is disabled
and MITRA falls back to normal calm conversation.

## WebSocket Contract

The active endpoint is:

```text
/ws/session
```

Inbound:

```json
{"type":"offer","sdp":"..."}
{"type":"ice","candidate":{}}
{"type":"call_preference","value":"ai_agent"}
{"type":"transcript","text":"..."}
{"type":"healthcare.confirm","received":true}
```

Outbound:

```json
{"type":"answer","sdp":"..."}
{"type":"transcript.final","text":"..."}
{"type":"assistant.final","text":"..."}
{"type":"healthcare.call.connecting"}
{"type":"healthcare.call.queued","call_id":"...","status":"QUEUED"}
{"type":"healthcare.call.await_confirm","timeout_ms":30000}
{"type":"healthcare.call.paused","hint":"..."}
{"type":"healthcare.call.open_dialer","number":"..."}
{"type":"healthcare.call.deferred"}
{"type":"healthcare.call.failed","message":"..."}
{"type":"error","message":"..."}
{"type":"closed"}
```

## Mind Check storage

There is no database. Mind Check results are kept in the browser's localStorage and the `/dashboard` reads them from there.

## Logs

Runtime logs are written to:

```text
logs/mitra.log
```

Errors include the session id, pipeline stage, and provider message.

## Legacy Dhwani Toggle

The previous Dhwani bridge is preserved in `app/dhwani_legacy.py`. Keep this off for the local WebRTC pipeline:

```env
USE_DHWANI=False
```

Set `USE_DHWANI=True` only if you intentionally want to run the old Dhwani bridge with the existing `MITRA_*` variables.
