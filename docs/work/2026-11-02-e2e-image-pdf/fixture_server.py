"""Serve the OME-1551 fixtures on loopback and log every request (one JSON line each).

Usage: python fixture_server.py <fixtures_dir> <port> <log.jsonl>
"""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT, PORT, LOG = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
TYPES = {".png": "image/png", ".pdf": "application/pdf"}


class Handler(BaseHTTPRequestHandler):
    def _serve(self, body: bool) -> None:
        path = self.path.split("?", 1)[0]
        target = ROOT / path.lstrip("/")
        entry = {
            "t": time.time(),
            "method": self.command,
            "path": self.path,
            "accept": self.headers.get("Accept"),
            "ua": self.headers.get("User-Agent"),
        }
        if target.suffix in TYPES and target.is_file():
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", TYPES[target.suffix])
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if body:
                self.wfile.write(data)
            entry["status"] = 200
        else:
            self.send_response(404)
            self.end_headers()
            entry["status"] = 404
        with LOG.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def do_GET(self) -> None:
        self._serve(True)

    def do_HEAD(self) -> None:
        self._serve(False)

    def log_message(self, *args) -> None:
        pass


ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
