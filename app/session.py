from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from aiohttp import web
from aiortc import RTCPeerConnection
from aiortc.mediastreams import MediaStreamError, MediaStreamTrack

from .companion import (
    GREETING_LINE,
    HELPLINE,
    HELPLINE_SPOKEN,
    HELPLINE_TEL,
    IDLE_NUDGE_SECONDS,
    MAX_IDLE_NUDGES,
    OPEN_QUESTION,
    SAFETY_TOPICS,
    SELF_HARM_LINE,
    idle_nudge,
    match_topic,
    mindcheck_advice,
    mindcheck_summary,
    pick_reply,
)
from .audio import AudioBuffer, TTS_PCM_SAMPLE_RATE, pcm_to_wav_bytes
from .dhwani_calls import DhwaniCallClient, DhwaniCallError
from .dialer_calls import DialerCallClient, DialerCallError
from .llm_gemini import GeminiLLM
from .settings import DOCTOR_CALL_STATIC, DOCTOR_IVR_NUMBER, Settings
from .stt_elevenlabs import ElevenLabsSTT
from .stt_gemini import GeminiSTT
from .tts_edge import EdgeTTS
from .tts_elevenlabs import ElevenLabsTTS
from .webrtc import QueuedAudioTrack, accept_offer, add_browser_ice, close_peer_connection, create_peer_connection


logger = logging.getLogger("mitra.session")

MAX_CAPTURE_SECONDS = 12.0
MIN_CAPTURE_SECONDS = 0.25
DANDA = "\u0964"
TTS_SENTENCE_PATTERN = re.compile(f"([^.!?{DANDA}]+[.!?{DANDA}]?)")
TTS_SINGLE_CALL_CHAR_LIMIT = 520
TTS_MAX_CHARS = 420
TTS_PRE_SILENCE_MS = 70
TTS_POST_SILENCE_MS = 130

HEALTHCARE_CALL_TOOL_NAME = "request_healthcare_call"
HEALTHCARE_CONFIRM_TIMEOUT_MS = 30000
HEALTHCARE_WAIT_LINE = "ठीक है भाई, एक सेकंड रुकिए, मैं अभी कॉल जोड़ रही हूँ।"
HEALTHCARE_SUCCESS_LINE = "कॉल जोड़ दी है, अभी आपके पास कॉल आ रही है, थोड़ा रुकिए।"
HEALTHCARE_FAIL_LINE = "अरे, अभी कॉल जुड़ नहीं पाई। आप चिंता मत कीजिए, थोड़ी देर में मैं फिर कोशिश करती हूँ।"
HEALTHCARE_LATER_LINE = "बिलकुल, जब भी आप कहेंगे मैं उसी समय डॉक्टर से आपकी बात करवा दूँगी।"
HEALTHCARE_DEFAULT_INSTRUCTIONS = (
    "Driver ne health se judi pareshani batayi hai. Unhe calm rakho, basic self-care batao, "
    "diagnosis ya dawai mat batao, aur zarurat ho to healthcare support team se connect karo."
)

CALL_PREF_AI_AGENT = "ai_agent"
CALL_PREF_HUMAN_AGENT = "human_agent"
CALL_PREF_CALL_HUMAN = "call_human"
CALL_PREFERENCES = {CALL_PREF_AI_AGENT, CALL_PREF_HUMAN_AGENT, CALL_PREF_CALL_HUMAN}

HEALTHCARE_HUMAN_SUCCESS_LINE = "कॉल जोड़ दी है, हमारी हेल्थकेयर टीम अभी आपसे बात करेगी, थोड़ा रुकिए।"
HEALTHCARE_HUMAN_PAUSE_HINT = "आप बात कर लीजिए, मैं चुप रहती हूँ। ज़रूरत हो तो माइक दबाइएगा।"
HEALTHCARE_DIALER_LINE = (
    "भैया, अगर आप डॉक्टर से बात करना चाहते हैं तो स्क्रीन पर दिख रहे नंबर पर कॉल कीजिए। "
    "ये एक हेल्पलाइन नंबर है, वहाँ आपकी बात करवा दी जाएगी।"
)

MINDCHECK_LOG_NAME = "mindcheck_escalations.jsonl"
MINDCHECK_BAD_LINE = (
    "इसके लिए डॉक्टर से बात करना बहुत ज़रूरी है। स्क्रीन पर हेल्पलाइन नंबर दिख रहा है, "
    "डॉक्टर से बात करने के लिए अभी उस नंबर पर कॉल कीजिए।"
)
MINDCHECK_REQUEST_LINE = (
    "भैया, ठीक है। स्क्रीन पर हेल्पलाइन नंबर दिख रहा है, डॉक्टर से बात करने के लिए उस नंबर पर कॉल कीजिए।"
)
MINDCHECK_CALL_INSTRUCTIONS = (
    "Driver ka Mind Check result bahut kharab aaya hai (score {score}, {band}). "
    "Doctor se turant baat karwana zaroori hai."
)

