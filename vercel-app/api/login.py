from http.server import BaseHTTPRequestHandler
import hmac
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from _lib.web import clean, login_pin, make_token, read_json, send_json, session_cookie  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        data = read_json(self)
        expected = login_pin()
        pin = str(data.get("pin", "")).strip()
        if expected and not hmac.compare_digest(pin, expected):
            send_json(self, 401, {"ok": False, "error": "Invalid PIN"})
            return
        profile = {
            "name": clean(data.get("name"), "Saathi"),
            "truck": clean(data.get("truck"), "Truck"),
            "route": clean(data.get("route"), "Highway"),
        }
        send_json(self, 200, {"ok": True, "profile": profile}, cookie=session_cookie(make_token(profile)))

    def log_message(self, *args):
        pass
