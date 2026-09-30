"""Run the Vercel version on your own laptop:  python dev_server.py   then open http://localhost:3000

Serves public/ (like Vercel with cleanUrls) and runs the functions in api/. Reads GEMINI_API_KEY etc. from a .env
file in this folder or in the parent folder. Stdlib only, nothing to install.
"""
from __future__ import annotations

import importlib.util
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
PORT = int(os.environ.get("PORT", "3000"))


def load_env() -> None:
    for folder in (ROOT.parent, ROOT):
        env = folder / ".env"
        if not env.is_file():
            continue
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_function(name: str):
    spec = importlib.util.spec_from_file_location(f"api_{name}", ROOT / "api" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.handler


class Dev(BaseHTTPRequestHandler):
    def _api(self, name: str) -> None:
        if not (ROOT / "api" / f"{name}.py").is_file():
            self.send_error(404)
            return
        fn = load_function(name)  # reloaded every time, so edits show up without a restart
        target = fn.__new__(fn)
        target.__dict__.update(self.__dict__)
        method = getattr(target, f"do_{self.command}", None)
        if method is None:
            self.send_error(405)
            return
        method()

    def _static(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", ""):
            path = "/index.html"
        candidate = (PUBLIC / path.lstrip("/")).resolve()
        if not candidate.is_file() and (PUBLIC / (path.lstrip("/") + ".html")).is_file():
            candidate = (PUBLIC / (path.lstrip("/") + ".html")).resolve()
        if PUBLIC not in candidate.parents and candidate != PUBLIC or not candidate.is_file():
            self.send_error(404)
            return
        body = candidate.read_bytes()
        kind = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{kind}; charset=utf-8" if kind.startswith(("text/", "application/javascript")) else kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _route(self) -> None:
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/"):
            self._api(path[len("/api/"):].strip("/"))
        else:
            self._static()

    do_GET = do_POST = _route

    def log_message(self, fmt, *args):
        print(f"{self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")


if __name__ == "__main__":
    load_env()
    if not os.environ.get("GEMINI_API_KEY"):
        print("Warning: GEMINI_API_KEY is not set, so only the built-in Hindi replies will work.")
    print(f"MITRA (Vercel version) running at http://localhost:{PORT}  (PIN: {os.environ.get('MITRA_LOGIN_PIN', '1234')})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Dev).serve_forever()
