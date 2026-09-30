import argparse
import asyncio
import base64
import hashlib
import json
import logging
import mimetypes
import os
import ssl
import struct
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "mitra.log"
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
LOGGER = logging.getLogger("mitra")


class DhwaniError(Exception):
    pass


class WebSocketClosed(Exception):
    def __init__(self, code=1000, reason=""):
        super().__init__(f"closed code={code} reason={reason}")
        self.code = code
        self.reason = reason


def load_env(path=ROOT / ".env"):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def bool_env(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def setup_logging():
    LOG_DIR.mkdir(exist_ok=True)
    LOGGER.handlers.clear()
    LOGGER.setLevel(logging.DEBUG)
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    LOGGER.addHandler(console)
    LOGGER.addHandler(file_handler)


def log(message, level="info"):
    if not LOGGER.handlers:
        setup_logging()
    getattr(LOGGER, level)(message)


def env_config():
    return {
        "agent_url": os.environ.get("MITRA_AGENT_WS_URL", "").strip(),
        "agent": os.environ.get("MITRA_AGENT_NAME", "default").strip() or "default",
        "user_name": os.environ.get("MITRA_USER_NAME", "Adesh").strip() or "Raushan",
        "greeting": bool_env("MITRA_GREETING", False),
        "ready_timeout": float(os.environ.get("MITRA_READY_TIMEOUT", "15")),
        "reply_timeout": float(os.environ.get("MITRA_REPLY_TIMEOUT", "45")),
        "check_text": os.environ.get("MITRA_CHECK_TEXT", "Hello").strip() or "Hello",
        "host": os.environ.get("MITRA_HOST", "127.0.0.1").strip() or "127.0.0.1",
        "port": int(os.environ.get("MITRA_PORT", "5173")),
    }


def safe_agent_url(agent_url):
    parsed = urlparse(agent_url)
    port = f":{parsed.port}" if parsed.port else ""
    suffix = "?key=***" if parsed.query else ""
    return f"{parsed.scheme}://{parsed.hostname or ''}{port}{parsed.path}{suffix}"


def describe_frame(frame):
    frame_type = frame.get("type", "unknown")
    if frame_type == "ready":
        return f"ready session_id={frame.get('session_id', '')} agent={frame.get('agent', '')}"
    if frame_type in {"token", "done", "greeting"}:
        return f"{frame_type} text_len={len(str(frame.get('text', '')))}"
    if frame_type == "error":
        return f"error message={frame.get('message', '')}"
    return frame_type


def parse_headers(raw):
    head = raw.decode("iso-8859-1")
    lines = head.split("\r\n")
    method, target, version = lines[0].split(" ", 2)
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    return method, target, version, headers


async def read_http_request(reader):
    raw_headers = await reader.readuntil(b"\r\n\r\n")
    method, target, version, headers = parse_headers(raw_headers)
    length = int(headers.get("content-length", "0") or "0")
    body = await reader.readexactly(length) if length else b""
    return method, target, version, headers, body


async def write_http(writer, status, body=b"", content_type="text/plain; charset=utf-8", headers=None):
    if isinstance(body, str):
        body = body.encode("utf-8")
    reason = {
        200: "OK",
        400: "Bad Request",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        502: "Bad Gateway",
        500: "Internal Server Error",
    }.get(status, "OK")
    header_lines = [
        f"HTTP/1.1 {status} {reason}",
        f"Content-Length: {len(body)}",
        f"Content-Type: {content_type}",
        "Cache-Control: no-store",
        "Connection: close",
    ]
    for key, value in (headers or {}).items():
        header_lines.append(f"{key}: {value}")
    writer.write(("\r\n".join(header_lines) + "\r\n\r\n").encode("ascii") + body)
    await writer.drain()


async def write_json(writer, status, payload):
    await write_http(
        writer,
        status,
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        "application/json; charset=utf-8",
    )


async def serve_static(writer, target):
    path = unquote(target.split("?", 1)[0])
    if path == "/":
        path = "/index.html"
    requested = (PUBLIC / path.lstrip("/")).resolve()
    if PUBLIC not in requested.parents and requested != PUBLIC:
        await write_http(writer, 403, "Forbidden")
        return
    if not requested.exists() or not requested.is_file():
        await write_http(writer, 404, "Not found")
        return
    content_type = mimetypes.guess_type(requested.name)[0] or "application/octet-stream"
    await write_http(writer, 200, requested.read_bytes(), content_type)


async def read_frame(reader):
    first = await reader.readexactly(2)
    b1, b2 = first
    opcode = b1 & 0x0F
    masked = bool(b2 & 0x80)
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack("!H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", await reader.readexactly(8))[0]
    mask = await reader.readexactly(4) if masked else b""
    payload = await reader.readexactly(length) if length else b""
    if masked:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    if opcode == 0x8:
        code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 1000
        reason = payload[2:].decode("utf-8", "ignore") if len(payload) > 2 else ""
        raise WebSocketClosed(code, reason)
    return opcode, payload


async def send_frame(writer, payload=b"", opcode=0x1, mask=False):
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    length = len(payload)
    header = bytearray([0x80 | opcode])
    mask_bit = 0x80 if mask else 0
    if length < 126:
        header.append(mask_bit | length)
    elif length <= 0xFFFF:
        header.append(mask_bit | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(mask_bit | 127)
        header.extend(struct.pack("!Q", length))
    if mask:
        key = os.urandom(4)
        payload = bytes(byte ^ key[index % 4] for index, byte in enumerate(payload))
        header.extend(key)
    writer.write(bytes(header) + payload)
    await writer.drain()


async def send_json_ws(writer, payload, mask=False):
    await send_frame(writer, json.dumps(payload, separators=(",", ":"), ensure_ascii=False), opcode=0x1, mask=mask)


async def recv_json_ws(reader, writer=None, mask=False):
    while True:
        opcode, payload = await read_frame(reader)
        if opcode == 0x9:
            if writer is not None:
                await send_frame(writer, payload, opcode=0xA, mask=mask)
            continue
        if opcode == 0xA:
            continue
        if opcode != 0x1:
            continue
        return json.loads(payload.decode("utf-8"))


async def close_ws(writer, code=1000, reason="", mask=False):
    payload = struct.pack("!H", code) + reason.encode("utf-8")
    try:
        await send_frame(writer, payload, opcode=0x8, mask=mask)
    except Exception:
        pass


async def connect_dhwani():
    config = env_config()
    agent_url = config["agent_url"]
    if not agent_url:
        raise DhwaniError("MITRA_AGENT_WS_URL is missing in .env")

    parsed = urlparse(agent_url)
    if parsed.scheme not in {"ws", "wss"}:
        raise DhwaniError("MITRA_AGENT_WS_URL must start with ws:// or wss://")

    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    ssl_context = ssl.create_default_context() if parsed.scheme == "wss" else None

    log(f"dhwani.connect url={safe_agent_url(agent_url)}")
    reader, writer = await asyncio.open_connection(
        host,
        port,
        ssl=ssl_context,
        server_hostname=host if ssl_context else None,
    )

    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {parsed.netloc}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "User-Agent: MITRA/2.0\r\n"
        "\r\n"
    )
    writer.write(request.encode("ascii"))
    await writer.drain()
    response = await reader.readuntil(b"\r\n\r\n")
    status_line = response.decode("iso-8859-1", "ignore").split("\r\n", 1)[0]
    log(f"dhwani.handshake {status_line}")
    if " 101 " not in status_line:
        writer.close()
        await writer.wait_closed()
        raise DhwaniError(status_line)
    return reader, writer


async def start_dhwani_session(reader, writer):
    config = env_config()
    start_frame = {
        "type": "start",
        "agent": config["agent"],
        "user_name": config["user_name"],
        "greeting": config["greeting"],
    }
    log(
        f"dhwani.start agent={start_frame['agent']} "
        f"user={start_frame['user_name']} greeting={start_frame['greeting']}"
    )
    await send_json_ws(writer, start_frame, mask=True)

    while True:
        frame = await asyncio.wait_for(
            recv_json_ws(reader, writer, mask=True),
            timeout=config["ready_timeout"],
        )
        log(f"dhwani.frame {describe_frame(frame)}")
        frame_type = frame.get("type")
        if frame_type == "ready":
            return frame
        if frame_type == "error":
            raise DhwaniError(frame.get("message", "Dhwani returned an error during start"))
        if frame_type == "greeting":
            continue


async def dhwani_turn(text):
    config = env_config()
    started = time.perf_counter()
    reader = None
    writer = None
    tokens = []
    try:
        reader, writer = await connect_dhwani()
        ready = await start_dhwani_session(reader, writer)
        log(f"dhwani.message chars={len(text)} session_id={ready.get('session_id', '')}")
        await send_json_ws(writer, {"type": "message", "text": text}, mask=True)

        while True:
            frame = await asyncio.wait_for(
                recv_json_ws(reader, writer, mask=True),
                timeout=config["reply_timeout"],
            )
            log(f"dhwani.frame {describe_frame(frame)}")
            frame_type = frame.get("type")
            if frame_type == "token":
                tokens.append(str(frame.get("text", "")))
            elif frame_type == "done":
                reply = str(frame.get("text") or "".join(tokens)).strip()
                if not reply:
                    raise DhwaniError("Dhwani returned an empty reply")
                elapsed_ms = round((time.perf_counter() - started) * 1000)
                log(f"dhwani.done chars={len(reply)} elapsed_ms={elapsed_ms}")
                return {
                    "ok": True,
                    "reply": reply,
                    "session_id": ready.get("session_id"),
                    "elapsed_ms": elapsed_ms,
                }
            elif frame_type == "error":
                raise DhwaniError(frame.get("message", "Dhwani returned an error"))
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionResetError, ConnectionAbortedError, WebSocketClosed) as exc:
        raise DhwaniError(f"{type(exc).__name__}: {exc}") from exc
    finally:
        if writer is not None:
            try:
                if not writer.is_closing():
                    await send_json_ws(writer, {"type": "end"}, mask=True)
                    await close_ws(writer, mask=True)
                    writer.close()
                    await writer.wait_closed()
            except Exception as exc:
                log(f"dhwani.close warning {type(exc).__name__}: {exc}", "debug")


