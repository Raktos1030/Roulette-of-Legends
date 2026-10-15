"""Local UI server (127.0.0.1 only).

  GET  /ui/...                UI files (ui/ folder)
  GET  /img/..., /fonts/...   images and fonts from data/
  POST /api/<name>            calls Core.api_<name>(**json); token required (X-Token header)
  GET  /api/events?t=         event stream (Server-Sent Events): League state, history, updates...

The random token keeps web pages opened elsewhere from using the API: only the app window knows it.
No CORS header is sent.
"""

import json
import mimetypes
import os
import queue
import secrets
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from core import DATA, UI_DIR, log_error

TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
         ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml",
         ".ico": "image/x-icon", ".ttf": "font/ttf", ".otf": "font/otf", ".woff2": "font/woff2", ".webp": "image/webp"}
ROOTS = {"ui": UI_DIR, "img": os.path.join(DATA, "img"), "fonts": os.path.join(DATA, "fonts")}


class Server:
    def __init__(self, core, port=0):
        self.core = core
        self.token = secrets.token_urlsafe(18)
        handler = self._make_handler()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]

    @property
    def url(self):
        return "http://127.0.0.1:%d/ui/index.html?t=%s" % (self.port, self.token)

    def start(self):
        threading.Thread(target=self.httpd.serve_forever, name="serveur", daemon=True).start()

    def stop(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except OSError:
            pass

    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):   # quiet
                pass

            def _send(self, code, body, ctype="application/json; charset=utf-8", cache="no-store"):
                if isinstance(body, str):
                    body = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", cache)
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code, data):
                self._send(code, json.dumps(data, ensure_ascii=False))

            def do_GET(self):
                u = urlparse(self.path)
                path = unquote(u.path)
                if path in ("/", "/index.html"):
                    self.send_response(302)
                    self.send_header("Location", "/ui/index.html" + ("?" + u.query if u.query else ""))
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if path == "/api/events":
                    if parse_qs(u.query).get("t", [""])[0] != server.token:
                        return self._json(403, {"error": "invalid token"})
                    return self._events()
                parts = path.strip("/").split("/", 1)
                if len(parts) != 2 or parts[0] not in ROOTS:
                    return self._send(404, "not found", "text/plain; charset=utf-8")
                root = os.path.abspath(ROOTS[parts[0]])
                full = os.path.abspath(os.path.join(root, parts[1]))
                if not full.startswith(root + os.sep) or not os.path.isfile(full):
                    return self._send(404, "not found", "text/plain; charset=utf-8")
                ext = os.path.splitext(full)[1].lower()
                ctype = TYPES.get(ext) or mimetypes.guess_type(full)[0] or "application/octet-stream"
                cache = "no-cache" if parts[0] == "ui" else "max-age=604800"
                try:
                    with open(full, "rb") as f:
                        body = f.read()
                except OSError:
                    return self._send(404, "not found", "text/plain; charset=utf-8")
                self._send(200, body, ctype, cache)

            def do_POST(self):
                u = urlparse(self.path)
                if not u.path.startswith("/api/"):
                    return self._json(404, {"error": "not found"})
                if self.headers.get("X-Token") != server.token:
                    return self._json(403, {"error": "invalid token"})
                name = u.path[len("/api/"):]
                fn = getattr(server.core, "api_" + name, None) if name.replace("_", "").isalnum() else None
                if fn is None:
                    return self._json(404, {"error": "unknown function: %s" % name})
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    args = json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}
                    if not isinstance(args, dict):
                        args = {}
                    result = fn(**args)
                except TypeError as e:
                    log_error("API %s: %s" % (name, traceback.format_exc()))
                    return self._json(400, {"error": "invalid parameters: %s" % e})
                except Exception as e:
                    log_error("API %s: %s" % (name, traceback.format_exc()))
                    return self._json(500, {"error": "internal error: %s" % e})
                self._json(200, result if result is not None else {})

            def _events(self):
                q = server.core.subscribe()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    self.wfile.write(b"retry: 1500\n\n")
                    self.wfile.flush()
                    while True:
                        try:
                            msg = q.get(timeout=15)
                            data = json.dumps(msg, ensure_ascii=False)
                            self.wfile.write(("data: %s\n\n" % data).encode("utf-8"))
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except (OSError, ValueError):
                    pass
                finally:
                    server.core.unsubscribe(q)
                    self.close_connection = True

        return Handler