# A plain hello ("hello mitra", "नमस्ते मित्रा जी") gets the fixed, instant welcome from companion.py instead of a model reply.
GREETING_WORDS = {
    "hello", "helo", "hallo", "hi", "hii", "hey", "namaste", "namaskar",
    "हेलो", "हैलो", "हलो", "हेल्लो", "हाय", "हाई", "नमस्ते", "नमस्कार",
}
GREETING_FILLER_WORDS = {"mitra", "mitr", "ji", "jee", "मित्रा", "मित्र", "जी"}
# Latin words, or Devanagari runs without the danda punctuation marks.
GREETING_TOKEN = re.compile("[a-z]+|[ऀ-ॣ०-ॿ]+")


@dataclass
class VoiceSession:
    settings: Settings
    ws: web.WebSocketResponse
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    peer_connection: RTCPeerConnection | None = None
    incoming_audio_track: MediaStreamTrack | None = None
    outgoing_audio_track: QueuedAudioTrack | None = None
    conversation_messages: list[dict[str, str]] = field(default_factory=list)
    user_profile: dict[str, str] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: datetime | None = None
    _closed: bool = False
    _error_sent: bool = False
    _audio_reader_started: bool = False
    _capture_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _capturing: bool = False
    _current_audio: AudioBuffer | None = None
    _current_frames: int = 0
    _turn_seq: int = 0
    _processing_task: asyncio.Task | None = None
    _playback_done: asyncio.Event | None = None
    _healthcare_call_deferred: bool = False
    call_preference: str = CALL_PREF_AI_AGENT
    _preference_locked: bool = False
    _topics_answered: set[str] = field(default_factory=set)
    _idle_task: asyncio.Task | None = None
    _idle_nudges: int = 0
    _on_call: bool = False
    _mindcheck_done: bool = False
    _last_activity: float = field(default_factory=time.monotonic)

    async def handle_offer(self, sdp: str) -> str:
        self.settings.require_voice_pipeline()
        self.peer_connection, self.outgoing_audio_track = await create_peer_connection(
            self._on_audio_track,
            self._on_connection_state,
            self.settings.ice_servers,
        )
        logger.info("session.offer session_id=%s", self.session_id)
        answer_sdp = await accept_offer(self.peer_connection, sdp)
        logger.info("session.answer session_id=%s", self.session_id)
        if self._idle_task is None:
            self._idle_task = asyncio.create_task(self._idle_loop())
        return answer_sdp

    async def handle_ice(self, candidate: dict[str, Any] | None) -> None:
        if self.peer_connection is None:
            logger.debug("session.ice ignored_no_peer session_id=%s", self.session_id)
            return
        await add_browser_ice(self.peer_connection, candidate)

    def set_call_preference(self, value: str) -> None:
        if self._preference_locked:
            logger.info(
                "session.call_preference locked ignored session_id=%s value=%s current=%s",
                self.session_id,
                value,
                self.call_preference,
            )
            return
        if value in CALL_PREFERENCES:
            self.call_preference = value
            logger.info("session.call_preference session_id=%s value=%s", self.session_id, value)

    async def start_turn(self) -> None:
        if self._closed:
            return
        # First real turn locks the preference for the rest of the conversation.
        self._preference_locked = True
        if self._processing_task is not None and not self._processing_task.done():
            await self.send_event({"type": "turn.busy"})
            return
        async with self._capture_lock:
            self._turn_seq += 1
            self._capturing = True
            self._current_audio = AudioBuffer()
            self._current_frames = 0
            logger.info("turn.start session_id=%s turn=%s", self.session_id, self._turn_seq)
        await self.send_event({"type": "turn.started"})

    async def stop_turn(self, reason: str = "client") -> None:
        audio: AudioBuffer | None
        frames: int
        turn_id: int
        async with self._capture_lock:
            if not self._capturing:
                return
            self._capturing = False
            audio = self._current_audio
            frames = self._current_frames
            turn_id = self._turn_seq
            self._current_audio = None
            self._current_frames = 0

        if audio is None:
            return

        logger.info(
            "turn.stop session_id=%s turn=%s reason=%s frames=%s seconds=%.2f bytes=%s",
            self.session_id,
            turn_id,
            reason,
            frames,
            audio.duration_seconds,
            len(audio.pcm_bytes),
        )
        if not audio.pcm_bytes or audio.duration_seconds < MIN_CAPTURE_SECONDS:
            await self.send_event({"type": "turn.empty", "message": "No speech heard"})
            return
        if reason == "no_speech":
            logger.info("turn.discard_no_speech session_id=%s turn=%s", self.session_id, turn_id)
            return

        self._processing_task = asyncio.create_task(self._process_turn(audio.pcm_bytes, audio.sample_rate, turn_id))

    async def cancel_turn(self, reason: str = "client") -> None:
        async with self._capture_lock:
            if not self._capturing:
                return
            logger.info("turn.cancel session_id=%s turn=%s reason=%s", self.session_id, self._turn_seq, reason)
            self._capturing = False
            self._current_audio = None
            self._current_frames = 0

    async def handle_browser_transcript(self, text: str) -> None:
        """Start a turn from speech already recognized in the browser (STT_PROVIDER=browser)."""
        if self._closed:
            return
        # First real turn locks the preference for the rest of the conversation.
        self._preference_locked = True
        self._last_activity = time.monotonic()
        if self._processing_task is not None and not self._processing_task.done():
            await self.send_event({"type": "turn.busy"})
            return
        transcript = " ".join(text.split())
        if not transcript:
            await self.send_event({"type": "turn.empty", "message": "No speech heard"})
            return
        self._turn_seq += 1
        turn_id = self._turn_seq
        logger.info("turn.browser_transcript session_id=%s turn=%s chars=%s", self.session_id, turn_id, len(transcript))
        self._processing_task = asyncio.create_task(self._process_turn(b"", 0, turn_id, transcript=transcript))

    async def interrupt(self) -> None:
        logger.info("session.interrupt session_id=%s", self.session_id)
        if self._processing_task is not None and not self._processing_task.done():
            self._processing_task.cancel()
        self._processing_task = None
        if self.outgoing_audio_track is not None:
            await self.outgoing_audio_track.clear()
        if self._playback_done is not None and not self._playback_done.is_set():
            self._playback_done.set()
        await self.send_event({"type": "assistant.audio.done", "interrupted": True})

    async def _on_audio_track(self, track: MediaStreamTrack) -> None:
        if self._audio_reader_started:
            logger.warning("session.audio_track extra_ignored session_id=%s", self.session_id)
            return
        self._audio_reader_started = True
        self.incoming_audio_track = track
        try:
            await self.receive_audio(track)
        except Exception as exc:
            await self.fail("receive_audio", exc)

    async def _on_connection_state(self, state: str) -> None:
        if state in {"failed", "closed"} and not self._closed:
            await self.close()

    async def receive_audio(self, track: MediaStreamTrack) -> None:
        logger.info("pipeline.receive_audio.start session_id=%s", self.session_id)
        while not self._closed:
            try:
                frame = await track.recv()
            except MediaStreamError:
                logger.info("pipeline.receive_audio.track_ended session_id=%s", self.session_id)
                break

            should_stop = False
            async with self._capture_lock:
                if self._capturing and self._current_audio is not None:
                    self._current_audio.add_frame(frame)
                    self._current_frames += 1
                    should_stop = self._current_audio.duration_seconds >= MAX_CAPTURE_SECONDS

            if should_stop:
                await self.stop_turn("max_duration")

    async def _process_turn(
        self,
        pcm_bytes: bytes,
        sample_rate: int,
        turn_id: int,
        transcript: str | None = None,
    ) -> None:
        task = asyncio.current_task()
        try:
            if transcript is None:
                await self.transcribe_audio(pcm_bytes, sample_rate, turn_id)
            else:
                await self.respond_to_transcript(transcript, turn_id)
        except asyncio.CancelledError:
            logger.info("turn.cancelled session_id=%s turn=%s", self.session_id, turn_id)
        except Exception as exc:
            await self.fail("turn_pipeline", exc)
        finally:
            if self._processing_task is task:
                self._processing_task = None

    async def transcribe_audio(self, pcm_bytes: bytes, sample_rate: int, turn_id: int) -> None:
        provider = self.settings.stt_provider
        logger.info("pipeline.transcribe.start session_id=%s turn=%s provider=%s", self.session_id, turn_id, provider)
        wav_bytes = pcm_to_wav_bytes(pcm_bytes, sample_rate)
        transcript = await self._stt().transcribe_wav(wav_bytes)
        logger.info(
            "pipeline.transcribe.done session_id=%s turn=%s provider=%s chars=%s",
            self.session_id,
            turn_id,
            provider,
            len(transcript),
        )
        if not transcript:
            await self.send_event({"type": "turn.empty", "message": "No speech heard"})
            return
        await self.respond_to_transcript(transcript, turn_id)

    async def respond_to_transcript(self, transcript: str, turn_id: int) -> None:
        await self.send_event({"type": "transcript.final", "text": transcript})
        self.conversation_messages.append({"role": "user", "content": transcript})
        self._idle_nudges = 0
        if is_greeting(transcript):
            await self._speak_greeting(turn_id)
            return
        topic = match_topic(transcript, self._topics_answered, SAFETY_TOPICS if self._mindcheck_done else None)
        if topic is not None:
            self._topics_answered.add(topic.name)
            if topic.name in {"crisis", "emergency"}:
                await self._show_helpline()
            await self._speak_static(pick_reply(topic), turn_id, f"topic:{topic.name}")
            return
        await self.generate_reply(turn_id)

    async def generate_reply(self, turn_id: int, allow_tools: bool = True) -> None:
        logger.info(
            "pipeline.generate.start session_id=%s turn=%s provider=%s",
            self.session_id,
            turn_id,
            self.settings.llm_provider,
        )
        healthcare_enabled = allow_tools and self._healthcare_tool_ready()
        result = await self._llm().generate(
            self.conversation_messages,
            self.user_profile,
            healthcare_enabled=healthcare_enabled,
            healthcare_deferred=self._healthcare_call_deferred,
            call_preference=CALL_PREF_CALL_HUMAN,
            call_number=HELPLINE_SPOKEN,
        )
        function_call = result.function_call
        if function_call and function_call.get("name") == HEALTHCARE_CALL_TOOL_NAME:
            logger.info(
                "pipeline.generate.tool session_id=%s turn=%s args=%s",
                self.session_id,
                turn_id,
                function_call.get("args"),
            )
            await self._handle_healthcare_call(function_call, result.text, turn_id)
            return

        assistant_text = result.text
        logger.info(
            "pipeline.generate.done session_id=%s turn=%s chars=%s",
            self.session_id,
            turn_id,
            len(assistant_text),
        )
        self.conversation_messages.append({"role": "assistant", "content": assistant_text})
        await self.send_event({"type": "assistant.final", "text": assistant_text})
        await self.synthesize_speech(assistant_text, turn_id)

    async def _idle_loop(self) -> None:
        """If the driver goes quiet after talking to MITRA, check in on them (a few times, never during a call)."""
        try:
            while not self._closed:
                await asyncio.sleep(5)
                idle = time.monotonic() - self._last_activity
                busy = self._capturing or (self._processing_task is not None and not self._processing_task.done())
                if (
                    idle < IDLE_NUDGE_SECONDS
                    or busy
                    or self._on_call
                    or self._turn_seq == 0
                    or self._idle_nudges >= MAX_IDLE_NUDGES
                ):
                    continue
                line = idle_nudge(self._idle_nudges)
                self._idle_nudges += 1
                self._last_activity = time.monotonic()
                self._turn_seq += 1
                turn_id = self._turn_seq
                logger.info("session.idle_nudge session_id=%s nudge=%s", self.session_id, self._idle_nudges)
                self._processing_task = asyncio.create_task(self._process_nudge(line, turn_id))
        except asyncio.CancelledError:
            pass

    async def _process_nudge(self, line: str, turn_id: int) -> None:
        task = asyncio.current_task()
        try:
            await self._speak_static(line, turn_id, "idle_nudge")
        except asyncio.CancelledError:
            logger.info("turn.cancelled session_id=%s turn=%s", self.session_id, turn_id)
        except Exception as exc:  # noqa: BLE001 - surface any pipeline failure to the client
            await self.fail("idle_nudge", exc)
        finally:
            if self._processing_task is task:
                self._processing_task = None

    async def _speak_greeting(self, turn_id: int) -> None:
        await self._speak_static(GREETING_LINE, turn_id, "greeting")

    async def _speak_static(self, line: str, turn_id: int, label: str) -> None:
        """Say a fixed line right away and keep it in the conversation so the model knows what was said."""
        logger.info("pipeline.static session_id=%s turn=%s kind=%s", self.session_id, turn_id, label)
        self.conversation_messages.append({"role": "assistant", "content": line})
        await self.send_event({"type": "assistant.final", "text": line})
        await self.synthesize_speech(line, turn_id)

    async def _handle_healthcare_call(self, function_call: dict, spoken_text: str, turn_id: int) -> None:
        args = function_call.get("args", {}) or {}
        timing = str(args.get("timing", "now")).strip().lower()
        issue_summary = str(args.get("issue_summary", "") or "").strip()
        spoken = (spoken_text or "").strip()

        tts = self._tts()
        await self.send_event({"type": "assistant.audio.started"})

        if timing == "later":
            self._healthcare_call_deferred = True
            confirm = spoken or HEALTHCARE_LATER_LINE
            await self.send_event({"type": "healthcare.call.deferred"})
            await self.send_event({"type": "assistant.final", "text": confirm})
            self.conversation_messages.append({"role": "assistant", "content": confirm})
            await self._speak_text(tts, confirm, turn_id)
            await self.wait_for_playback_done(turn_id)
            return

        # timing == "now": the model only calls this after the driver has confirmed.
        # The model's own wording is ignored here: the driver always gets the same clear line plus the number on screen.
        await self._open_phone_dialer(tts, "", turn_id)

    async def handle_mindcheck_result(self, result: dict) -> None:
        """Speak the Mind Check verdict; a bad score puts the helpline number on screen."""
        if self._closed:
            return
        self._preference_locked = True
        if self._processing_task is not None and not self._processing_task.done():
            await self.send_event({"type": "turn.busy"})
            return
        self._turn_seq += 1
        turn_id = self._turn_seq
        self._processing_task = asyncio.create_task(self._process_mindcheck_result(result, turn_id))

    def _log_mindcheck(self, result: dict, tier: str, action: str, call_id: str = "", error: str = "") -> None:
        """Append one line per Mind Check to logs/mindcheck_escalations.jsonl, so every escalation is auditable."""
        profile = self.user_profile or {}
        record = {
            "at": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "name": profile.get("name", ""),
            "truck": profile.get("truck", ""),
            "route": profile.get("route", ""),
            "kind": result.get("kind", ""),
            "score": result.get("score"),
            "band": result.get("band", ""),
            "tier": tier,
            "self_harm": bool(result.get("selfHarm")),
            "face_concern": bool(result.get("faceConcern")),
            "action": action,
            "doctor_number": DOCTOR_IVR_NUMBER if action.startswith("doctor_call") else "",
            "simulated": DOCTOR_CALL_STATIC if action.startswith("doctor_call") else False,
            "call_id": call_id,
            "error": error,
        }
        try:
            self.settings.log_dir.mkdir(parents=True, exist_ok=True)
            with (self.settings.log_dir / MINDCHECK_LOG_NAME).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("mindcheck.log.failed session_id=%s error=%s", self.session_id, exc)

    async def _process_mindcheck_result(self, result: dict, turn_id: int) -> None:
        tier = str(result.get("tier", "")) or "normal"
        action, call_id, error = "none", "", ""
        try:
            score = int(result.get("score", 0))
            band = str(result.get("band", ""))
            # Severe / Moderately severe (PHQ-9, GAD-7) or any self-harm answer means "call the doctor".
            bad = result.get("bucket") == "high" or bool(result.get("selfHarm")) or tier == "urgent"
            # Pressing "Call the doctor" is an explicit request, so the call is placed whatever the tier is.
            requested = bool(result.get("requestDoctor"))
            call_doctor = bad or requested
            logger.info("mindcheck.result session_id=%s score=%s bad=%s", self.session_id, score, bad)
            kind = str(result.get("kind", ""))
            raw_symptoms = result.get("symptoms")
            symptoms = [str(item).strip()[:80] for item in raw_symptoms[:3] if str(item).strip()] if isinstance(raw_symptoms, list) else []
            concern = tier == "elevated" or bool(result.get("faceConcern"))
            action = "advice_only" if concern and not call_doctor else "none"
            summary = mindcheck_summary(kind, band, symptoms)
            self_harm_line = f" {SELF_HARM_LINE}" if result.get("selfHarm") else ""
            if bad:
                line = f"{summary} {mindcheck_advice('high')}{self_harm_line} {MINDCHECK_BAD_LINE}"
            elif requested:
                line = MINDCHECK_REQUEST_LINE
            else:
                line = f"{summary} {mindcheck_advice(str(result.get('bucket', '')))}{self_harm_line} {OPEN_QUESTION}"
            self._mindcheck_done = True
            tts = self._tts()
            await self.send_event({"type": "assistant.audio.started"})
            await self.send_event({"type": "assistant.final", "text": line})
            self.conversation_messages.append({"role": "assistant", "content": line})
            symptom_note = f" The answers that stood out most: {'; '.join(symptoms)}." if symptoms else ""
            self.conversation_messages.append(
                {
                    "role": "user",
                    "content": (
                        f"[System note: the driver just finished a Mind Check ({kind}, score {score}, band {band}, "
                        f"priority {tier}).{symptom_note} The driver may now ask you anything about depression, anxiety, "
                        "sleep, stress or this result. Answer in simple, warm Hindi, explain clearly in 3 to 5 short "
                        "sentences, give one practical step, and end with a gentle question. Do not diagnose, do not "
                        "name medicines, and do not mention this note.]"
                    ),
                }
            )
            if not call_doctor:
                await self._speak_text(tts, line, turn_id)
                await self.wait_for_playback_done(turn_id)
                return

            action = "helpline_shown"
            await self._show_helpline()
            await self._speak_text(tts, line, turn_id)
            await self.wait_for_playback_done(turn_id)
        except asyncio.CancelledError:
            logger.info("mindcheck.cancelled session_id=%s turn=%s", self.session_id, turn_id)
        except Exception as exc:  # noqa: BLE001 - surface any pipeline failure to the client
            error = error or str(exc)
            await self.fail("mindcheck", exc)
        finally:
            self._log_mindcheck(result, tier, action, call_id, error)

    async def _place_doctor_call(self, score: int, band: str) -> dict:
        if DOCTOR_CALL_STATIC:
            logger.info("mindcheck.doctor_call.static number=%s score=%s band=%s", DOCTOR_IVR_NUMBER, score, band)
            await asyncio.sleep(1.5)
            return {"call_id": "STATIC-DOCTOR-CALL", "status": "QUEUED"}
        if not self.settings.doctor_call_ready():
            raise DhwaniCallError("DHWANI_CALL_API_KEY is not configured")
        client = DhwaniCallClient(
            self.settings.dhwani_call_api_key,
            self.settings.dhwani_call_base_url,
            self.settings.dhwani_call_agent,
        )
        receiver_name = (self.user_profile or {}).get("name", "Driver")
        return await client.place_call(
            number=DOCTOR_IVR_NUMBER,
            receiver_name=receiver_name,
            user_instructions=MINDCHECK_CALL_INSTRUCTIONS.format(score=score, band=band),
        )

    async def _connect_ai_agent(self, tts, spoken: str, issue_summary: str, turn_id: int) -> None:
        wait_line = spoken or HEALTHCARE_WAIT_LINE
        await self.send_event({"type": "healthcare.call.connecting", "mode": CALL_PREF_AI_AGENT})
        await self.send_event({"type": "assistant.final", "text": wait_line})
        # Place the call while the "please wait" line is being synthesized and played.
        call_task = asyncio.create_task(self._place_healthcare_call(issue_summary))
        await self._speak_text(tts, wait_line, turn_id)

        try:
            call_result = await call_task
        except DhwaniCallError as exc:
            await self._call_failed(tts, wait_line, str(exc), turn_id)
            return

        self._healthcare_call_deferred = False
        await self.send_event(
            {
                "type": "healthcare.call.queued",
                "mode": CALL_PREF_AI_AGENT,
                "call_id": call_result.get("call_id"),
                "status": call_result.get("status"),
            }
        )
        # Pause MITRA and ask the driver to confirm the call arrived. The frontend
        # shows the popup and starts the countdown as soon as this arrives.
        self._on_call = True
        await self.send_event(
            {"type": "healthcare.call.await_confirm", "timeout_ms": HEALTHCARE_CONFIRM_TIMEOUT_MS}
        )
        await self.send_event({"type": "assistant.final", "text": HEALTHCARE_SUCCESS_LINE})
        self.conversation_messages.append(
            {"role": "assistant", "content": f"{wait_line} {HEALTHCARE_SUCCESS_LINE}".strip()}
        )
        await self._speak_text(tts, HEALTHCARE_SUCCESS_LINE, turn_id)
        await self.wait_for_playback_done(turn_id)

    async def _connect_human_agent(self, tts, spoken: str, issue_summary: str, turn_id: int) -> None:
        wait_line = spoken or HEALTHCARE_WAIT_LINE
        await self.send_event({"type": "healthcare.call.connecting", "mode": CALL_PREF_HUMAN_AGENT})
        await self.send_event({"type": "assistant.final", "text": wait_line})
        # Single click_to_call bridge: Acefone rings the human agent and the driver
        # and connects them directly (no separate transfer step).
        call_task = asyncio.create_task(self._place_bridge_call())
        await self._speak_text(tts, wait_line, turn_id)

        try:
            result = await call_task
        except DialerCallError as exc:
            await self._call_failed(tts, wait_line, str(exc), turn_id)
            return

        self._healthcare_call_deferred = False
        await self.send_event(
            {
                "type": "healthcare.call.queued",
                "mode": CALL_PREF_HUMAN_AGENT,
                "status": result.get("message"),
            }
        )
        self._on_call = True
        await self.send_event(
            {"type": "healthcare.call.await_confirm", "timeout_ms": HEALTHCARE_CONFIRM_TIMEOUT_MS}
        )
        await self.send_event({"type": "assistant.final", "text": HEALTHCARE_HUMAN_SUCCESS_LINE})
        self.conversation_messages.append(
            {"role": "assistant", "content": f"{wait_line} {HEALTHCARE_HUMAN_SUCCESS_LINE}".strip()}
        )
        await self._speak_text(tts, HEALTHCARE_HUMAN_SUCCESS_LINE, turn_id)
        await self.wait_for_playback_done(turn_id)

    async def _open_phone_dialer(self, tts, spoken: str, turn_id: int) -> None:
        line = spoken or HEALTHCARE_DIALER_LINE
        self._healthcare_call_deferred = False
        await self._show_helpline()
        await self.send_event({"type": "healthcare.call.paused", "hint": HEALTHCARE_HUMAN_PAUSE_HINT})
        await self.send_event({"type": "assistant.final", "text": line})
        self.conversation_messages.append({"role": "assistant", "content": line})
        await self._speak_text(tts, line, turn_id)
        await self.wait_for_playback_done(turn_id)

    async def _call_failed(self, tts, wait_line: str, error: str, turn_id: int) -> None:
        logger.warning("healthcare.call.failed session_id=%s error=%s", self.session_id, error)
        await self.send_event({"type": "healthcare.call.failed", "message": error})
        await self.send_event({"type": "assistant.final", "text": HEALTHCARE_FAIL_LINE})
        self.conversation_messages.append(
            {"role": "assistant", "content": f"{wait_line} {HEALTHCARE_FAIL_LINE}".strip()}
        )
        await self._speak_text(tts, HEALTHCARE_FAIL_LINE, turn_id)
        await self.wait_for_playback_done(turn_id)

    def _llm(self) -> GeminiLLM:
        return GeminiLLM(self.settings.gemini_api_key, self.settings.gemini_model)

    def _stt(self) -> ElevenLabsSTT | GeminiSTT:
        if self.settings.stt_provider == "browser":
            raise RuntimeError("STT_PROVIDER=browser recognizes speech in the browser; server audio turns are not used")
        if self.settings.stt_provider == "gemini":
            return GeminiSTT(self.settings.gemini_api_key, self.settings.gemini_model)
        return ElevenLabsSTT(self.settings.elevenlabs_api_key, self.settings.elevenlabs_stt_model)

    def _tts(self) -> ElevenLabsTTS | EdgeTTS:
        if self.settings.tts_provider == "edge":
            return EdgeTTS(self.settings.edge_tts_voice)
        return ElevenLabsTTS(
            self.settings.elevenlabs_api_key,
            self.settings.elevenlabs_tts_model,
            self.settings.elevenlabs_tts_voice_id,
        )

    def _dialer_client(self) -> DialerCallClient:
        return DialerCallClient(
            self.settings.dialer_api_key,
            self.settings.dialer_api_url,
            self.settings.dialer_api_token,
            self.settings.transfer_call_url,
            self.settings.dialer_caller_id,
            self.settings.dialer_bridge_url,
        )

    async def _place_bridge_call(self) -> dict:
        client = self._dialer_client()
        return await client.place_bridge_call(
            agent_number=self.settings.human_agent_number,
            destination_number=self.settings.healthcare_driver_number,
        )

    async def handle_healthcare_confirmation(self, received: bool) -> None:
        if received:
            logger.info("healthcare.call.confirmed_received session_id=%s", self.session_id)
            self.conversation_messages.append(
                {
                    "role": "user",
                    "content": (
                        "[System note: the driver confirmed the healthcare call connected. "
                        "The driver is on the call now; stay quiet until they speak to you again.]"
                    ),
                }
            )
            return

        logger.info("healthcare.call.not_received session_id=%s", self.session_id)
        self._on_call = False
        if self._processing_task is not None and not self._processing_task.done():
            await self.send_event({"type": "turn.busy"})
            return
        self.conversation_messages.append(
            {
                "role": "user",
                "content": (
                    "[System note: the healthcare call did not reach the driver within the wait time. "
                    "Say a warm short sorry, keep them calm, and ask if they want you to try connecting "
                    "again now or a little later. Do not blame anyone and do not diagnose.]"
                ),
            }
        )
        self._turn_seq += 1
        turn_id = self._turn_seq
        self._processing_task = asyncio.create_task(self._process_confirmation_turn(turn_id))

    async def _process_confirmation_turn(self, turn_id: int) -> None:
        task = asyncio.current_task()
        try:
            # Tools disabled here so the "call not received" reply can only speak/ask,
            # never auto-redial without a fresh confirmation.
            await self.generate_reply(turn_id, allow_tools=False)
        except asyncio.CancelledError:
            logger.info("healthcare.confirmation.cancelled session_id=%s turn=%s", self.session_id, turn_id)
        except Exception as exc:
            await self.fail("healthcare_confirmation", exc)
        finally:
            if self._processing_task is task:
                self._processing_task = None

    def _healthcare_tool_ready(self) -> bool:
        # The doctor is reached by the driver calling the helpline number, so nothing has to be configured.
        return self.settings.healthcare_enabled

    async def _show_helpline(self) -> None:
        """Put the helpline number on the driver's screen (tap to call) and pause MITRA while they phone."""
        self._on_call = True
        await self.send_event({"type": "healthcare.call.open_dialer", "number": HELPLINE, "tel": HELPLINE_TEL})

    async def _place_healthcare_call(self, issue_summary: str) -> dict:
        client = DhwaniCallClient(
            self.settings.dhwani_call_api_key,
            self.settings.dhwani_call_base_url,
            self.settings.dhwani_call_agent,
        )
        receiver_name = (self.user_profile or {}).get("name", "Driver")
        return await client.place_call(
            number=self.settings.healthcare_driver_number,
            receiver_name=receiver_name,
            user_instructions=issue_summary or HEALTHCARE_DEFAULT_INSTRUCTIONS,
        )

    async def synthesize_speech(self, text: str, turn_id: int) -> None:
        logger.info(
            "pipeline.synthesize.start session_id=%s turn=%s provider=%s",
            self.session_id,
            turn_id,
            self.settings.tts_provider,
        )
        tts = self._tts()
        await self.send_event({"type": "assistant.audio.started"})
        await self._speak_text(tts, text, turn_id)
        await self.wait_for_playback_done(turn_id)

    async def _speak_text(self, tts: ElevenLabsTTS | EdgeTTS, text: str, turn_id: int) -> None:
        chunks = split_tts_text(text)
        for index, chunk in enumerate(chunks, start=1):
            if self._closed:
                return
            logger.info(
                "pipeline.synthesize.chunk session_id=%s turn=%s chunk=%s/%s chars=%s",
                self.session_id,
                turn_id,
                index,
                len(chunks),
                len(chunk),
            )
            pcm_bytes = await tts.synthesize_pcm(chunk)
            pcm_bytes = pad_tts_pcm(pcm_bytes)
            logger.info(
                "pipeline.synthesize.chunk_done session_id=%s turn=%s chunk=%s bytes=%s",
                self.session_id,
                turn_id,
                index,
                len(pcm_bytes),
            )
            await self.send_audio_to_webrtc(pcm_bytes, turn_id, index)

    async def send_audio_to_webrtc(self, pcm_bytes: bytes, turn_id: int, chunk_index: int) -> None:
        logger.info("pipeline.send_audio_to_webrtc.start session_id=%s turn=%s", self.session_id, turn_id)
        if self.outgoing_audio_track is None:
            raise RuntimeError("WebRTC output track is not available")

        done = await self.outgoing_audio_track.send_pcm(pcm_bytes)
        self._playback_done = done
        logger.info(
            "pipeline.send_audio_to_webrtc.queued session_id=%s turn=%s chunk=%s",
            self.session_id,
            turn_id,
            chunk_index,
        )

    async def wait_for_playback_done(self, turn_id: int) -> None:
        done = self._playback_done
        if done is None:
            if self._processing_task is asyncio.current_task():
                self._processing_task = None
            await self.send_event({"type": "assistant.audio.done"})
            return
        try:
            await asyncio.wait_for(done.wait(), timeout=45.0)
        except asyncio.TimeoutError:
            logger.warning("pipeline.playback_done.timeout session_id=%s turn=%s", self.session_id, turn_id)
            pass
        finally:
            self._playback_done = None
        if self._processing_task is asyncio.current_task():
            self._processing_task = None
        await self.send_event({"type": "assistant.audio.done"})

    async def send_event(self, payload: dict[str, Any]) -> None:
        if payload.get("type") in {"assistant.audio.done", "turn.started"}:
            self._last_activity = time.monotonic()
        if self.ws.closed:
            return
        await self.ws.send_json(payload)

    async def fail(self, stage: str, exc: Exception) -> None:
        logger.exception("session.error session_id=%s stage=%s error=%s", self.session_id, stage, exc)
        if not self._error_sent and not self.ws.closed:
            self._error_sent = True
            await self.ws.send_json({"type": "error", "message": f"{stage}: {exc}"})
        await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.closed_at = datetime.now(timezone.utc)
        logger.info("session.close session_id=%s", self.session_id)
        if self._idle_task is not None and self._idle_task is not asyncio.current_task():
            self._idle_task.cancel()
        if self._processing_task is not None and not self._processing_task.done():
            self._processing_task.cancel()
        if self.outgoing_audio_track is not None:
            await self.outgoing_audio_track.finish()
        await close_peer_connection(self.peer_connection)
        if not self.ws.closed:
            try:
                await self.ws.send_json({"type": "closed"})
            finally:
                await self.ws.close()


