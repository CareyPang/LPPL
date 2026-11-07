"""Bounded local real-analysis gateway; no GitHub/Pages/Worker deployment.

Run with the existing research Python environment. Default budget permits two
current fits for the two explicitly authorized assets. Historical replay is not
enabled. /api/preview alone accepts 000001 as the explicitly named index alias.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from research.pipeline.real_preview_adapter import canonical, market, utc_now, write_json  # noqa: E402


class Service:
    def __init__(self, data_dir: Path, max_runs: int, source_sha: str):
        self.root, self.max_runs, self.source_sha = data_dir, max_runs, source_sha
        self.lock = threading.RLock()
        self.market_locks = {symbol: threading.Lock() for symbol in ("sh000001", "sh600519")}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="research-preview")
        self.jobs = {}
        state = data_dir / "gateway_jobs.json"
        if state.exists():
            self.jobs = json.loads(state.read_text(encoding="utf-8"))
            for job in self.jobs.values():
                if job["status"] in ("queued", "in_progress"):
                    job.update(status="completed", conclusion="failure", error="Gateway restarted; no duplicate computation was launched")

    def save(self):
        write_json(self.root / "gateway_jobs.json", self.jobs)

    def observed(self, code):
        with self.market_locks[code]:
            return market(code, self.root)

    def query(self, code):
        with self.lock:
            existing = [job for job in self.jobs.values() if job["code"] == code and job.get("conclusion") != "failure"]
            if existing:
                return {**existing[-1], "deduped": True}
            if sum(job.get("run_kind") != "fixed_fit_export" for job in self.jobs.values()) >= self.max_runs:
                raise ValueError("本轮两资产当前分析预算已用完；不会自动重复运行")
            job = {"code": code, "symbol": code, "mode": "current", "history_weeks": 0,
                   "job_id": str(uuid.uuid4()), "requested_at": utc_now(), "source_sha": self.source_sha,
                   "status": "queued", "conclusion": None, "current_ready": False, "history_ready": False}
            self.jobs[job["job_id"]] = job
            self.save()
            self.executor.submit(self.run, job["job_id"])
            return {**job, "deduped": False}

    def run(self, identity):
        with self.lock:
            job = self.jobs[identity]
            job.update(status="in_progress", started_at=utc_now())
            self.save()
        directory = self.root / job["code"] / "jobs" / identity
        directory.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONIOENCODING": "utf-8"}
        command = [sys.executable, "-m", "research.pipeline.real_preview_adapter", job["code"],
                   "--data-dir", str(self.root), "--job-id", identity, "--requested-at", job["requested_at"],
                   "--source-sha", self.source_sha]
        try:
            with (directory / "runner.log").open("w", encoding="utf-8") as log:
                result = subprocess.run(command, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=240,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode or not (directory / "result.json").exists():
                raise RuntimeError(f"research runner failed (exit {result.returncode}); inspect isolated runner.log")
            with self.lock:
                job.update(status="completed", conclusion="success", current_ready=True, completed_at=utc_now())
                self.save()
        except Exception as exc:
            with self.lock:
                job.update(status="completed", conclusion="failure", error=str(exc), completed_at=utc_now())
                self.save()

    def status(self, code, identity):
        with self.lock:
            job = self.jobs.get(identity)
            if not job or job["code"] != code:
                raise KeyError("任务编号与资产不匹配")
            result = dict(job)
        progress = self.root / code / "jobs" / identity / "progress.json"
        if progress.exists():
            result["progress"] = json.loads(progress.read_text(encoding="utf-8"))
        return result

    def result(self, code, identity):
        if identity:
            self.status(code, identity)
            path = self.root / code / "jobs" / identity / "result.json"
        else:
            path = self.root / code / "latest.json"
        if not path.exists():
            raise KeyError("结果尚未生成")
        return json.loads(path.read_text(encoding="utf-8"))


def handler(service: Service, allowed_origins: set[str]):
    class Handler(BaseHTTPRequestHandler):
        def send(self, status, value):
            raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            origin = self.headers.get("Origin")
            if origin in allowed_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def dispatch(self):
            origin = self.headers.get("Origin")
            if origin and origin not in allowed_origins:
                return self.send(403, {"error_code": "ORIGIN_FORBIDDEN", "error": "隔离服务不允许此来源"})
            if self.command == "OPTIONS":
                return self.send(200, {})
            parsed = urlsplit(self.path)
            parts = parsed.path.strip("/").split("/")
            preview = len(parts) == 3 and parts[:2] == ["api", "preview"]
            if not preview and not (len(parts) == 2 and parts[0] == "api"):
                return self.send(404, {"error": "接口不存在"})
            action = parts[-1]
            if action not in ("market", "query", "status", "result") or (self.command == "POST") != (action == "query"):
                return self.send(405, {"error": "请求方法不支持"})
            params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
            try:
                if self.command == "POST":
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 2048:
                        raise ValueError("请求体大小不合法")
                    params = json.loads(self.rfile.read(length))
                code = params.get("code", "")
                if preview and code == "000001":
                    code = "sh000001"
                code = canonical(code)
                identity = params.get("job_id")
                if identity:
                    uuid.UUID(identity)
                if action == "market":
                    value = service.observed(code)
                elif action == "query":
                    if params.get("mode", "current") != "current" or int(params.get("history_weeks", 0)) != 0:
                        return self.send(409, {"error_code": "HISTORY_NOT_ENABLED", "error": "本轮只运行当前分析；历史回放未启用，不会自动运行104周"})
                    value = service.query(code)
                elif action == "status":
                    value = service.status(code, identity)
                else:
                    if params.get("kind", "latest") != "latest":
                        raise KeyError("本轮不生成历史回放结果")
                    value = service.result(code, identity)
                self.send(202 if action == "query" else 200, value)
            except KeyError as exc:
                self.send(404, {"error_code": "RESULT_NOT_FOUND", "error": str(exc)})
            except (ValueError, TypeError) as exc:
                self.send(400, {"error_code": "INVALID_REQUEST", "error": str(exc)})
            except Exception as exc:
                self.send(502, {"error_code": "PREVIEW_UNAVAILABLE", "error": str(exc)})

        do_GET = dispatch
        do_POST = dispatch
        do_OPTIONS = dispatch

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8793)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--max-runs", type=int, default=2)
    parser.add_argument("--source-sha", default="NOT_ESTABLISHED")
    parser.add_argument("--allow-origin", action="append", default=[])
    args = parser.parse_args()
    if not 1 <= args.max_runs <= 2:
        parser.error("this authorized preview allows 1 or 2 current runs")
    root = args.data_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    origins = {f"http://127.0.0.1:{port}" for port in (8792, 8793, 8794)} | set(args.allow_origin)
    service = Service(root, args.max_runs, args.source_sha)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(service, origins))
    print(f"Isolated real analysis: http://127.0.0.1:{args.port}/api (two assets, current only)", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
