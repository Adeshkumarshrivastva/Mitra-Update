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

    async def start_turn(self) -> None:
        if self._closed:
            return
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

    async def generate_with_gemini(self, turn_id: int) -> None:
        logger.info("pipeline.generate_with_gemini.start session_id=%s turn=%s", self.session_id, turn_id)
        assistant_text = await GeminiLLM(
            self.settings.gemini_api_key,
            self.settings.gemini_model,
        ).generate(self.conversation_messages, self.user_profile)
        logger.info(
            "pipeline.generate_with_gemini.done session_id=%s turn=%s chars=%s",
            self.session_id,
            turn_id,
            len(assistant_text),
        )
        self.conversation_messages.append({"role": "assistant", "content": assistant_text})
        await self.send_event({"type": "assistant.final", "text": assistant_text})
        await self.synthesize_with_elevenlabs(assistant_text, turn_id)

    async def synthesize_with_elevenlabs(self, text: str, turn_id: int) -> None:
        logger.info("pipeline.synthesize_with_elevenlabs.start session_id=%s turn=%s", self.session_id, turn_id)
        tts = ElevenLabsTTS(
            self.settings.elevenlabs_api_key,
            self.settings.elevenlabs_tts_model,
            self.settings.elevenlabs_tts_voice_id,
        )

        chunks = split_tts_text(text)
        await self.send_event({"type": "assistant.audio.started", "chunks": len(chunks)})
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
        await self.wait_for_playback_done(turn_id)

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
