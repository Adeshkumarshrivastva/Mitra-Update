from __future__ import annotations

import asyncio
import logging
from fractions import Fraction
from typing import Awaitable, Callable

from aiortc import RTCIceCandidate, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError, MediaStreamTrack
from aiortc.sdp import candidate_from_sdp

from .audio import WEBRTC_SAMPLE_RATE, pcm_bytes_to_audio_frames


logger = logging.getLogger("mitra.webrtc")


TrackHandler = Callable[[MediaStreamTrack], Awaitable[None]]
StateHandler = Callable[[str], Awaitable[None]]


class QueuedAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self) -> None:
        super().__init__()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._samples_sent = 0
        self._stopped = False

    async def recv(self):
        if self._stopped:
            raise MediaStreamError

        frame = await self._queue.get()
        if frame is None:
            self._stopped = True
            raise MediaStreamError

        frame.pts = self._samples_sent
        frame.time_base = Fraction(1, WEBRTC_SAMPLE_RATE)
        self._samples_sent += frame.samples
        return frame

    async def send_pcm(self, pcm_bytes: bytes) -> None:
        for frame in pcm_bytes_to_audio_frames(pcm_bytes):
            await self._queue.put(frame)

    async def finish(self) -> None:
        await self._queue.put(None)


async def create_peer_connection(
    on_audio_track: TrackHandler,
    on_state_change: StateHandler,
) -> tuple[RTCPeerConnection, QueuedAudioTrack]:
    pc = RTCPeerConnection()
    outgoing_track = QueuedAudioTrack()
    pc.addTrack(outgoing_track)

    @pc.on("track")
    def on_track(track: MediaStreamTrack) -> None:
        logger.info("webrtc.track kind=%s", track.kind)
        if track.kind == "audio":
            asyncio.create_task(on_audio_track(track))

    @pc.on("connectionstatechange")
    async def on_connectionstatechange() -> None:
        logger.info("webrtc.connection_state state=%s", pc.connectionState)
        await on_state_change(pc.connectionState)

    return pc, outgoing_track


async def accept_offer(pc: RTCPeerConnection, sdp: str) -> str:
    offer = RTCSessionDescription(sdp=sdp, type="offer")
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    await wait_for_ice_gathering_complete(pc)
    if pc.localDescription is None:
        raise RuntimeError("WebRTC answer was not created")
    return pc.localDescription.sdp


async def wait_for_ice_gathering_complete(pc: RTCPeerConnection, timeout: float = 5.0) -> None:
    if pc.iceGatheringState == "complete":
        return

    loop = asyncio.get_running_loop()
    done = loop.create_future()

    @pc.on("icegatheringstatechange")
    def on_ice_gathering_state_change() -> None:
        if pc.iceGatheringState == "complete" and not done.done():
            done.set_result(None)

    try:
        await asyncio.wait_for(done, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("webrtc.ice_gathering timeout state=%s", pc.iceGatheringState)


async def add_browser_ice(pc: RTCPeerConnection, candidate: dict | None) -> None:
    if not candidate:
        await pc.addIceCandidate(None)
        return

    candidate_line = candidate.get("candidate")
    if not candidate_line:
        return
    if candidate_line.startswith("candidate:"):
        candidate_line = candidate_line.removeprefix("candidate:")
    rtc_candidate: RTCIceCandidate = candidate_from_sdp(candidate_line)
    rtc_candidate.sdpMid = candidate.get("sdpMid")
    rtc_candidate.sdpMLineIndex = candidate.get("sdpMLineIndex")
    await pc.addIceCandidate(rtc_candidate)


async def close_peer_connection(pc: RTCPeerConnection | None) -> None:
    if pc is not None and pc.connectionState != "closed":
        await pc.close()
