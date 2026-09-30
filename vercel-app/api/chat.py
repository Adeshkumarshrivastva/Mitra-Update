from http.server import BaseHTTPRequestHandler
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from _lib.web import current_profile, read_json, send_json  # noqa: E402
from _lib.brain import TROUBLE_LINE, respond  # noqa: E402

logger = logging.getLogger("mitra.chat")


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        profile = current_profile(self)
        if profile is None:
            send_json(self, 401, {"ok": False, "error": "Login required"})
            return
        try:
            result = respond(read_json(self), profile)
        except Exception as exc:  # noqa: BLE001 - the driver hears a calm line instead of an error
            logger.exception("chat failed: %s", exc)
            send_json(self, 200, {"ok": False, "error": str(exc)[:200], "text": TROUBLE_LINE})
            return
        send_json(self, 200, result)

    def log_message(self, *args):
        pass