def is_greeting(text: str) -> bool:
    """True when the whole utterance is just a hello, e.g. "hello mitra" or "नमस्ते मित्रा जी"."""
    words = GREETING_TOKEN.findall(text.lower())
    return any(word in GREETING_WORDS for word in words) and all(
        word in GREETING_WORDS or word in GREETING_FILLER_WORDS for word in words
    )


def split_tts_text(text: str) -> list[str]:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []

    if len(normalized) <= TTS_SINGLE_CALL_CHAR_LIMIT:
        return [normalized]

    pieces = [match.group(0).strip() for match in TTS_SENTENCE_PATTERN.finditer(normalized)]
    pieces = [piece for piece in pieces if piece]
    if not pieces:
        return split_long_tts_piece(normalized)

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if len(piece) > TTS_MAX_CHARS:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(split_long_tts_piece(piece))
            continue

        candidate = f"{current} {piece}".strip() if current else piece
        if len(candidate) <= TTS_MAX_CHARS:
            current = candidate
            continue

        if current:
            chunks.append(current)
        current = piece

    if current:
        chunks.append(current)

    return chunks


def split_long_tts_piece(text: str) -> list[str]:
    chunks: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip() if current else word
        if len(candidate) <= TTS_MAX_CHARS:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = word
    if current:
        chunks.append(current)
    return chunks


def pad_tts_pcm(pcm_bytes: bytes) -> bytes:
    pre_samples = int(TTS_PCM_SAMPLE_RATE * TTS_PRE_SILENCE_MS / 1000)
    post_samples = int(TTS_PCM_SAMPLE_RATE * TTS_POST_SILENCE_MS / 1000)
    return (b"\x00\x00" * pre_samples) + pcm_bytes + (b"\x00\x00" * post_samples)
