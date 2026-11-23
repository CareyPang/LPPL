"""Repeatable local daily refresh; no publication, trading or historical sweep.

The scheduler refreshes full source histories and runs one latest endpoint per
asset only when its verified input or implementation changed. Raw snapshots,
jobs, checkpoints, result vintages and failure audits remain outside checkout.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ..data.global_terminal import ASSETS, fetch_snapshot
from .global_jobs import GlobalJobs
from .global_terminal import ROOT, atomic_json, method_identity

SCHEMA = "global_daily_refresh_v1"
DEFAULT_SYMBOLS = ("US_IXIC", "US_NDX", "KR_KOSPI", "KR_KOSDAQ")


def now():
    return datetime.now(UTC).isoformat()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def parse_config(value):
    """Validate configuration without creating files, fetching data or fitting."""
    if not isinstance(value, dict):
        raise ValueError("Configuration must be a JSON object")
    config = {}
    for name in ("source_root", "jobs_root", "state_root", "archive_root", "long_root"):
        if name not in value or value[name] is None:
            if name in ("source_root", "jobs_root", "state_root"):
                raise ValueError(f"Missing absolute {name}")
            config[name] = None
            continue
        if not isinstance(value[name], str) or not Path(value[name]).is_absolute():
            raise ValueError(f"{name} must be an absolute path")
        path = Path(value[name]).resolve()
        if path.is_relative_to(ROOT):
            raise ValueError(f"{name} must stay outside the checkout")
        config[name] = path
    if config["source_root"] == config["jobs_root"]:
        raise ValueError("Source and job roots must be distinct")
    symbols = value.get("symbols", list(DEFAULT_SYMBOLS))
    if (not isinstance(symbols, list) or not symbols or any(not isinstance(s, str) for s in symbols)
            or len(symbols) != len(set(symbols))):
        raise ValueError("symbols must be a nonempty unique list")
    if any(not isinstance(symbol, str) or symbol not in ASSETS for symbol in symbols):
        raise ValueError("All symbols must be registered asset identifiers")
    config["symbols"] = list(symbols)
    minimum = value.get("minimum_rows", {})
    if not isinstance(minimum, dict) or any(symbol not in symbols for symbol in minimum):
        raise ValueError("minimum_rows must map requested asset identifiers to positive integers")
    if any(not isinstance(n, int) or isinstance(n, bool) or n < 10 for n in minimum.values()):
        raise ValueError("minimum_rows must be at least 10 real observations")
    config["minimum_rows"] = {symbol: minimum.get(symbol, 10) for symbol in symbols}
    long_rows = value.get("long_window_rows", 6700)
    if not isinstance(long_rows, int) or isinstance(long_rows, bool) or long_rows < 6600:
        raise ValueError("long_window_rows must be at least 6600")
    config["long_window_rows"] = long_rows
    return config


class AlreadyRunning(RuntimeError):
    pass


@contextlib.contextmanager
def refresh_lock(state_root):
    """OS advisory lock survives no process; no stale-lock deletion heuristic."""
    state_root.mkdir(parents=True, exist_ok=True)
    file = (state_root / "refresh.lock").open("a+b")
    locked = False
    try:
        if file.tell() == 0:
            file.write(b"0")
            file.flush()
        file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except (OSError, BlockingIOError) as error:
            raise AlreadyRunning("A daily refresh is already running for this state root") from error
        yield
    finally:
        if locked:
            file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)
        file.close()


def implementation_identity(config):
    dependencies = ("research/pipeline/global_jobs.py", "research/features/aftershock.py",
                    "research/data/global_events.py", "research/data/global_terminal.py")
    value = {"fit_method": method_identity()["hash"], "dependencies": {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in dependencies}}
    archive = config.get("archive_root")
    if archive and archive.is_dir():
        value["research_archive"] = {str(p.relative_to(archive)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(archive.rglob("*")) if p.is_file() and p.suffix in (".json", ".py", ".csv")}
    return fingerprint(value)


def _read(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _run_locked(config, fetcher, job_factory, sleeper):
    state_root = config["state_root"]
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
    audit = {"schema_version": SCHEMA, "run_id": run_id, "started_at": now(), "status": "running",
             "history_auto_run": False, "publication": "none", "assets": [],
             "counts": {"expected": len(config["symbols"]), "updated": 0, "unchanged": 0, "failed": 0}}
    audit_path = state_root / "runs" / (run_id + ".json")
    method = implementation_identity(config)
    service = job_factory(config["jobs_root"], config["source_root"], config["archive_root"], config["long_root"])
    try:
        for symbol in config["symbols"]:
            state_path = state_root / "assets" / (symbol + ".json")
            previous = {}
            previous_loaded = False
            row = {"symbol": symbol, "started_at": now(), "status": "fetching"}
            audit["assets"].append(row)
            atomic_json(audit_path, audit)
            try:
                previous = _read(state_path)
                previous_loaded = True
                frame, metadata = fetcher(symbol, config["source_root"], refresh=True,
                                         full_history=True, minimum_rows=config["minimum_rows"][symbol])
                asof = str(frame.date.iloc[-1].date())
                if metadata.get("id") != symbol or metadata.get("asof") != asof:
                    raise ValueError("Refreshed source asset or cutoff mismatch")
                if previous.get("last_good", {}).get("asof", "") > asof:
                    raise ValueError("Refreshed source cutoff regressed; existing result retained")
                current_key = fingerprint({"symbol": symbol, "asof": asof,
                    "data_version": metadata["normalized_sha256"], "implementation": method})
                row.update(asof=asof, source_status="ready", source_fetched_at=metadata["fetched_at"],
                           rows=len(frame), first_date=str(frame.date.iloc[0].date()),
                           data_version=metadata["normalized_sha256"],
                           long_window_coverage={"required_rows": config["long_window_rows"],
                              "actual_rows": len(frame),
                              "status": "available" if len(frame) >= config["long_window_rows"] else "insufficient_data"})
                selected = service.selected_result(symbol)
                last_good = previous.get("last_good", {})
                if (last_good.get("input_method_fingerprint") == current_key and selected
                        and selected.get("asof") == asof and selected.get("symbol") == symbol
                        and selected.get("data_version") == metadata["normalized_sha256"]
                        and selected.get("record_version") == last_good.get("record_version")):
                    row.update(status="unchanged", reason="no_new_completed_session_or_input_revision",
                               job_id=selected.get("job_id"), record_version=selected.get("record_version"))
                    # Do not label the day a holiday merely because an API returned no new bar.
                    audit["counts"]["unchanged"] += 1
                else:
                    job = service.start({"symbol": symbol, "asof": None, "refresh": False})
                    row.update(status="fitting", job_id=job["job_id"])
                    atomic_json(audit_path, audit)
                    while job["status"] not in ("complete", "failed"):
                        sleeper(1)
                        job = service.get(job["job_id"])
                    if job["status"] == "failed":
                        raise RuntimeError(job.get("error") or "Current analysis failed")
                    selected = service.result(job["job_id"])
                    if (selected.get("symbol") != symbol or selected.get("asof") != asof
                            or selected.get("data_version") != metadata["normalized_sha256"]):
                        raise ValueError("Completed result differs from the refreshed input")
                    row.update(status="updated", record_version=selected["record_version"],
                               fit_counts=selected.get("fit_counts"), cache_reused=job.get("cache_reused"),
                               modules=job.get("modules"))
                    audit["counts"]["updated"] += 1
                row["completed_at"] = now()
                last_good = {"asof": asof, "data_version": metadata["normalized_sha256"],
                             "record_version": selected["record_version"], "job_id": selected.get("job_id"),
                             "input_method_fingerprint": current_key, "verified_at": now()}
                atomic_json(state_path, {"schema_version": SCHEMA, "symbol": symbol,
                    "last_good": last_good, "last_attempt": row, "source_status": "ready"})
            except Exception as error:
                row.update(status="failed", completed_at=now(), error=f"{type(error).__name__}: {error}",
                           stale_reason="update_failed_existing_result_retained")
                if "source_status" not in row:
                    row["source_status"] = "stale"
                row["last_good_asof"] = previous.get("last_good", {}).get("asof")
                audit["counts"]["failed"] += 1
                # Preserve last successful state; a failed fetch never advances last_good.
                if previous_loaded:
                    atomic_json(state_path, {**previous, "schema_version": SCHEMA, "symbol": symbol,
                                            "last_attempt": row, "source_status": row["source_status"]})
            atomic_json(audit_path, audit)
    finally:
        # Keep the OS lock until any submitted background work has really exited.
        if hasattr(service, "executor"):
            service.executor.shutdown(wait=True, cancel_futures=False)
    audit.update(status="partial_failure" if audit["counts"]["failed"] else "complete", completed_at=now())
    atomic_json(audit_path, audit)
    atomic_json(state_root / "latest.json", audit)
    return audit, 1 if audit["counts"]["failed"] else 0


def run_config(value, *, dry_run=False, fetcher=None, job_factory=None, sleeper=time.sleep):
    config = parse_config(value)
    if dry_run:
        return {"schema_version": SCHEMA, "status": "configuration_valid", "dry_run": True,
                "symbols": config["symbols"], "history_auto_run": False, "publication": "none",
                "source_root": str(config["source_root"]), "jobs_root": str(config["jobs_root"]),
                "state_root": str(config["state_root"]), "minimum_rows": config["minimum_rows"],
                "long_window_rows": config["long_window_rows"]}, 0
    with refresh_lock(config["state_root"]):
        return _run_locked(config, fetcher or fetch_snapshot, job_factory or GlobalJobs, sleeper)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Absolute path to local JSON configuration")
    parser.add_argument("--dry-run", action="store_true", help="Validate only; no download, fit or file writes")
    args = parser.parse_args()
    if not args.config.is_absolute():
        parser.error("--config must be absolute")
    try:
        audit, code = run_config(json.loads(args.config.read_text(encoding="utf-8-sig")), dry_run=args.dry_run)
    except AlreadyRunning as error:
        print(json.dumps({"status": "already_running", "error": str(error)}))
        return 75
    except (ValueError, OSError) as error:
        print(json.dumps({"status": "configuration_error", "error": str(error)}))
        return 2
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
