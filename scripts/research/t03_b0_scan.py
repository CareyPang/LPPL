#!/usr/bin/env python3
"""Run one deterministic shard of the frozen future-only B0 development scan."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import platform
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import scipy

from research.eval.dataset import price_series
from research.eval.top_time.contracts import LABEL_VERSION, SCORING_CONTRACT_VERSION
from research.features.lppls_scan import asof_dates, calendar, window_eligibility
from research.labels.run_top import FROZEN
from research.lppls.future_contract import (
    CONTRACT_VERSION,
    DEFAULT_FILTER_BOUNDS,
    DEFAULT_SEARCH_BOUNDS,
    LogPrice,
    fit_window,
)
from research.lppls.window_clusters import SCALE_WINDOWS

ROOT = Path(__file__).resolve().parents[2]
PREREG_PATH = ROOT / "reports/lppls_handoff/t06a_20261116_a1/preregistration.json"
PREREG_SHA256 = "3e8651b1ccaf2bc7dc944af746b03917f6291ad537b979b0612556278b2daaab"
SYMBOLS = ("sh000001", "sh000016", "sh000300", "sh000905", "sz399001", "sz399006")
WINDOWS = tuple(window for scale in SCALE_WINDOWS.values() for window in scale)
T01_CONTRACT_PATH = ROOT / "reports/lppls_handoff/t01_20261116_a1/fit_contract_frozen.json"
T02_CONTRACT_PATH = ROOT / "reports/lppls_handoff/t02_20261116_a1/scoring_contract_frozen.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_value(value):
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


class JsonlGzWriter:
    def __init__(self, path: Path):
        self._raw = path.open("wb")
        self._stream = gzip.GzipFile(fileobj=self._raw, mode="wb", mtime=0)
        self.rows = 0

    def write(self, row: dict) -> None:
        encoded = json.dumps(
            _json_value(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        self._stream.write((encoded + "\n").encode("utf-8"))
        self.rows += 1

    def close(self) -> None:
        self._stream.close()
        self._raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def verify_prereg() -> dict:
    raw = PREREG_PATH.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != PREREG_SHA256:
        raise ValueError(f"frozen preregistration SHA-256 mismatch: {actual}")
    prereg = json.loads(raw)
    if tuple(prereg["sample"]["symbols"]) != SYMBOLS:
        raise ValueError("registered symbols differ from scanner symbols")
    if prereg["fit_budget"]["window_grid"]["total"] != len(WINDOWS):
        raise ValueError("registered window count differs from the fixed scale grids")
    return prereg


def parse_shard(value: str) -> tuple[int, int]:
    try:
        index_text, total_text = value.split("/", maxsplit=1)
        index, total = int(index_text), int(total_text)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("shard must be i/N with zero-based i") from exc
    if total < 1 or not 0 <= index < total:
        raise argparse.ArgumentTypeError("shard must satisfy 0 <= i < N")
    return index, total


def planned_asofs(symbol: str, mode: str, sessions: pd.DatetimeIndex) -> list[pd.Timestamp]:
    if symbol not in SYMBOLS:
        raise ValueError(f"unregistered symbol: {symbol}")
    dates = asof_dates(symbol, "index", sessions, ("dev",))
    if mode == "pilot":
        if symbol != "sh000300":
            raise ValueError("pilot mode is restricted to sh000300")
        dates = [date for date in dates if date.year == 2015]
    return dates


def verify_full_plan(sessions: pd.DatetimeIndex) -> int:
    total = sum(len(planned_asofs(symbol, "full", sessions)) for symbol in SYMBOLS)
    if total != 4236:
        raise ValueError(f"full plan has {total} symbol-asofs; preregistration requires 4236")
    return total


def _identity(
    run_id: str,
    symbol: str,
    asof: str,
    window: int,
    data_hash: str,
    contract_hash: str,
    scoring_contract_hash: str,
) -> dict:
    return {
        "run_id": run_id,
        "asset": symbol,
        "symbol": symbol,
        "asof": asof,
        "n": window,
        "window": {"L": window},
        "contract_version": CONTRACT_VERSION,
        "contract_hash": contract_hash,
        "scoring_contract_hash": scoring_contract_hash,
        "scoring_contract_version": SCORING_CONTRACT_VERSION,
        "label_version": LABEL_VERSION,
        "data_hash": data_hash,
    }


def _empty_candidate(identity: dict, status: str, reason: str | None) -> dict:
    return {
        **identity,
        "status": status,
        "reason": reason,
        "theta": None,
        "beta": None,
        "sse": None,
        "finite": False,
        "filter_outcome": {"status": "not_evaluated", "reasons": []},
        "attempt_id": None,
        "cache_key": None,
        "tc_offset_bars": None,
        "bar_to_session_index": None,
    }


def scan(args: argparse.Namespace) -> dict:
    verify_prereg()
    shard_index, shard_total = args.shard
    if args.mode not in {"pilot", "full"}:
        raise ValueError("mode must be pilot or full")
    sessions = calendar()
    full_asof_count = verify_full_plan(sessions) if args.mode == "full" else None
    all_asofs = planned_asofs(args.symbol, args.mode, sessions)
    selected_asofs = all_asofs[shard_index::shard_total]
    if not selected_asofs:
        raise ValueError("selected shard has no planned as-of sessions")

    series = price_series(args.symbol)
    if not series.index.is_monotonic_increasing or series.index.has_duplicates:
        raise ValueError("frozen price series must have unique increasing dates")
    data_path = FROZEN / f"{args.symbol}_qfq.parquet"
    data_hash = sha256_file(data_path)
    contract_hash = sha256_file(T01_CONTRACT_PATH)
    scoring_contract_hash = sha256_file(T02_CONTRACT_PATH)
    calendar_positions = {date: index for index, date in enumerate(sessions)}
    price_positions = {date: index for index, date in enumerate(series.index)}
    out = Path(args.out).resolve()
    if out.exists():
        raise FileExistsError(f"refusing to overwrite output directory: {out}")
    out.mkdir(parents=True, exist_ok=False)

    source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    manifest = {
        "schema_version": "t03_b0_shard_v1",
        "run_id": args.run_id,
        "mode": args.mode,
        "symbol": args.symbol,
        "shard": {"index": shard_index, "total": shard_total},
        "preregistration_sha256": PREREG_SHA256,
        "source_head": source_sha,
        "planned_symbol_asofs": full_asof_count,
        "symbol_asofs": len(all_asofs),
        "shard_asofs": len(selected_asofs),
        "window_count": len(WINDOWS),
        "data_path": str(data_path.relative_to(ROOT)),
        "data_sha256": data_hash,
        "fit_contract_sha256": contract_hash,
        "scoring_contract_sha256": scoring_contract_hash,
        "fit_contract_version": CONTRACT_VERSION,
        "scoring_contract_version": SCORING_CONTRACT_VERSION,
        "label_version": LABEL_VERSION,
        "search_bounds": DEFAULT_SEARCH_BOUNDS.to_dict(),
        "filter_bounds": DEFAULT_FILTER_BOUNDS.to_dict(),
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "pandas": pd.__version__,
            "thread_env": {
                name: os.environ.get(name)
                for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
            },
        },
        "started_at_utc": datetime.now(UTC).isoformat(),
        "eligibility_source": "research.features.lppls_scan.window_eligibility",
        "fit_clock": "effective_bars",
        "pilot_is_effect_size_comparison": False,
    }
    (out / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    totals = {"planned": 0, "done": 0, "failed": 0, "ineligible": 0, "unresolved": 0}
    started = time.perf_counter()
    with (
        JsonlGzWriter(out / "fit_attempts.jsonl.gz") as attempts_writer,
        JsonlGzWriter(out / "candidate_fits.jsonl.gz") as candidates_writer,
        JsonlGzWriter(out / "window_results.jsonl.gz") as windows_writer,
        JsonlGzWriter(out / "scan_ledger.jsonl.gz") as scans_writer,
    ):
        for asof_date in selected_asofs:
            asof = asof_date.strftime("%Y-%m-%d")
            asof_position = price_positions.get(asof_date)
            if asof_position is None:
                raise ValueError(f"planned as-of not present in price series: {asof}")
            eligibility = window_eligibility(
                asof_position, series.index, WINDOWS, calendar_positions
            )
            asof_counts = {"planned": len(WINDOWS), "done": 0, "failed": 0,
                           "ineligible": 0, "unresolved": 0}
            for window in WINDOWS:
                identity = _identity(
                    args.run_id, args.symbol, asof, window, data_hash,
                    contract_hash, scoring_contract_hash,
                )
                reason = eligibility[window]
                if reason is not None:
                    status = "ineligible"
                    asof_counts["ineligible"] += 1
                    candidate = _empty_candidate(identity, status, reason)
                    window_row = {**identity, "status": status, "reason": reason,
                                  "attempt_id": None, "attempt_count": 0}
                    candidates_writer.write(candidate)
                    windows_writer.write(window_row)
                    continue

                start_position = asof_position + 1 - window
                bar_dates = series.index[start_position : asof_position + 1]
                try:
                    bar_map = [calendar_positions[date] for date in bar_dates]
                except KeyError:
                    status = "unresolved"
                    reason = "price_bar_missing_from_frozen_calendar"
                    asof_counts["failed"] += 1
                    asof_counts["unresolved"] += 1
                    candidates_writer.write(_empty_candidate(identity, status, reason))
                    windows_writer.write({**identity, "status": status, "reason": reason,
                                          "attempt_id": None, "attempt_count": 0})
                    continue
                window_start = bar_dates[0].strftime("%Y-%m-%d")
                window_end = bar_dates[-1].strftime("%Y-%m-%d")
                fit_started = time.perf_counter()
                try:
                    result = fit_window(
                        LogPrice.from_log_price(
                            series.iloc[start_position : asof_position + 1].to_numpy(),
                            source_field="close",
                            adjustment_type="qfq",
                        ),
                        data_hash=data_hash,
                        asof=asof,
                        window_start=window_start,
                        window_end=window_end,
                        lookback_L=window,
                        bar_to_session_index=bar_map,
                        seed_retries=((DEFAULT_SEARCH_BOUNDS.seed, 0),),
                    )
                except Exception as exc:  # noqa: BLE001
                    status = "unresolved"
                    reason = f"{type(exc).__name__}: {exc}"
                    asof_counts["failed"] += 1
                    asof_counts["unresolved"] += 1
                    candidates_writer.write(_empty_candidate(identity, status, reason))
                    windows_writer.write({**identity, "status": status, "reason": reason,
                                          "attempt_id": None, "attempt_count": 0})
                    continue
                elapsed_fit = time.perf_counter() - fit_started
                identity.update({
                    "window_start": window_start,
                    "window_end": window_end,
                    "clock_map_hash": hashlib.sha256(
                        json.dumps(bar_map, separators=(",", ":")).encode("ascii")
                    ).hexdigest(),
                })
                result_dict = result.to_dict()
                attempt_dicts = result_dict.pop("attempts")
                for attempt in attempt_dicts:
                    attempts_writer.write({
                        **identity,
                        **attempt,
                        "elapsed_fit_seconds": elapsed_fit,
                    })
                best = min(
                    (attempt for attempt in attempt_dicts if attempt["status"] == "success"),
                    key=lambda attempt: attempt["sse"],
                    default=None,
                )
                candidate = {
                    **identity,
                    "status": result.status,
                    "reason": result_dict.get("filter_outcome", {}).get("reasons"),
                    "theta": best["theta"] if best else None,
                    "beta": best["beta"] if best else None,
                    "sse": best["sse"] if best else None,
                    "finite": bool(best and best["finite"]),
                    "filter_outcome": result.filter_outcome.to_dict(),
                    "attempt_id": best["attempt_id"] if best else None,
                    "cache_key": best["cache_key"] if best else None,
                    "tc_offset_bars": result.tc_offset_bars,
                    "bar_to_session_index": bar_map,
                    "elapsed_fit_seconds": elapsed_fit,
                }
                window_row = {**identity, **result_dict, "attempt_id": best["attempt_id"] if best else None}
                candidates_writer.write(candidate)
                windows_writer.write(window_row)
                if result.status == "fit_ok":
                    asof_counts["done"] += 1
                elif result.status == "all_attempts_failed":
                    asof_counts["failed"] += 1
                    asof_counts["unresolved"] += 1
                else:
                    asof_counts["failed"] += 1
                    asof_counts["unresolved"] += 1
            if asof_counts["planned"] != (
                asof_counts["done"] + asof_counts["failed"] + asof_counts["ineligible"]
            ):
                raise AssertionError(f"window conservation failed for {args.symbol} {asof}")
            totals = {key: totals[key] + asof_counts[key] for key in totals}
            scans_writer.write({
                "run_id": args.run_id,
                "asset": args.symbol,
                "symbol": args.symbol,
                "asof": asof,
                "data_hash": data_hash,
                "contract_hash": manifest["fit_contract_sha256"],
                "scoring_contract_hash": manifest["scoring_contract_sha256"],
                **asof_counts,
                "status": "complete" if asof_counts["failed"] == 0 else "partial",
            })
    manifest.update({
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "elapsed_seconds": time.perf_counter() - started,
        "totals": totals,
        "fit_attempt_rows": attempts_writer.rows,
        "candidate_fit_rows": candidates_writer.rows,
        "window_result_rows": windows_writer.rows,
        "scan_ledger_rows": scans_writer.rows,
    })
    (out / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True, choices=SYMBOLS)
    parser.add_argument("--shard", required=True, type=parse_shard)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--mode", choices=("pilot", "full"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", args.run_id):
        parser.error("run-id must match [A-Za-z0-9_.-]{1,64}")
    result = scan(args)
    print(json.dumps({
        "run_id": result["run_id"],
        "symbol": result["symbol"],
        "mode": result["mode"],
        "shard": result["shard"],
        "shard_asofs": result["shard_asofs"],
        "totals": result["totals"],
        "elapsed_seconds": result["elapsed_seconds"],
        "output": str(Path(args.out).resolve()),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
