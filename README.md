# MITRA Voice Assistant

MITRA is a minimal browser voice app. The browser sends microphone audio over WebRTC, the Python backend transcribes it with ElevenLabs Scribe v2, sends the transcript to Gemini, synthesizes the reply with ElevenLabs TTS, and returns audio over the same WebRTC session.

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

## WebSocket Contract

The active endpoint is:

```text
/ws/session
```

Inbound:

```json
{"type":"offer","sdp":"..."}
{"type":"ice","candidate":{}}
```

Outbound:

```json
{"type":"answer","sdp":"..."}
{"type":"transcript.final","text":"..."}
{"type":"assistant.final","text":"..."}
{"type":"error","message":"..."}
{"type":"closed"}
```

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
