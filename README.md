# MITRA Voice Assistant

A minimal voice-to-voice web demo for MITRA. The browser records speech, the local Python backend calls the configured voice agent from `.env`, and the browser speaks the returned reply.

## Run

```powershell
python server.py
```

Open:

```text
http://127.0.0.1:5173
```

Tap the mic and speak. Chrome or Edge is recommended for microphone speech recognition.

Do not run `python -m http.server`; that only serves static files and will not create MITRA's voice bridge.

## Check The Agent

Check connection up to the `ready` frame:

```powershell
python server.py --check
```

Check whether the configured agent can answer a test message:

```powershell
python server.py --check-turn
```

The web UI runs the same answer check on load. If the configured agent returns an error, the mic will retry the check instead of recording a driver turn.

## Logs

Runtime logs are printed in the terminal and written to:

```text
logs/mitra.log
```

Open the browser DevTools Console to see frontend state logs such as mic listening, transcript capture, API calls, and speech playback errors.

## Config

Edit `.env` if needed:

```text
MITRA_AGENT_WS_URL=...
MITRA_AGENT_NAME=default
MITRA_USER_NAME=Rahul
MITRA_GREETING=true
MITRA_PORT=5173
```
