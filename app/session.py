from __future__ import annotations

import asyncio
import logging
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

MAX_CAPTURE_SECONDS = 7.0
FRAME_GAP_TIMEOUT_SECONDS = 2.0
FIRST_FRAME_TIMEOUT_SECONDS = 10.0


@dataclass
class VoiceSession:
    settings: Settings
    ws: web.WebSocketResponse
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    peer_connection: RTCPeerConnection | None = None
    incoming_audio_track: MediaStreamTrack | None = None
    outgoing_audio_track: QueuedAudioTrack | None = None
    conversation_messages: list[dict[str, str]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: datetime | None = None
    _closed: bool = False
    _error_sent: bool = False
    _pipeline_started: bool = False

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

    async def _on_audio_track(self, track: MediaStreamTrack) -> None:
        if self._pipeline_started:
            logger.warning("session.audio_track extra_ignored session_id=%s", self.session_id)
            return
        self._pipeline_started = True
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
        audio = AudioBuffer()
        frames = 0
        loop = asyncio.get_running_loop()
        started_at = loop.time()

        while True:
            try:
                timeout = FRAME_GAP_TIMEOUT_SECONDS if frames else FIRST_FRAME_TIMEOUT_SECONDS
                frame = await asyncio.wait_for(track.recv(), timeout=timeout)
            except MediaStreamError:
                break
            except asyncio.TimeoutError:
                if frames:
                    logger.info("pipeline.receive_audio.gap_timeout session_id=%s", self.session_id)
                    break
                raise RuntimeError("No microphone frames arrived")
            audio.add_frame(frame)
            frames += 1
            if audio.duration_seconds >= MAX_CAPTURE_SECONDS:
                logger.info("pipeline.receive_audio.max_duration session_id=%s", self.session_id)
                break
            if loop.time() - started_at >= FIRST_FRAME_TIMEOUT_SECONDS and not frames:
                raise RuntimeError("No microphone audio received")

        logger.info(
            "pipeline.receive_audio.done session_id=%s frames=%s seconds=%.2f bytes=%s",
            self.session_id,
            frames,
            audio.duration_seconds,
            len(audio.pcm_bytes),
        )
        if not audio.pcm_bytes or audio.duration_seconds < 0.2:
            raise RuntimeError("No microphone audio received")

        await self.transcribe_with_scribe_v2(audio.pcm_bytes, audio.sample_rate)

    async def transcribe_with_scribe_v2(self, pcm_bytes: bytes, sample_rate: int) -> None:
        logger.info("pipeline.transcribe_with_scribe_v2.start session_id=%s", self.session_id)
        wav_bytes = pcm_to_wav_bytes(pcm_bytes, sample_rate)
        transcript = await ElevenLabsSTT(
            self.settings.elevenlabs_api_key,
            self.settings.elevenlabs_stt_model,
        ).transcribe_wav(wav_bytes)
        logger.info("pipeline.transcribe_with_scribe_v2.done session_id=%s chars=%s", self.session_id, len(transcript))
        await self.send_event({"type": "transcript.final", "text": transcript})
        self.conversation_messages.append({"role": "user", "content": transcript})
        await self.generate_with_gemini()

    async def generate_with_gemini(self) -> None:
        logger.info("pipeline.generate_with_gemini.start session_id=%s", self.session_id)
        assistant_text = await GeminiLLM(
            self.settings.gemini_api_key,
            self.settings.gemini_model,
        ).generate(self.conversation_messages)
        logger.info("pipeline.generate_with_gemini.done session_id=%s chars=%s", self.session_id, len(assistant_text))
        self.conversation_messages.append({"role": "assistant", "content": assistant_text})
        await self.send_event({"type": "assistant.final", "text": assistant_text})
        await self.synthesize_with_elevenlabs(assistant_text)

    async def synthesize_with_elevenlabs(self, text: str) -> None:
        logger.info("pipeline.synthesize_with_elevenlabs.start session_id=%s", self.session_id)
        pcm_bytes = await ElevenLabsTTS(
            self.settings.elevenlabs_api_key,
            self.settings.elevenlabs_tts_model,
            self.settings.elevenlabs_tts_voice_id,
        ).synthesize_pcm(text)
        logger.info("pipeline.synthesize_with_elevenlabs.done session_id=%s bytes=%s", self.session_id, len(pcm_bytes))
        await self.send_audio_to_webrtc(pcm_bytes)

    async def send_audio_to_webrtc(self, pcm_bytes: bytes) -> None:
        logger.info("pipeline.send_audio_to_webrtc.start session_id=%s", self.session_id)
        if self.outgoing_audio_track is None:
            raise RuntimeError("WebRTC output track is not available")
        await self.outgoing_audio_track.send_pcm(pcm_bytes)
        audio_seconds = len(pcm_bytes) / 2 / TTS_PCM_SAMPLE_RATE
        logger.info(
            "pipeline.send_audio_to_webrtc.done session_id=%s seconds=%.2f",
            self.session_id,
            audio_seconds,
        )
        await asyncio.sleep(min(audio_seconds + 0.8, 45.0))
        await self.close()

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
        if self.outgoing_audio_track is not None:
            await self.outgoing_audio_track.finish()
        await close_peer_connection(self.peer_connection)
        if not self.ws.closed:
            try:
                await self.ws.send_json({"type": "closed"})
            finally:
                await self.ws.close()
