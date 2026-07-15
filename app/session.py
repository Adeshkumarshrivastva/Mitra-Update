from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from aiohttp import web
from aiortc import RTCPeerConnection
from aiortc.mediastreams import MediaStreamError, MediaStreamTrack

from .audio import AudioBuffer, TTS_PCM_SAMPLE_RATE, pcm_to_wav_bytes
from .dhwani_calls import DhwaniCallClient, DhwaniCallError
from .dialer_calls import DialerCallClient, DialerCallError
from .llm_gemini import GeminiLLM
from .settings import Settings
from .stt_elevenlabs import ElevenLabsSTT
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
HEALTHCARE_DIALER_LINE = "मैं आपके फ़ोन में हेल्थकेयर टीम का नंबर खोल रही हूँ, आप कॉल कर लीजिए।"


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

    async def handle_offer(self, sdp: str) -> str:
        self.settings.require_voice_pipeline()
        self.peer_connection, self.outgoing_audio_track = await create_peer_connection(
            self._on_audio_track,
            self._on_connection_state,
        )
        logger.info("session.offer session_id=%s", self.session_id)
        answer_sdp = await accept_offer(self.peer_connection, sdp)
        logger.info("session.answer session_id=%s", self.session_id)
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

    async def _process_turn(self, pcm_bytes: bytes, sample_rate: int, turn_id: int) -> None:
        task = asyncio.current_task()
        try:
            await self.transcribe_with_scribe_v2(pcm_bytes, sample_rate, turn_id)
        except asyncio.CancelledError:
            logger.info("turn.cancelled session_id=%s turn=%s", self.session_id, turn_id)
        except Exception as exc:
            await self.fail("turn_pipeline", exc)
        finally:
            if self._processing_task is task:
                self._processing_task = None

    async def transcribe_with_scribe_v2(self, pcm_bytes: bytes, sample_rate: int, turn_id: int) -> None:
        logger.info("pipeline.transcribe_with_scribe_v2.start session_id=%s turn=%s", self.session_id, turn_id)
        wav_bytes = pcm_to_wav_bytes(pcm_bytes, sample_rate)
        transcript = await ElevenLabsSTT(
            self.settings.elevenlabs_api_key,
            self.settings.elevenlabs_stt_model,
        ).transcribe_wav(wav_bytes)
        logger.info(
            "pipeline.transcribe_with_scribe_v2.done session_id=%s turn=%s chars=%s",
            self.session_id,
            turn_id,
            len(transcript),
        )
        await self.send_event({"type": "transcript.final", "text": transcript})
        self.conversation_messages.append({"role": "user", "content": transcript})
        await self.generate_with_gemini(turn_id)

    async def generate_with_gemini(self, turn_id: int, allow_tools: bool = True) -> None:
        logger.info("pipeline.generate_with_gemini.start session_id=%s turn=%s", self.session_id, turn_id)
        result = await GeminiLLM(
            self.settings.gemini_api_key,
            self.settings.gemini_model,
        ).generate(
            self.conversation_messages,
            self.user_profile,
            healthcare_enabled=allow_tools and self._healthcare_tool_ready(),
            healthcare_deferred=self._healthcare_call_deferred,
            call_preference=self.call_preference,
            call_number=self.settings.human_agent_number or self.settings.healthcare_support_number,
        )
        function_call = result.function_call
        if function_call and function_call.get("name") == HEALTHCARE_CALL_TOOL_NAME:
            logger.info(
                "pipeline.generate_with_gemini.tool session_id=%s turn=%s args=%s",
                self.session_id,
                turn_id,
                function_call.get("args"),
            )
            await self._handle_healthcare_call(function_call, result.text, turn_id)
            return

        assistant_text = result.text
        logger.info(
            "pipeline.generate_with_gemini.done session_id=%s turn=%s chars=%s",
            self.session_id,
            turn_id,
            len(assistant_text),
        )
        self.conversation_messages.append({"role": "assistant", "content": assistant_text})
        await self.send_event({"type": "assistant.final", "text": assistant_text})
        await self.synthesize_with_elevenlabs(assistant_text, turn_id)

    async def _handle_healthcare_call(self, function_call: dict, spoken_text: str, turn_id: int) -> None:
        args = function_call.get("args", {}) or {}
        timing = str(args.get("timing", "now")).strip().lower()
        issue_summary = str(args.get("issue_summary", "") or "").strip()
        spoken = (spoken_text or "").strip()

        tts = ElevenLabsTTS(
            self.settings.elevenlabs_api_key,
            self.settings.elevenlabs_tts_model,
            self.settings.elevenlabs_tts_voice_id,
        )
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
        if self.call_preference == CALL_PREF_HUMAN_AGENT:
            await self._connect_human_agent(tts, spoken, issue_summary, turn_id)
        elif self.call_preference == CALL_PREF_CALL_HUMAN:
            await self._open_phone_dialer(tts, spoken, turn_id)
        else:
            await self._connect_ai_agent(tts, spoken, issue_summary, turn_id)

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
        number = self.settings.human_agent_number or self.settings.healthcare_support_number
        self._healthcare_call_deferred = False
        await self.send_event({"type": "healthcare.call.open_dialer", "number": number})
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
            await self.generate_with_gemini(turn_id, allow_tools=False)
        except asyncio.CancelledError:
            logger.info("healthcare.confirmation.cancelled session_id=%s turn=%s", self.session_id, turn_id)
        except Exception as exc:
            await self.fail("healthcare_confirmation", exc)
        finally:
            if self._processing_task is task:
                self._processing_task = None

    def _healthcare_tool_ready(self) -> bool:
        if not self.settings.healthcare_enabled:
            return False
        if self.call_preference == CALL_PREF_HUMAN_AGENT:
            return self.settings.human_call_ready()
        if self.call_preference == CALL_PREF_CALL_HUMAN:
            return True
        return self.settings.healthcare_call_ready()

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

    async def synthesize_with_elevenlabs(self, text: str, turn_id: int) -> None:
        logger.info("pipeline.synthesize_with_elevenlabs.start session_id=%s turn=%s", self.session_id, turn_id)
        tts = ElevenLabsTTS(
            self.settings.elevenlabs_api_key,
            self.settings.elevenlabs_tts_model,
            self.settings.elevenlabs_tts_voice_id,
        )
        await self.send_event({"type": "assistant.audio.started"})
        await self._speak_text(tts, text, turn_id)
        await self.wait_for_playback_done(turn_id)

    async def _speak_text(self, tts: ElevenLabsTTS, text: str, turn_id: int) -> None:
        chunks = split_tts_text(text)
        for index, chunk in enumerate(chunks, start=1):
            if self._closed:
                return
            logger.info(
                "pipeline.synthesize_with_elevenlabs.chunk session_id=%s turn=%s chunk=%s/%s chars=%s",
                self.session_id,
                turn_id,
                index,
                len(chunks),
                len(chunk),
            )
            pcm_bytes = await tts.synthesize_pcm(chunk)
            pcm_bytes = pad_tts_pcm(pcm_bytes)
            logger.info(
                "pipeline.synthesize_with_elevenlabs.chunk_done session_id=%s turn=%s chunk=%s bytes=%s",
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
