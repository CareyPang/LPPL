#!/usr/bin/env python3
"""Local Worker API stub for the stock page flow.

Run from the repository root with:
    python workers/stock-query/dev/stub_server.py
"""
from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[3]
STOCK_DIR = ROOT / "web" / "mock" / "data" / "stock"
CODE_PATTERN = re.compile(r"^(?:60|68|00|30|43|83|87|92)\d{4}$")
STATUS_CALLS: dict[str, int] = {}
PORT = int(os.environ.get("PORT", "8765"))
RUN_URL = f"http://127.0.0.1:{PORT}/runs/600519"


class Handler(BaseHTTPRequestHandler):
    def _headers(self, status: int, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, status: int, value: object) -> None:
        self._headers(status)
        self.wfile.write(json.dumps(value, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self) -> None:
        self._headers(204)

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/query":
            self._json(404, {"error": "Not found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(size))
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "Invalid JSON body"})
            return
        code = body.get("code") if isinstance(body, dict) else None
        if not isinstance(code, str) or not CODE_PATTERN.fullmatch(code):
            self._json(400, {"error": "Invalid A-share code"})
            return
        STATUS_CALLS[code] = 0
        self._json(202, {"queued": True})

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        params = parse_qs(parsed.query)
        code = params.get("code", [""])[0]
        if parsed.path == "/status":
            if not CODE_PATTERN.fullmatch(code):
                self._json(400, {"error": "Invalid A-share code"})
                return
            calls = STATUS_CALLS.get(code, 0) + 1
            STATUS_CALLS[code] = calls
            if calls == 1:
                payload = {"status": "queued", "conclusion": None, "run_url": RUN_URL}
            elif calls == 2:
                payload = {"status": "in_progress", "conclusion": None, "run_url": RUN_URL}
            else:
                payload = {
                    "status": "completed",
                    "conclusion": "success",
                    "run_url": RUN_URL,
                }
            self._json(200, payload)
            return
        if parsed.path == "/result":
            kind = params.get("kind", [""])[0]
            suffix = {"latest": ".json", "history": "_history.json", "error": "_error.json"}.get(kind)
            if not CODE_PATTERN.fullmatch(code) or suffix is None:
                self._json(400, {"error": "Invalid code or kind"})
                return
            if STATUS_CALLS.get(code, 0) < 3:
                self._json(404, {"error": "Not found"})
                return
            path = (STOCK_DIR / f"{code}{suffix}").resolve()
            if not path.is_relative_to(STOCK_DIR.resolve()):
                self._json(400, {"error": "Invalid path"})
                return
            try:
                data = path.read_bytes()
            except FileNotFoundError:
                self._json(404, {"error": "Not found"})
                return
            self._headers(200)
            self.wfile.write(data)
            return
        self._json(404, {"error": "Not found"})

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"{self.address_string()} - {format_string % args}")


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"stock-query stub listening at http://127.0.0.1:{PORT} (use code 600519)", flush=True)
    server.serve_forever()
