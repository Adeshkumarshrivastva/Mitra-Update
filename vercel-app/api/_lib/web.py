"""Small helpers shared by the Vercel functions: JSON in/out and the signed login cookie (no server-side session store)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from http.cookies import SimpleCookie
from typing import Any

COOKIE_NAME = "mitra_session"
SESSION_SECONDS = 12 * 60 * 60
MAX_BODY = 64 * 1024


def _secret() -> bytes:
    # Set SESSION_SECRET in Vercel. Without it the login PIN is used, which is still unguessable to outsiders.
    return (os.environ.get("SESSION_SECRET") or ("mitra-" + login_pin())).encode("utf-8")


def login_pin() -> str:
    return os.environ.get("MITRA_LOGIN_PIN", "1234").strip()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_token(profile: dict[str, str]) -> str:
    body = _b64(json.dumps({**profile, "exp": int(time.time()) + SESSION_SECONDS}, ensure_ascii=False).encode("utf-8"))
    sig = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token: str) -> dict[str, str] | None:
    try:
        body, sig = token.split(".", 1)
        expected = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(_unb64(body).decode("utf-8"))
        if int(data.get("exp", 0)) < time.time():
            return None
        return {key: str(data.get(key, "")) for key in ("name", "truck", "route")}
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def current_profile(handler: Any) -> dict[str, str] | None:
    cookie = SimpleCookie()
    try:
        cookie.load(handler.headers.get("Cookie", ""))
    except Exception:  # noqa: BLE001 - a malformed cookie just means "not logged in"
        return None
    morsel = cookie.get(COOKIE_NAME)
    return read_token(morsel.value) if morsel else None


def session_cookie(token: str) -> str:
    return f"{COOKIE_NAME}={token}; Max-Age={SESSION_SECONDS}; Path=/; HttpOnly; Secure; SameSite=Lax"


def clear_cookie() -> str:
    return f"{COOKIE_NAME}=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax"


def read_json(handler: Any) -> dict[str, Any]:
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0 or length > MAX_BODY:
        return {}
    try:
        data = json.loads(handler.rfile.read(length).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def send_json(handler: Any, status: int, payload: dict[str, Any], cookie: str | None = None) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    if cookie:
        handler.send_header("Set-Cookie", cookie)
    handler.end_headers()
    handler.wfile.write(body)


def clean(value: object, default: str) -> str:
    text = str(value or "").strip()
    return text[:60] if text else default