async def dhwani_check(send_message=False):
    reader = None
    writer = None
    try:
        reader, writer = await connect_dhwani()
        ready = await start_dhwani_session(reader, writer)
        result = {"ok": True, "session_id": ready.get("session_id"), "agent": ready.get("agent")}
        if send_message:
            check_text = env_config()["check_text"]
            log(f"dhwani.check.message chars={len(check_text)}")
            await send_json_ws(writer, {"type": "message", "text": check_text}, mask=True)
            while True:
                frame = await asyncio.wait_for(
                    recv_json_ws(reader, writer, mask=True),
                    timeout=env_config()["reply_timeout"],
                )
                log(f"dhwani.check.frame {describe_frame(frame)}")
                if frame.get("type") == "done":
                    result["reply_chars"] = len(str(frame.get("text", "")))
                    break
                if frame.get("type") == "error":
                    raise DhwaniError(frame.get("message", "Dhwani returned an error"))
        return result
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionResetError, ConnectionAbortedError, WebSocketClosed) as exc:
        raise DhwaniError(f"{type(exc).__name__}: {exc}") from exc
    finally:
        if writer is not None:
            try:
                if not writer.is_closing():
                    await send_json_ws(writer, {"type": "end"}, mask=True)
                    await close_ws(writer, mask=True)
                    writer.close()
                    await writer.wait_closed()
            except Exception as exc:
                log(f"dhwani.check.close warning {type(exc).__name__}: {exc}", "debug")


