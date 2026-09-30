from http.server import BaseHTTPRequestHandler
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from _lib.web import clear_cookie, send_json  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        send_json(self, 200, {"ok": True}, cookie=clear_cookie())

    def log_message(self, *args):
        pass
