# -*- coding: utf-8 -*-
"""Test fixture: a minimal local health endpoint.

This is NOT the product Sidecar. It exists only to verify that the diagnostics
layer can start a configured component and observe a healthy endpoint.
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/health"):
            body = json.dumps({"ok": True, "component": "fake-sidecar"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8877
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
