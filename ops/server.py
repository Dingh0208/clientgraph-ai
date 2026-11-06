# -*- coding: utf-8 -*-
"""Local ops server: static prototype + diagnostics API.

Run: python -m ops.server --port 8123
Binds to 127.0.0.1 only.
"""
from __future__ import annotations

import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .diagnostics import get_log, run_checks, start_component, stop_component

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROTOTYPE), **kwargs)

    def _json(self, payload: dict, status: int = 200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._json({"ok": True, "service": "clientgraph-ops"})
            return
        if parsed.path == "/api/diagnostics":
            self._json(run_checks())
            return
        if parsed.path.startswith("/api/components/") and parsed.path.endswith("/log"):
            cid = parsed.path.split("/")[3]
            qs = parse_qs(parsed.query)
            lines = int((qs.get("lines") or ["60"])[0])
            self._json({"id": cid, "content": get_log(cid, lines)})
            return
        if parsed.path.startswith("/api/"):
            self._json({"error": "not_found"}, 404)
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "components" \
                and parts[3] in ("start", "retry", "stop"):
            if parts[3] == "stop":
                self._json(stop_component(parts[2]))
            else:
                self._json(start_component(parts[2]))
            return
        self._json({"error": "not_found"}, 404)

    def log_message(self, fmt, *args):
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"ClientGraph AI ops server: http://{args.host}:{args.port}/")
    print("diagnostics: /api/diagnostics")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
