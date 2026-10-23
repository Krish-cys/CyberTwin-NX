"""Tiny threaded HTTP server for the dashboard.  python -m cybertwin ui [--port 8765] [--open]

Binds to 127.0.0.1 by default. There is no authentication, so do NOT expose it to a network
you don't control. The UI only plans commands (dry-run); it never executes anything.
"""
from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from cybertwin.ui import service

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 64 * 1024
_run_lock = threading.Lock()   # incident runs append to shared log files


class Handler(BaseHTTPRequestHandler):
    server_version = "CyberTwinUI/1.0"

    # -- plumbing ---------------------------------------------------------------------
    def log_message(self, fmt, *args):  # quiet by default
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, default=str).encode(), "application/json; charset=utf-8")

    def _static(self, rel: str) -> None:
        target = (STATIC / rel).resolve()
        if STATIC.resolve() not in target.parents and target != STATIC.resolve() or not target.is_file():
            return self._json({"error": "not found"}, 404)
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise service.InputError("request body too large")
        if not n:
            return {}
        try:
            data = json.loads(self.rfile.read(n))
        except ValueError:
            raise service.InputError("body must be JSON") from None
        if not isinstance(data, dict):
            raise service.InputError("body must be a JSON object")
        return data

    def _guard(self, fn) -> None:
        try:
            self._json(fn())
        except service.InputError as e:
            self._json({"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001 - report, don't crash the server
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    # -- routes -----------------------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        if path == "/api/topology":
            return self._guard(service.topology)
        if path == "/api/history":
            return self._guard(service.history)
        if path == "/api/health":
            return self._json({"ok": True, "dry_run": True})
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/whatif":
            def go():
                b = self._body()
                return service.whatif(b.get("scenario", ""), b.get("args") or {})
            return self._guard(go)
        if path == "/api/incident":
            def go():
                b = self._body()
                try:
                    seed = int(b.get("seed", 0))
                except (TypeError, ValueError):
                    raise service.InputError("'seed' must be an integer") from None
                if not 0 <= seed <= 10_000:
                    raise service.InputError("'seed' must be between 0 and 10000")
                with _run_lock:
                    return service.run_incident(seed=seed, attacker=str(b.get("attacker", "h2")))
            return self._guard(go)
        self._json({"error": "not found"}, 404)


def make_server(host: str = "127.0.0.1", port: int = 8765, verbose: bool = False) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.verbose = verbose
    return srv


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    srv = make_server(host, port, verbose=True)
    url = f"http://{host}:{srv.server_address[1]}/"
    print(f"CyberTwin-NX dashboard -> {url}   (dry-run only; Ctrl+C to stop)")
    if host not in ("127.0.0.1", "localhost"):
        print("WARNING: no authentication - only bind to non-local addresses on a trusted network.")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        srv.server_close()
