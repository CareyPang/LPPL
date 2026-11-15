"""Local-only stock UI acceptance fixtures. No market requests or model execution."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SHA = "b" * 40
JOBS: dict[str, dict] = {}
RESULTS: dict[tuple, dict] = {}
SCENARIOS = {"warm", "cold", "stale", "failure", "stale-failure", "slow-history"}


def series(code):
    rows = []
    day = date(2025, 10, 1)
    while day <= date(2026, 11, 5):
        if day.weekday() < 5:
            i = len(rows)
            close = round(18 + (int(code[-2:]) % 10) + i * .025 + math.sin(i / 13) * 1.8, 2)
            rows.append(dict(date=day.isoformat(), open=round(close - .12, 2),
                             high=round(close + .35, 2), low=round(close - .4, 2), close=close, volume=12000))
        day += timedelta(days=1)
    return rows


def record(code, scenario, job=None, kind="latest"):
    key = (code, scenario, job["job_id"] if job else None, kind)
    if key in RESULTS:
        return RESULTS[key]
    rows = series(code)
    result = {
        "symbol": ("sh" if code.startswith("6") else "sz" if code[0] in "03" else "bj") + code,
        "code": code, "name": "合成验收股票", "asof": rows[-1]["date"],
        "variant": "stk_lite", "model_version": "fixture-v1", "source_sha": SHA,
        "schema_version": "stock_result_v1", "generated_at": "2026-11-05T09:00:00Z",
        "evidence": "dev_only", "data_version": "synthetic-no-market-data",
        "stock_meta": {"variant": "stk_lite"}, "top": {"evidence": "dev_only"},
        "price_history": {key: [row[key] for row in rows] for key in ("open", "high", "low", "close", "volume")},
    }
    result["price_history"]["dates"] = [row["date"] for row in rows]
    if scenario in {"stale", "stale-failure"} and job is None:
        result["asof"] = "2026-11-04"
        result["source_sha"] = "a" * 40
    if job:
        result.update(job_id=job["job_id"], requested_at=job["requested_at"],
                      mode=job["mode"], generated_at=datetime.now(UTC).isoformat())
    if kind == "history":
        result["frames"] = [{"asof": rows[-1]["date"], "evidence": "dev_only", "top": {}}]
    result["delivery_observation"] = {
        "result_hash": hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest(),
        "first_worker_observed_at": datetime.now(UTC).isoformat(),
        "first_visible_at": None, "public_first_published_at": None,
        "evidence": "synthetic_fixture_not_live_observation",
    }
    RESULTS[key] = result
    return result


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, value, mime="application/json; charset=utf-8"):
        data = json.dumps(value, ensure_ascii=False).encode() if isinstance(value, (dict, list)) else value
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_POST(self):
        parts = urlsplit(self.path).path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "api" or parts[2] != "query":
            self.respond(404, {"error": "Not found"})
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        code, mode = body.get("code"), body.get("mode", "current")
        for job in JOBS.values():
            duration = 18 if job["mode"] == "history" else 4
            if job["code"] == code and job["mode"] == mode and time.monotonic() - job["started"] < duration:
                self.respond(202, job)
                return
        job = dict(code=code, mode=mode, job_id=str(uuid.uuid4()), source_sha=SHA, queued=True, phase="queued",
                   history_weeks=104 if mode == "history" else 0,
                   requested_at=datetime.now(UTC).isoformat(), started=time.monotonic())
        JOBS[job["job_id"]] = job
        self.respond(202, job)

    def do_GET(self):
        parsed = urlsplit(self.path)
        params = parse_qs(parsed.query)
        path = parsed.path
        if path.startswith("/api/"):
            _, _, scenario, action = path.split("/", 3)
            code = params.get("code", ["600519"])[0]
            if action == "market":
                rows = series(code)
                self.respond(200, dict(code=code, symbol=("sh" if code.startswith("6") else "sz") + code,
                    name="合成验收股票", source="本地合成数据", price=rows, latest=rows[-1],
                    asof=rows[-1]["date"], closed_only=True, adjustment="none", expected_source_sha=SHA))
                return
            job_id = params.get("job_id", [None])[0]
            job = JOBS.get(job_id)
            if action == "status":
                if not job:
                    self.respond(404, {"error": "Unknown fixture job"})
                    return
                ready = time.monotonic() - job["started"] >= (18 if job["mode"] == "history" else 4)
                failure = scenario in {"failure", "stale-failure"} and ready
                phase = ("stale" if scenario == "stale-failure" else "failed") if failure else (
                    job["mode"] + "_ready" if ready else job["mode"] + "_running")
                self.respond(200, dict(job_id=job_id, phase=phase, status="completed" if ready else "in_progress",
                    stale=scenario == "stale-failure" and ready,
                    stale_reason="refresh_failed_previous_result_retained" if phase == "stale" else None,
                    conclusion=("failure" if failure else "success") if ready else None,
                    current_ready=ready and not failure and job["mode"] == "current",
                    history_ready=ready and not failure and job["mode"] == "history"))
                return
            if action == "result":
                kind = params.get("kind", ["latest"])[0]
                duration = 18 if job and job["mode"] == "history" else 4
                if kind == "error" or (job_id and (not job or time.monotonic() - job["started"] < duration)):
                    self.respond(404, {"error": "Not available"})
                elif not job and scenario in {"cold", "failure"}:
                    self.respond(404, {"error": "No cached result"})
                else:
                    if scenario == "slow-history" and kind == "history":
                        time.sleep(20)
                    self.respond(200, record(code, scenario, job, kind))
                return
        if path.startswith("/fixtures/"):
            self.respond(404, {"error": "No static fixture; read local API"})
            return
        relative = path.lstrip("/") or "stock.html"
        target = (ROOT / "frontend" / relative).resolve()
        if not target.is_relative_to((ROOT / "frontend").resolve()) or not target.is_file():
            self.respond(404, {"error": "Not found"})
            return
        data = target.read_bytes()
        mime = {".js": "text/javascript; charset=utf-8", ".css": "text/css",
                ".html": "text/html; charset=utf-8", ".webp": "image/webp"}.get(target.suffix, "application/octet-stream")
        if target.name == "stock.html":
            scenario = params.get("scenario", ["warm"])[0]
            if scenario not in SCENARIOS:
                scenario = "warm"
            config = '<script>window.LPPL_QUERY_API="/api/' + scenario + '";window.LPPL_DATA_BASE="/fixtures/";</script>'
            banner = ('<aside style="padding:12px;background:#24344b;color:white;font:13px system-ui">'
                      '本地验收 · 全部为合成数据 · 不调用行情或模型　' +
                      "　".join('<a style="color:white" href="?scenario=' + s + '&code=600519">' + s + '</a>'
                                for s in sorted(SCENARIOS)) +
                      '<button onclick="localStorage.removeItem(\'lppl.stock.jobs.v1\');location.reload()">清除测试任务</button></aside>')
            text = data.decode().replace('<script src="app/lppl-data.js">', config + '<script src="app/lppl-data.js">')
            data = text.replace("<body>", "<body>" + banner).encode()
        self.respond(200, data, mime)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8794)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Local fixture preview: http://127.0.0.1:{args.port}/stock.html?scenario=cold&code=600519", flush=True)
    server.serve_forever()
