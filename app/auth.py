from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from aiohttp import web


COOKIE_NAME = "mitra_session"
SESSION_TTL = timedelta(hours=12)


@dataclass
class UserProfile:
    name: str
    truck: str
    route: str
    login_at: datetime

    def to_json(self) -> dict[str, str]:
        return {
            "name": self.name,
            "truck": self.truck,
            "route": self.route,
            "login_at": self.login_at.isoformat(),
        }


def _bearer_token(request: web.Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[len("Bearer "):].strip() or None
    return None


def current_profile(request: web.Request) -> UserProfile | None:
    # Native clients (React Native) have no automatic cookie jar for a WS
    # upgrade request, so they send the token as a header instead; browsers
    # keep using the httponly cookie exactly as before.
    token = _bearer_token(request) or request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    sessions: dict[str, UserProfile] = request.app["auth_sessions"]
    profile = sessions.get(token)
    if profile is None:
        return None
    if datetime.now(timezone.utc) - profile.login_at > SESSION_TTL:
        sessions.pop(token, None)
        return None
    return profile


def require_profile(request: web.Request) -> UserProfile:
    profile = current_profile(request)
    if profile is None:
        raise web.HTTPUnauthorized(text="Login required")
    return profile


def create_login_response(request: web.Request, payload: dict[str, Any], expected_pin: str) -> web.Response:
    name = _clean(payload.get("name"), default="Saathi")
    pin = str(payload.get("pin", "")).strip()
    truck = _clean(payload.get("truck"), default="Truck")
    route = _clean(payload.get("route"), default="Highway")

    if expected_pin and pin != expected_pin:
        raise web.HTTPUnauthorized(text="Invalid PIN")

    token = secrets.token_urlsafe(32)
    profile = UserProfile(
        name=name,
        truck=truck,
        route=route,
        login_at=datetime.now(timezone.utc),
    )
    request.app["auth_sessions"][token] = profile
    # `token` is also returned in the body (not just Set-Cookie) so a client
    # with no cookie jar (React Native) can carry it as a Bearer header.
    response = web.json_response({"ok": True, "profile": profile.to_json(), "token": token})
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return response


def clear_login_response(request: web.Request) -> web.Response:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        request.app["auth_sessions"].pop(token, None)
    response = web.json_response({"ok": True})
    response.del_cookie(COOKIE_NAME, path="/")
    return response


def _clean(value: object, default: str) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    return text[:60]
