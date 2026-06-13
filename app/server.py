from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

from aiohttp import WSMsgType, web

from .session import VoiceSession
from .settings import Settings, load_env


logger = logging.getLogger("mitra")


def setup_logging(settings: Settings) -> Path:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    log_file = settings.log_dir / "mitra.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(name)s %(message)s", "%Y-%m-%d %H:%M:%S")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.INFO)

    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    return log_file


def create_app(settings: Settings) -> web.Application:
    app = web.Application()
    app["settings"] = settings
    app["sessions"] = {}

    async def index(_request: web.Request) -> web.FileResponse:
        return web.FileResponse(settings.public_dir / "index.html")

    async def websocket_session(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)

        session = VoiceSession(settings=settings, ws=ws)
        request.app["sessions"][session.session_id] = session
        logger.info("ws.session.open session_id=%s", session.session_id)

        try:
            settings.require_voice_pipeline()
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await handle_ws_text(session, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    raise RuntimeError(f"WebSocket error: {ws.exception()}")
        except Exception as exc:
            await session.fail("websocket", exc)
        finally:
            await session.close()
            request.app["sessions"].pop(session.session_id, None)
            logger.info("ws.session.done session_id=%s", session.session_id)

        return ws

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "pipeline": "webrtc", "use_dhwani": settings.use_dhwani})

    app.router.add_get("/", index)
    app.router.add_get("/ws/session", websocket_session)
    app.router.add_get("/health", health)
    app.router.add_static("/", settings.public_dir, show_index=False)
    return app


async def handle_ws_text(session: VoiceSession, raw: str) -> None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid JSON message") from exc

    message_type = payload.get("type")
    if message_type == "offer":
        sdp = payload.get("sdp")
        if not sdp:
            raise RuntimeError("offer.sdp is required")
        answer_sdp = await session.handle_offer(sdp)
        await session.send_event({"type": "answer", "sdp": answer_sdp})
    elif message_type == "ice":
        await session.handle_ice(payload.get("candidate"))
    else:
        raise RuntimeError(f"Unsupported message type: {message_type}")


async def run_server(settings: Settings) -> None:
    log_file = setup_logging(settings)
    app = create_app(settings)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.app_host, settings.app_port)
    await site.start()

    display_host = "127.0.0.1" if settings.app_host in {"0.0.0.0", "::"} else settings.app_host
    print(f"MITRA running at http://{display_host}:{settings.app_port}", flush=True)
    logger.info(
        "server.started host=%s port=%s use_dhwani=%s log_file=%s",
        settings.app_host,
        settings.app_port,
        settings.use_dhwani,
        log_file,
    )
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


def main() -> None:
    load_env()
    settings = Settings.from_env()
    if settings.use_dhwani:
        from .dhwani_legacy import main as legacy_main

        legacy_main()
        return
    try:
        asyncio.run(run_server(settings))
    except KeyboardInterrupt:
        print("\nMITRA stopped", flush=True)
