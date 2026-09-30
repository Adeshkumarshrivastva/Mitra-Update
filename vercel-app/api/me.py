from http.server import BaseHTTPRequestHandler
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from _lib.web import current_profile, send_json  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        send_json(self, 200, {"ok": True, "profile": current_profile(self), "stt_provider": "browser"})

    def log_message(self, *args):
        pass