def json_body(body):
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON body") from exc


async def handle_api(method, path, body, writer):
    if path == "/api/health" and method == "GET":
        config = env_config()
        await write_json(
            writer,
            200,
            {
                "ok": True,
                "agent_configured": bool(config["agent_url"]),
                "agent": config["agent"],
                "log_file": str(LOG_FILE),
            },
        )
        return True

    if path == "/api/check" and method == "GET":
        try:
            result = await dhwani_check(send_message=False)
            await write_json(writer, 200, result)
        except DhwaniError as exc:
            log(f"api.check failed {exc}", "error")
            await write_json(writer, 502, {"ok": False, "error": str(exc)})
        return True

    if path == "/api/check-turn" and method == "GET":
        try:
            result = await dhwani_check(send_message=True)
            await write_json(writer, 200, result)
        except DhwaniError as exc:
            log(f"api.check_turn failed {exc}", "error")
            await write_json(writer, 502, {"ok": False, "error": str(exc)})
        return True

    if path == "/api/turn" and method == "POST":
        try:
            data = json_body(body)
            text = str(data.get("text", "")).strip()
            if not text:
                await write_json(writer, 400, {"ok": False, "error": "No speech text received"})
                return True
            result = await dhwani_turn(text)
            await write_json(writer, 200, result)
        except ValueError as exc:
            await write_json(writer, 400, {"ok": False, "error": str(exc)})
        except DhwaniError as exc:
            log(f"api.turn failed {exc}", "error")
            await write_json(writer, 502, {"ok": False, "error": str(exc)})
        except Exception as exc:
            log(f"api.turn unexpected {type(exc).__name__}: {exc}", "exception")
            await write_json(writer, 500, {"ok": False, "error": "Unexpected server error"})
        return True

    if path.startswith("/api/"):
        await write_json(writer, 404, {"ok": False, "error": "Unknown API route"})
        return True

    return False


