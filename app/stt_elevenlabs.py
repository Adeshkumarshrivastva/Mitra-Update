from __future__ import annotations

import asyncio
import json
import mimetypes
import uuid
from urllib import error, request


ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"


class ElevenLabsSTT:
    def __init__(self, api_key: str, model_id: str) -> None:
        self.api_key = api_key
        self.model_id = model_id

    async def transcribe_wav(self, wav_bytes: bytes) -> str:
        return await asyncio.to_thread(self._transcribe_wav_sync, wav_bytes)

    def _transcribe_wav_sync(self, wav_bytes: bytes) -> str:
        boundary = f"----mitra-{uuid.uuid4().hex}"
        body = _multipart_body(
            boundary,
            fields={"model_id": self.model_id},
            files={"file": ("utterance.wav", "audio/wav", wav_bytes)},
        )
        req = request.Request(
            ELEVENLABS_STT_URL,
            data=body,
            method="POST",
            headers={
                "xi-api-key": self.api_key,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        payload = _open_json(req, timeout=90)
        text = str(payload.get("text", "")).strip()
        if not text:
            raise RuntimeError("ElevenLabs STT returned an empty transcript")
        return text


def _multipart_body(
    boundary: str,
    fields: dict[str, str],
    files: dict[str, tuple[str, str | None, bytes]],
) -> bytes:
    chunks: list[bytes] = []
    boundary_bytes = boundary.encode("ascii")

    for name, value in fields.items():
        chunks.extend(
            [
                b"--" + boundary_bytes,
                f'Content-Disposition: form-data; name="{name}"'.encode("utf-8"),
                b"",
                str(value).encode("utf-8"),
            ]
        )

    for name, (filename, content_type, content) in files.items():
        guessed_type = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        chunks.extend(
            [
                b"--" + boundary_bytes,
                (
                    f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{filename}"'
                ).encode("utf-8"),
                f"Content-Type: {guessed_type}".encode("utf-8"),
                b"",
                content,
            ]
        )

    chunks.append(b"--" + boundary_bytes + b"--")
    chunks.append(b"")
    return b"\r\n".join(chunks)


def _open_json(req: request.Request, timeout: int) -> dict:
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
    except error.HTTPError as exc:
        raw = exc.read()
        detail = raw.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"ElevenLabs STT HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"ElevenLabs STT connection failed: {exc.reason}") from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        detail = raw.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"ElevenLabs STT returned non-JSON response: {detail}") from exc