async def handle_client(reader, writer):
    try:
        method, target, _version, _headers, body = await read_http_request(reader)
        path = target.split("?", 1)[0]
        log(f"http {method} {path}", "debug")
        if await handle_api(method, path, body, writer):
            return
        if method != "GET":
            await write_http(writer, 405, "Only GET is supported for static files")
            return
        await serve_static(writer, target)
    except Exception as exc:
        log(f"request error {type(exc).__name__}: {exc}", "exception")
        try:
            await write_json(writer, 500, {"ok": False, "error": "Internal server error"})
        except Exception:
            pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def run_server():
    config = env_config()
    requested_host = config["host"]
    if requested_host in {"127.0.0.1", "localhost", "::1"}:
        bind_hosts = ["127.0.0.1", "::1"]
    else:
        bind_hosts = [requested_host]

    servers = []
    for host in bind_hosts:
        try:
            server = await asyncio.start_server(handle_client, host, config["port"])
            servers.append((host, server))
            log(f"server bound host={host} port={config['port']}")
        except OSError as exc:
            log(f"server failed to bind host={host} port={config['port']}: {exc}", "error")

    if not servers:
        print(f"MITRA could not start on port {config['port']}", flush=True)
        print("Stop old Python servers on that port, or change MITRA_PORT in .env.", flush=True)
        raise SystemExit(1)

    for host, _server in servers:
        url_host = f"[{host}]" if ":" in host else host
        print(f"MITRA running at http://{url_host}:{config['port']}", flush=True)
    log(f"server started hosts={','.join(host for host, _ in servers)} port={config['port']} log_file={LOG_FILE}")

    try:
        await asyncio.gather(*(server.serve_forever() for _host, server in servers))
    finally:
        for _host, server in servers:
            server.close()
        await asyncio.gather(*(server.wait_closed() for _host, server in servers))


async def run_check(send_message):
    try:
        result = await dhwani_check(send_message=send_message)
        print(json.dumps(result, indent=2))
        return 0
    except DhwaniError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1


def main():
    load_env()
    setup_logging()
    parser = argparse.ArgumentParser(description="Run the MITRA voice assistant web app.")
    parser.add_argument("--check", action="store_true", help="Check Dhwani connection up to ready.")
    parser.add_argument("--check-turn", action="store_true", help="Check Dhwani connection and one test message.")
    args = parser.parse_args()

    if args.check or args.check_turn:
        raise SystemExit(asyncio.run(run_check(send_message=args.check_turn)))

    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        print("\nMITRA stopped")


if __name__ == "__main__":
    main()
