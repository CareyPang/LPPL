#!/usr/bin/env python3
"""Merge T03 shards, conserve planned windows, and score frozen research arms."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import platform
import shutil
import subprocess
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.eval.top_time.contracts import Protocol
from research.eval.top_time.labels import build_labels
from research.eval.top_time.t02 import (
    AppendOnlyClaimLedger,
    _next_target,
    action_session_after_close,
    formal_interval_gate,
    score_t02,
    unknown_label_rows,
)
from research.features.lppls_scan import calendar
from research.labels.run_top import FROZEN
from research.lppls.window_clusters import (
    SCALE_WINDOWS,
    analyze_asof,
    selected_windows,
)
from scripts.research.t03_b0_scan import (
    PREREG_PATH,
    PREREG_SHA256,
    SYMBOLS,
    T01_CONTRACT_PATH,
    T02_CONTRACT_PATH,
    JsonlGzWriter,
    planned_asofs,
    sha256_file,
)

ROOT = Path(__file__).resolve().parents[2]
T00_DIR = ROOT / "reports/lppls_handoff/t00_20261116_a1"
T01_DIR = ROOT / "reports/lppls_handoff/t01_20261116_a1"
T02_DIR = ROOT / "reports/lppls_handoff/t02_20261116_a1"
ARM_NAMES = ("B0", "W1", "C1", "calendar_fixed_10")
SCOPES = ("short", "stage")
HORIZON = 63
MINIMUM_LEAD = 5
MAXIMUM_WIDTH = 10
BOOTSTRAP_SEED = 20261116


def validate_conservation(planned: int, done: int, failed: int, ineligible: int) -> None:
    if planned != done + failed + ineligible:
        raise ValueError(
            f"window conservation failed: planned={planned}, done={done}, "
            f"failed={failed}, ineligible={ineligible}"
        )


def interval_distance(event_session: int, start: int, end: int) -> int:
    if end < start:
        raise ValueError("interval end precedes start")
    if start <= event_session <= end:
        return 0
    return start - event_session if event_session < start else event_session - end


def hit_k(event_session: int, action_session: int, start: int, end: int, k: int) -> int:
    if k < 0:
        raise ValueError("k must be non-negative")
    return int(event_session - action_session >= 1 and interval_distance(event_session, start, end) <= k)


def random_placement_expectation(
    action_session: int,
    width: int,
    event_session: int,
    k: int,
    horizon: int = HORIZON,
) -> float:
    if width < 1 or horizon < 1 or k < 0:
        raise ValueError("width and horizon must be positive and k non-negative")
    if event_session - action_session < 1:
        return 0.0
    first = action_session + 1
    last = max(first, action_session + horizon - width + 1)
    starts = range(first, last + 1)
    return sum(
        interval_distance(event_session, start, start + width - 1) <= k
        for start in starts
    ) / len(starts)


def year_block_bootstrap(
    years: list[int],
    values: list[float],
    *,
    n_resamples: int = 10_000,
    seed: int = BOOTSTRAP_SEED,
    confidence: float = 0.975,
) -> tuple[float | None, float | None]:
    if len(years) != len(values):
        raise ValueError("years and values must have equal lengths")
    if not years:
        return None, None
    year_order = sorted(set(years))
    sums = np.asarray([sum(v for y, v in zip(years, values, strict=True) if y == year) for year in year_order])
    counts = np.asarray([sum(y == year for y in years) for year in year_order])
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(year_order), size=(n_resamples, len(year_order)))
    numerators = sums[draws].sum(axis=1)
    denominators = counts[draws].sum(axis=1)
    means = numerators / denominators
    alpha = (1.0 - confidence) / 2.0
    low, high = np.quantile(means, [alpha, 1.0 - alpha])
    return float(low), float(high)


def _read_jsonl_gz(path: Path) -> list[dict]:
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
    return rows


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    if fieldnames is None:
        fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_shards(
    input_dir: Path,
    *,
    run_id: str,
    mode: str,
    symbols: tuple[str, ...],
    shard_count: int,
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    manifest_paths = sorted(input_dir.rglob("run_manifest.json"))
    if not manifest_paths:
        raise ValueError(f"no shard manifests found under {input_dir}")
    manifests = [json.loads(path.read_text(encoding="utf-8")) for path in manifest_paths]
    found: set[tuple[str, int]] = set()
    source_heads = set()
    fit_contract_hashes = set()
    scoring_contract_hashes = set()
    data_hashes = {}
    for manifest, path in zip(manifests, manifest_paths, strict=True):
        shard = manifest["shard"]
        key = (manifest["symbol"], int(shard["index"]))
        if key in found:
            raise ValueError(f"duplicate shard {key}")
        found.add(key)
        source_heads.add(manifest.get("source_head"))
        fit_contract_hashes.add(manifest.get("fit_contract_sha256"))
        scoring_contract_hashes.add(manifest.get("scoring_contract_sha256"))
        if manifest.get("window_count") != 95:
            raise ValueError(f"unexpected window count in shard manifest: {path}")
        symbol_hash = manifest.get("data_sha256")
        previous_hash = data_hashes.setdefault(manifest["symbol"], symbol_hash)
        if previous_hash != symbol_hash:
            raise ValueError(f"inconsistent frozen data hash for {manifest['symbol']}")
        if (
            manifest.get("run_id") != run_id
            or manifest.get("mode") != mode
            or manifest.get("preregistration_sha256") != PREREG_SHA256
            or int(shard["total"]) != shard_count
        ):
            raise ValueError(f"shard manifest does not match requested run: {path}")
        if manifest["symbol"] not in symbols:
            raise ValueError(f"unexpected symbol in shard manifest: {manifest['symbol']}")
    if len(source_heads) != 1 or None in source_heads:
        raise ValueError("shards were produced from different or missing source heads")
    if len(fit_contract_hashes) != 1 or None in fit_contract_hashes:
        raise ValueError("shard fit-contract hashes differ or are missing")
    if len(scoring_contract_hashes) != 1 or None in scoring_contract_hashes:
        raise ValueError("shard scoring-contract hashes differ or are missing")
    expected = {(symbol, index) for symbol in symbols for index in range(shard_count)}
    if found != expected:
        missing, extra = sorted(expected - found), sorted(found - expected)
        raise ValueError(f"incomplete shard set; missing={missing}, extra={extra}")

    attempts, candidates, windows, scans = [], [], [], []
    for manifest_path in manifest_paths:
        shard_dir = manifest_path.parent
        for target, filename in (
            (attempts, "fit_attempts.jsonl.gz"),
            (candidates, "candidate_fits.jsonl.gz"),
            (windows, "window_results.jsonl.gz"),
            (scans, "scan_ledger.jsonl.gz"),
        ):
            source = shard_dir / filename
            if not source.is_file():
                raise ValueError(f"missing shard ledger: {source}")
            target.extend(_read_jsonl_gz(source))
    window_keys = [(row["symbol"], row["asof"], row["n"]) for row in windows]
    candidate_keys = [(row["symbol"], row["asof"], row["n"]) for row in candidates]
    if len(set(window_keys)) != len(window_keys):
        raise ValueError("duplicate symbol-asof-window result")
    if len(set(candidate_keys)) != len(candidate_keys) or set(candidate_keys) != set(window_keys):
        raise ValueError("candidate and window-result ledgers have different window identities")
    attempts_by_window: dict[tuple[str, str, int], list[dict]] = defaultdict(list)
    for attempt in attempts:
        key = (attempt["symbol"], attempt["asof"], attempt["n"])
        attempts_by_window[key].append(attempt)
    for row in windows:
        key = (row["symbol"], row["asof"], row["n"])
        expected_attempts = int(row["status"] in {"fit_ok", "all_attempts_failed"})
        if len(attempts_by_window[key]) != expected_attempts:
            raise ValueError(f"unexpected attempt count for {key}")
    return manifests, attempts, candidates, windows, scans


def _assert_scan_conservation(scan_rows: list[dict], window_rows: list[dict]) -> None:
    expected_windows = {window for grid in SCALE_WINDOWS.values() for window in grid}
    per_asof: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in scan_rows:
        validate_conservation(row["planned"], row["done"], row["failed"], row["ineligible"])
        per_asof[(row["symbol"], row["asof"])]
    for row in window_rows:
        per_asof[(row["symbol"], row["asof"])].append(row)
    if set(per_asof) != {(row["symbol"], row["asof"]) for row in scan_rows}:
        raise ValueError("window results contain an unplanned symbol-asof")
    if len({(row["symbol"], row["asof"]) for row in scan_rows}) != len(scan_rows):
        raise ValueError("duplicate scan-ledger symbol-asof")
    for key, rows in per_asof.items():
        if (
            len(rows) != len(expected_windows)
            or {row["n"] for row in rows} != expected_windows
        ):
            raise ValueError(f"expected exactly 95 unique planned windows for {key}")
        counts = defaultdict(int)
        for row in rows:
            status = row["status"]
            if status in {"fit_ok"}:
                counts["done"] += 1
            elif status == "ineligible":
                counts["ineligible"] += 1
            else:
                counts["failed"] += 1
                if status in {"unresolved", "pending", "all_attempts_failed"}:
                    counts["unresolved"] += 1
        scan = next(row for row in scan_rows if (row["symbol"], row["asof"]) == key)
        if scan["planned"] != len(expected_windows):
            raise ValueError(f"unexpected planned window count for {key}")
        if any(scan[name] != counts[name] for name in ("done", "failed", "ineligible", "unresolved")):
            raise ValueError(f"scan/window ledger count mismatch for {key}")


def _label_books(symbols: tuple[str, ...]) -> tuple[dict[str, Any], list[str]]:
    sessions = calendar()
    sessions = sessions[sessions <= pd.Timestamp("2019-12-31")]
    session_strings = [date.strftime("%Y-%m-%d") for date in sessions]
    books = {}
    for symbol in symbols:
        frame = pd.read_parquet(FROZEN / f"{symbol}_qfq.parquet")
        prices = {pd.Timestamp(row.date): float(row.close) for row in frame.itertuples(index=False)}
        aligned = [prices.get(date) for date in sessions]
        books[symbol] = build_labels(
            symbol,
            session_strings,
            aligned,
            config=Protocol(),
            asof_session=len(session_strings) - 1,
            input_status="FROZEN_QFQ_DEVELOPMENT_DIAGNOSTIC",
        )
    return books, session_strings


def _eligible_fits_for_asof(
    symbol: str,
    asof: str,
    candidates: list[dict],
    window_rows: list[dict],
) -> tuple[pd.DataFrame, list[int]]:
    eligibility = {
        row["n"] for row in window_rows
        if row["symbol"] == symbol and row["asof"] == asof and row["status"] != "ineligible"
    }
    source = {
        row["n"]: row for row in candidates
        if row["symbol"] == symbol and row["asof"] == asof
    }
    records = []
    for window in sorted(eligibility):
        row = source[window]
        theta = row.get("theta") or [np.nan, np.nan, np.nan]
        beta = row.get("beta") or [np.nan, np.nan, np.nan, np.nan]
        records.append({
            "date": pd.Timestamp(asof),
            "n": window,
            "tc": theta[0],
            "m": theta[1],
            "w": theta[2],
            "B": beta[1],
            "t01_qualified": (
                row["status"] == "fit_ok"
                and row.get("filter_outcome", {}).get("status") == "pass"
            ),
        })
    return pd.DataFrame(records, columns=("date", "n", "tc", "m", "w", "B", "t01_qualified")), sorted(eligibility)


def _asof_arms(
    symbol: str,
    asof: str,
    asof_position: int,
    fits: pd.DataFrame,
    expected_windows: list[int],
) -> dict[str, dict]:
    def qualify(frame: pd.DataFrame) -> pd.Series:
        return frame["t01_qualified"]

    analyses = {
        name: analyze_asof(
            fits,
            expected_windows,
            mode="thin" if name == "W1" else "full",
            qualified_predicate=qualify,
        )
        for name in ("B0", "W1", "C1")
    }
    thin_set = {window for windows in selected_windows("thin").values() for window in windows}
    source = {int(row.n): row for row in fits.itertuples(index=False)}
    for window in thin_set.intersection(expected_windows):
        if window not in source:
            raise AssertionError(f"W1 window {window} is missing from B0 fits for {symbol} {asof}")
    result: dict[str, dict] = {}
    for arm, analysis in analyses.items():
        interval = None
        status = "no_alert"
        if arm in {"B0", "W1"}:
            scale_ok = analysis["evaluable"]
            alarm = any(item["alarm"] for item in analysis["scales"].values())
            if scale_ok and alarm:
                ahead = [
                    fit["ahead"] for fit in analysis["fits"]
                    if fit["qualified"] and fit["expected"] and fit["ahead"] is not None
                ]
                if ahead:
                    lo, hi = np.quantile(np.asarray(ahead, dtype=float), [0.2, 0.8])
                    interval = (float(lo), float(hi))
                    status = "candidate"
                else:
                    status = "no_qualified_fit"
            elif not scale_ok:
                status = "incomplete_scale_status"
        else:
            cluster = analysis["clusters"]["cross"]["primary"]
            if cluster is not None:
                interval = (float(cluster["lo"]), float(cluster["hi"]))
                status = "candidate"
            elif not analysis["evaluable"]:
                status = "incomplete_scale_status"
        if interval is None:
            start = end = None
        else:
            start = asof_position + math.floor(interval[0])
            end = asof_position + math.ceil(interval[1])
        result[arm] = {
            "run_arm": arm,
            "symbol": symbol,
            "asof": asof,
            "asof_session": asof_position,
            "status": status,
            "interval_start": start,
            "interval_end": end,
            "ahead_lo": interval[0] if interval else None,
            "ahead_hi": interval[1] if interval else None,
            "window_mode": "thin" if arm == "W1" else "full",
            "qualified_count": sum(record["qualified"] for record in analysis["fits"]),
            "evaluable": analysis["evaluable"],
            "analysis": analysis,
        }
    for window in thin_set.intersection(expected_windows):
        b0_row = source[window]
        w1_records = {record["n"]: record for record in analyses["W1"]["fits"]}
        if window not in w1_records:
            raise AssertionError(f"W1 analysis omitted selected B0 fit {window} for {symbol} {asof}")
        if bool(w1_records[window]["qualified"]) != bool(b0_row.t01_qualified):
            raise AssertionError(f"W1 qualification differs from B0 fit {window} for {symbol} {asof}")
    return result


def _candidate_predictions(
    symbols: tuple[str, ...],
    scan_rows: list[dict],
    candidate_rows: list[dict],
    window_rows: list[dict],
    session_strings: list[str],
) -> list[dict]:
    sessions = pd.DatetimeIndex(session_strings)
    positions = {date.strftime("%Y-%m-%d"): index for index, date in enumerate(sessions)}
    by_asof = sorted({(row["symbol"], row["asof"]) for row in scan_rows})
    identity_by_asof = {}
    for row in candidate_rows:
        identity_by_asof.setdefault((row["symbol"], row["asof"]), row)
    output = []
    for symbol, asof in by_asof:
        fits, expected = _eligible_fits_for_asof(symbol, asof, candidate_rows, window_rows)
        analyses = _asof_arms(symbol, asof, positions[asof], fits, expected)
        identity = identity_by_asof[(symbol, asof)]
        for arm in ("B0", "W1", "C1"):
            row = analyses[arm].copy()
            row.pop("analysis", None)
            row.update({
                "data_hash": identity.get("data_hash"),
                "fit_contract_hash": identity.get("contract_hash"),
                "scoring_contract_hash": identity.get("scoring_contract_hash"),
                "label_version": identity.get("label_version"),
            })
            output.append(row)
        action = action_session_after_close(session_strings, positions[asof])
        output.append({
            "run_arm": "calendar_fixed_10",
            "symbol": symbol,
            "asof": asof,
            "asof_session": positions[asof],
            "status": "candidate",
            "interval_start": action + 5,
            "interval_end": action + 14,
            "ahead_lo": None,
            "ahead_hi": None,
            "window_mode": "fixed",
            "qualified_count": None,
            "evaluable": True,
            "data_hash": identity.get("data_hash"),
            "fit_contract_hash": identity.get("contract_hash"),
            "scoring_contract_hash": identity.get("scoring_contract_hash"),
            "label_version": identity.get("label_version"),
        })
    return output


def _claim_id(*parts: Any) -> str:
    encoded = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_claims(
    predictions: list[dict],
    books: dict[str, Any],
    sessions: list[str],
) -> tuple[list[dict], dict[tuple[str, str], list[dict]]]:
    raw_rows: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_symbol_arm: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for prediction in predictions:
        by_symbol_arm[(prediction["symbol"], prediction["run_arm"])].append(prediction)
    for (symbol, arm), rows in by_symbol_arm.items():
        ledger = AppendOnlyClaimLedger()
        state: dict[str, dict | None] = {"short": None, "stage": None}
        for prediction in sorted(rows, key=lambda row: (row["asof"], row["run_arm"])):
            if prediction["interval_start"] is None or prediction["interval_end"] is None:
                continue
            published = int(prediction["asof_session"])
            action = action_session_after_close(sessions, published)
            start, end = int(prediction["interval_start"]), int(prediction["interval_end"])
            gate = formal_interval_gate(action, start, end)
            for scope in SCOPES:
                current = state[scope]
                if current is None or action > current["expiry"]:
                    current = {
                        "episode_id": "episode_" + _claim_id(symbol, arm, scope, action)[:24],
                        "raw_first_interval": (start, end),
                        "raw_first_clock": action,
                        "raw_expiry": action + HORIZON,
                        "first_formal": None,
                        "last_claim_id": None,
                        "expiry": action + HORIZON,
                    }
                    state[scope] = current
                first_formal = current["first_formal"]
                if gate["formal"] and first_formal is None:
                    kind = "new"
                    first_interval = (start, end)
                    first_clock = action
                    expiry = action + HORIZON
                    first_formal = {
                        "interval": first_interval,
                        "clock": first_clock,
                        "expiry": expiry,
                    }
                    current["first_formal"] = first_formal
                    current["expiry"] = expiry
                elif gate["formal"]:
                    kind = "revision"
                    first_interval = first_formal["interval"]
                    first_clock = first_formal["clock"]
                    expiry = first_formal["expiry"]
                else:
                    kind = "observation"
                    if first_formal is None:
                        first_interval = current["raw_first_interval"]
                        first_clock = current["raw_first_clock"]
                        expiry = current["raw_expiry"]
                    else:
                        first_interval = first_formal["interval"]
                        first_clock = first_formal["clock"]
                        expiry = first_formal["expiry"]
                claim_id = "claim_" + _claim_id(
                    symbol, arm, scope, prediction["asof"], start, end
                )[:32]
                row = {
                    "claim_id": claim_id,
                    "parent_claim_id": current["last_claim_id"],
                    "episode_id": current["episode_id"],
                    "kind": kind,
                    "scope": scope,
                    "symbol": symbol,
                    "arm": arm,
                    "asof": prediction["asof"],
                    "published_session": published,
                    "action_session": action,
                    "interval_start": start,
                    "interval_end": end,
                    "first_interval_start": first_interval[0],
                    "first_interval_end": first_interval[1],
                    "first_clock_session": first_clock,
                    "fixed_expiry_session": expiry,
                    "mode": "historical_replay",
                    "first_visible_at": None,
                    "simulated_available_at": f"{prediction['asof']}T17:00:00+08:00",
                    "simulated_action_session": action,
                    "delay_assumption": (
                        "hypothetical full-close output available by 17:00 Asia/Shanghai; "
                        "actionable on the next frozen-calendar session"
                    ),
                    "pit_evidence": None,
                    "vintage_status": "HISTORICAL_VINTAGE_NOT_ESTABLISHED",
                    "geometry": gate,
                    "full_close_data": True,
                    "published_session_close_at": f"{prediction['asof']}T15:00:00+08:00",
                    "data_hash": prediction.get("data_hash"),
                    "fit_contract_hash": prediction.get("fit_contract_hash"),
                    "scoring_contract_hash": prediction.get("scoring_contract_hash"),
                    "label_version": prediction.get("label_version"),
                }
                accepted = ledger.append(row)
                normalized = dict(accepted)
                raw_rows[(symbol, arm)].append(normalized)
                current["last_claim_id"] = claim_id
    return (
        [row for key in sorted(raw_rows) for row in raw_rows[key]],
        dict(raw_rows),
    )


def _event_by_anchor(book) -> dict[tuple[str, int], Any]:
    result = {}
    for event in sorted(book.events, key=lambda item: (item.scale, item.peak_session, item.event_id)):
        result.setdefault((event.scale, event.peak_session), event)
    return result


def _event_scores(
    book,
    claims: list[dict],
    *,
    start_session: int,
    end_session: int,
    data_evaluable_ids: set[str],
) -> tuple[list[dict], dict]:
    first_by_episode: dict[tuple[str, str], dict] = {}
    for row in claims:
        key = (row["episode_id"], row["scope"])
        previous = first_by_episode.get(key)
        if previous is None or (row["action_session"], row["claim_id"]) < (
            previous["action_session"], previous["claim_id"]
        ):
            first_by_episode[key] = row
    first_claims = sorted(
        first_by_episode.values(),
        key=lambda row: (row["action_session"], row["claim_id"]),
    )
    event_by_anchor = _event_by_anchor(book)
    matched: dict[tuple[str, str], dict] = {}
    pending_rows = []
    duplicates = 0
    for claim in first_claims:
        status, event, blocker = _next_target(
            book, event_by_anchor, claim["scope"], claim["action_session"], HORIZON
        )
        if status == "pending":
            pending_rows.append({
                "claim_id": claim["claim_id"],
                "scope": claim["scope"],
                "blocker_session": blocker,
            })
            continue
        if status != "event" or event is None:
            continue
        key = (claim["scope"], event.event_id)
        if key in matched:
            duplicates += 1
            continue
        matched[key] = claim

    rows = []
    for event in book.events:
        if not start_session <= event.peak_session <= end_session:
            continue
        first_claim = matched.get((event.scale, event.event_id))
        evaluable = event.event_id in data_evaluable_ids
        claim = first_claim if evaluable else None
        lead = event.peak_session - first_claim["action_session"] if first_claim else None
        if claim:
            start, end = claim["interval_start"], claim["interval_end"]
            width = end - start + 1
            hits = {
                f"hit_{k}": hit_k(event.peak_session, claim["action_session"], start, end, k)
                for k in (0, 5, 10, 21)
            }
            randoms = {
                f"r_{k}": random_placement_expectation(
                    claim["action_session"], width, event.peak_session, k
                )
                for k in (0, 5, 10, 21)
            }
        else:
            hits = {f"hit_{k}": 0 for k in (0, 5, 10, 21)}
            randoms = {f"r_{k}": 0.0 for k in (0, 5, 10, 21)}
        rows.append({
            "symbol": book.symbol,
            "scope": event.scale,
            "event_id": event.event_id,
            "peak_session": event.peak_session,
            "peak_date": book.sessions[event.peak_session],
            "support_end": event.support_end,
            "label_available_session": event.label_available_session,
            "label_version": event.label_version,
            "data_evaluable": evaluable,
            "first_claim_id": first_claim["claim_id"] if first_claim else None,
            "first_claim_kind": first_claim["kind"] if first_claim else None,
            "first_claim_action_session": first_claim["action_session"] if first_claim else None,
            "interval_start": first_claim["interval_start"] if first_claim else None,
            "interval_end": first_claim["interval_end"] if first_claim else None,
            "event_lead": lead,
            **hits,
            **randoms,
            **{f"S{k}": hits[f"hit_{k}"] - randoms[f"r_{k}"] for k in (0, 5, 10, 21)},
        })
    return rows, {"pending_first_claims": pending_rows, "duplicate_event_matches": duplicates}


def _data_evaluable_ids(
    book,
    scan_rows: list[dict],
    start_session: int,
    end_session: int,
) -> set[str]:
    session_positions = {date: index for index, date in enumerate(book.sessions)}
    asof_sessions = {
        symbol: sorted(
            (pd.Timestamp(row["asof"]), row)
            for row in scan_rows if row["symbol"] == symbol
        )
        for symbol in {row["symbol"] for row in scan_rows}
    }
    result = set()
    for event in book.events:
        if not start_session <= event.peak_session <= end_session:
            continue
        lo = event.peak_session - HORIZON
        relevant = [
            row for date, row in asof_sessions[book.symbol]
            if lo <= session_positions[date.strftime("%Y-%m-%d")] < event.peak_session
        ]
        if all(row.get("failed", 0) == 0 for row in relevant):
            result.add(event.event_id)
    return result


def _arm_metric_rows(
    books: dict[str, Any],
    claim_rows: list[dict],
    raw_claims: dict[tuple[str, str], list[dict]],
    scan_rows: list[dict],
    session_strings: list[str],
    mode: str,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    if mode == "pilot":
        return [], [], [], []
    positions = {date: index for index, date in enumerate(session_strings)}
    natural_rows, event_rows, attribution_rows, pending_rows = [], [], [], []
    for symbol, book in books.items():
        symbol_asofs = sorted(row["asof"] for row in scan_rows if row["symbol"] == symbol)
        if not symbol_asofs:
            raise ValueError(f"no planned scans for {symbol}")
        start_session = positions[symbol_asofs[0]] + HORIZON
        end_session = max(
            index for index, date in enumerate(session_strings) if date <= "2018-12-31"
        )
        if start_session > end_session:
            raise ValueError(f"deployment scope is empty for {symbol}")
        evaluable_ids = _data_evaluable_ids(book, scan_rows, start_session, end_session)
        for arm in ARM_NAMES:
            claims = raw_claims.get((symbol, arm), [])
            t02 = score_t02(
                book,
                claims,
                data_evaluable_event_ids=evaluable_ids,
                start_session=start_session,
                end_session=end_session,
            )
            t02_by_scope = t02["scopes"]
            primary_rows, primary_meta = _event_scores(
                book,
                claims,
                start_session=start_session,
                end_session=end_session,
                data_evaluable_ids=evaluable_ids,
            )
            for scope in SCOPES:
                scope_events = [row for row in primary_rows if row["scope"] == scope]
                event_rows.extend({**row, "arm": arm} for row in scope_events)
                metrics = t02_by_scope[scope]["metrics"]
                E = len(scope_events)
                if metrics.get("E") != E:
                    raise ValueError(
                        f"T02 and primary event denominators differ for {symbol}/{arm}/{scope}"
                    )
                row = {
                    "symbol": symbol,
                    "arm": arm,
                    "scope": scope,
                    "E": E,
                    "S0": sum(item["S0"] for item in scope_events) / E if E else None,
                    "S5": sum(item["S5"] for item in scope_events) / E if E else None,
                    "S10": sum(item["S10"] for item in scope_events) / E if E else None,
                    "S21": sum(item["S21"] for item in scope_events) / E if E else None,
                    "hit_0_rate": sum(item["hit_0"] for item in scope_events) / E if E else None,
                    "hit_5_rate": sum(item["hit_5"] for item in scope_events) / E if E else None,
                    "hit_10_rate": sum(item["hit_10"] for item in scope_events) / E if E else None,
                    "hit_21_rate": sum(item["hit_21"] for item in scope_events) / E if E else None,
                    "r_10_mean": sum(item["r_10"] for item in scope_events) / E if E else None,
                    "r_0_mean": sum(item["r_0"] for item in scope_events) / E if E else None,
                    "r_5_mean": sum(item["r_5"] for item in scope_events) / E if E else None,
                    "r_21_mean": sum(item["r_21"] for item in scope_events) / E if E else None,
                    "no_formal_alert_rate": metrics.get("no_formal_alert_rate"),
                    "first_window_coverage": metrics.get("first_window_coverage"),
                    "StrictStageRecall5W10": metrics.get("StrictStageRecall5W10") if scope == "stage" else None,
                    "strict_stage_miss_rate": (
                        1.0 - metrics["StrictStageRecall5W10"]
                        if scope == "stage" and metrics.get("StrictStageRecall5W10") is not None
                        else None
                    ),
                    "QualifiedStageRecall5": metrics.get("QualifiedStageRecall5") if scope == "stage" else None,
                    "no_formal_stage_alert_rate": metrics.get("no_formal_alert_rate") if scope == "stage" else None,
                    "first_interval_stage_coverage": metrics.get("first_window_coverage") if scope == "stage" else None,
                    "resolved_claim_precision": metrics.get("resolved_claim_precision"),
                    "notifications_per_asset_year": metrics.get("alerts_per_asset_year"),
                    "alert_occupied_sessions": metrics.get("alarm_occupied_days"),
                    "asset_years": metrics.get("asset_years"),
                    "formal_alerts": metrics.get("formal_alerts"),
                    "claim_notices": metrics.get("claim_notices"),
                    "duplicate_notices": metrics.get("duplicate_notices"),
                    "pending_claims": metrics.get("pending_claims"),
                    "revisions": metrics.get("revisions"),
                    "data_evaluable_E": metrics.get("data_evaluable_subset", {}).get("E"),
                    "data_failure_E": E - (metrics.get("data_evaluable_subset", {}).get("E") or 0),
                    "data_evaluable_strict_recall": (
                        metrics.get("data_evaluable_subset", {}).get("StrictStageRecall5W10")
                        if scope == "stage" else None
                    ),
                    "data_evaluable_qualified_stage_recall": (
                        metrics.get("data_evaluable_subset", {}).get("QualifiedStageRecall5")
                        if scope == "stage" else None
                    ),
                    "data_evaluable_no_formal_alert_rate": (
                        metrics.get("data_evaluable_subset", {}).get("no_formal_alert_rate")
                    ),
                    "data_evaluable_first_window_coverage": (
                        metrics.get("data_evaluable_subset", {}).get("first_window_coverage")
                    ),
                    "primary_duplicate_event_matches": primary_meta["duplicate_event_matches"],
                    "score_contract": t02["scoring_contract_version"],
                    "zero_denominator_is_null": True,
                }
                natural_rows.append(row)
                pending_rows.extend({
                    "symbol": symbol, "arm": arm, "scope": scope, **pending,
                } for pending in primary_meta["pending_first_claims"] if pending["scope"] == scope)
                for event in scope_events:
                    claim_id = event["first_claim_id"]
                    claim = next((item for item in claims if item["claim_id"] == claim_id), None)
                    gate = (
                        formal_interval_gate(
                            claim["action_session"], claim["interval_start"], claim["interval_end"]
                        )
                        if claim else None
                    )
                    lead = event["event_lead"]
                    peak = event["peak_session"]
                    start = event["interval_start"]
                    end = event["interval_end"]
                    flags = {
                        "data_not_evaluable": not event["data_evaluable"],
                        "no_alert": claim is None,
                        "reversed_non_future_beyond_H": bool(
                            gate and any(reason in gate["reasons"] for reason in ("reversed", "not_future", "beyond_H"))
                        ),
                        "too_wide": bool(gate and "too_wide" in gate["reasons"]),
                        "early_late": bool(
                            claim and (
                                end < peak or start > peak
                            )
                        ),
                        "insufficient_lead": bool(
                            claim and start - claim["action_session"] < MINIMUM_LEAD
                        ),
                        "success": bool(
                            claim and gate and gate["formal"] and start <= peak <= end
                            and lead is not None and lead >= MINIMUM_LEAD
                        ),
                    }
                    priority = (
                        "data_not_evaluable", "no_alert", "reversed_non_future_beyond_H",
                        "too_wide", "early_late", "insufficient_lead", "success",
                    )
                    primary = next((name for name in priority if flags[name]), "success")
                    attribution_rows.append({
                        "symbol": symbol,
                        "arm": arm,
                        "scope": scope,
                        "event_id": event["event_id"],
                        "peak_date": event["peak_date"],
                        "claim_id": claim_id,
                        **flags,
                        "primary_cause": primary,
                    })
    denominators = defaultdict(set)
    for row in natural_rows:
        denominators[(row["symbol"], row["scope"])].add(row["E"])
    if any(len(values) != 1 for values in denominators.values()):
        raise ValueError("mature-event denominator E differs across arms")
    return natural_rows, event_rows, attribution_rows, pending_rows


def _d1_rows(candidate_rows: list[dict], window_rows: list[dict]) -> list[dict]:
    by_id = {(row["symbol"], row["asof"], row["n"]): row for row in candidate_rows}
    counts: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: dict(Q=0, R=0, U=0, N=0))
    for window in window_rows:
        key = (window["symbol"], next(
            scale for scale, grid in SCALE_WINDOWS.items() if window["n"] in grid
        ))
        if window["status"] == "ineligible":
            counts[key]["N"] += 1
            continue
        candidate = by_id[(window["symbol"], window["asof"], window["n"])]
        if window["status"] != "fit_ok":
            counts[key]["U"] += 1
        elif candidate.get("filter_outcome", {}).get("status") == "pass":
            counts[key]["Q"] += 1
        elif candidate.get("filter_outcome", {}).get("status") == "reject":
            counts[key]["R"] += 1
        else:
            counts[key]["U"] += 1
    rows = []
    pooled: dict[str, int] = dict(Q=0, R=0, U=0, N=0)
    for (symbol, scale), values in sorted(counts.items()):
        pooled = {name: pooled[name] + values[name] for name in pooled}
        resolved = values["Q"] + values["R"]
        eligible = resolved + values["U"]
        rows.append({
            "symbol": symbol, "scale": scale, **values,
            "eligible": eligible,
            "ratio_full": values["Q"] / eligible if eligible and values["U"] == 0 else None,
            "ratio_conditional": values["Q"] / resolved if resolved else None,
            "alert_metrics": "NOT_APPLICABLE",
        })
    for symbol in sorted({key[0] for key in counts}):
        values = {name: sum(c[name] for (asset, _), c in counts.items() if asset == symbol) for name in pooled}
        eligible = values["Q"] + values["R"] + values["U"]
        resolved = values["Q"] + values["R"]
        rows.append({
            "symbol": symbol, "scale": "pooled", **values,
            "eligible": eligible,
            "ratio_full": values["Q"] / eligible if eligible and values["U"] == 0 else None,
            "ratio_conditional": values["Q"] / resolved if resolved else None,
            "alert_metrics": "NOT_APPLICABLE",
        })
    return rows


def _copy_source_snapshot(out: Path) -> None:
    snapshot = out / "source_snapshot"
    for relative in (
        "scripts/research/t03_b0_scan.py",
        "scripts/research/t03_merge_and_score.py",
        "research/features/lppls_scan.py",
        "research/lppls/future_contract.py",
        "research/lppls/window_clusters.py",
        "research/lppls/oscillations.py",
        "research/eval/top_time/contracts.py",
        "research/eval/top_time/labels.py",
        "research/eval/top_time/t02.py",
    ):
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)


def _checksums(out: Path) -> None:
    lines = []
    for path in sorted(item for item in out.rglob("*") if item.is_file() and item.name != "checksums.sha256"):
        lines.append(f"{sha256_file(path)}  {path.relative_to(out).as_posix()}")
    (out / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge(args: argparse.Namespace) -> dict:
    prereg_bytes = PREREG_PATH.read_bytes()
    if hashlib.sha256(prereg_bytes).hexdigest() != PREREG_SHA256:
        raise ValueError("frozen preregistration SHA-256 mismatch")
    symbols = tuple(item for item in args.symbols.split(",") if item)
    if args.mode == "full" and symbols != SYMBOLS:
        raise ValueError("full mode requires the six frozen preregistration symbols in order")
    if args.mode == "pilot" and symbols != ("sh000300",):
        raise ValueError("pilot mode is restricted to sh000300")
    if not 1 <= args.shards <= 20:
        raise ValueError("shards must be in 1..20")
    manifests, attempts, candidates, windows, scans = load_shards(
        args.inputs,
        run_id=args.run_id,
        mode=args.mode,
        symbols=symbols,
        shard_count=args.shards,
    )
    _assert_scan_conservation(scans, windows)
    asof_count = len({(row["symbol"], row["asof"]) for row in scans})
    if args.mode == "full" and asof_count != 4236:
        raise ValueError(f"full mode planned {asof_count} symbol-asofs; expected 4236")
    planned_sessions = calendar()
    expected_asofs = {
        (symbol, date.strftime("%Y-%m-%d"))
        for symbol in symbols
        for date in planned_asofs(symbol, args.mode, planned_sessions)
    }
    actual_asofs = {(row["symbol"], row["asof"]) for row in scans}
    if actual_asofs != expected_asofs:
        raise ValueError(
            f"scan ledger differs from frozen as-of plan; "
            f"missing={sorted(expected_asofs - actual_asofs)[:5]}, "
            f"extra={sorted(actual_asofs - expected_asofs)[:5]}"
        )
    if len({(row["symbol"], row["asof"], row["n"]) for row in windows}) != len(windows):
        raise ValueError("duplicate symbol-asof-window result")

    out = args.out.resolve()
    if out.exists():
        raise FileExistsError(f"refusing to overwrite output directory: {out}")
    out.mkdir(parents=True, exist_ok=False)
    with JsonlGzWriter(out / "fit_attempts.jsonl.gz") as writer:
        for row in attempts:
            writer.write(row)
    with JsonlGzWriter(out / "candidate_fits.jsonl.gz") as writer:
        for row in candidates:
            writer.write(row)
    with JsonlGzWriter(out / "window_results.jsonl.gz") as writer:
        for row in windows:
            writer.write(row)
    with JsonlGzWriter(out / "scan_ledger.jsonl.gz") as writer:
        for row in sorted(scans, key=lambda item: (item["symbol"], item["asof"])):
            writer.write(row)

    books, session_strings = _label_books(symbols)
    label_rows, label_state_rows, unknown_rows = [], [], []
    for symbol, book in books.items():
        for event in book.events:
            label_rows.append({
                "symbol": symbol,
                "event_id": event.event_id,
                "scope": event.scale,
                "peak_session": event.peak_session,
                "peak_date": book.sessions[event.peak_session],
                "support_start": event.support_start,
                "support_end": event.support_end,
                "label_available_session": event.label_available_session,
                "label_version": event.label_version,
                "price": event.price,
                "family_id": event.family_id,
                "family_ambiguous": event.family_ambiguous,
            })
        unknown_rows.extend(unknown_label_rows(book))
        for scope, states in book.states.items():
            for session, state in enumerate(states):
                label_state_rows.append({
                    "symbol": symbol,
                    "scope": scope,
                    "session": session,
                    "date": book.sessions[session],
                    "label_state": getattr(state, "value", str(state)),
                    "label_version": book.metadata.get("label_version"),
                })
    _write_csv(out / "label_events.csv", label_rows)
    _write_csv(out / "label_states.csv", label_state_rows)
    _write_csv(out / "unknown_labels.csv", unknown_rows)

    predictions = _candidate_predictions(symbols, scans, candidates, windows, session_strings)
    with JsonlGzWriter(out / "arm_predictions.jsonl.gz") as writer:
        for row in predictions:
            writer.write(row)
    claim_rows, raw_claims = build_claims(predictions, books, session_strings)
    with JsonlGzWriter(out / "prediction_ledger.jsonl.gz") as writer:
        for row in claim_rows:
            writer.write(row)
    natural_rows, event_rows, attribution_rows, pending_rows = _arm_metric_rows(
        books, claim_rows, raw_claims, scans, session_strings, args.mode
    )
    _write_csv(out / "event_scores.csv", event_rows)
    _write_csv(out / "natural_budget_scores.csv", natural_rows)
    natural_by_key = {
        (row["symbol"], row["arm"], row["scope"]): row
        for row in natural_rows
    }
    data_subset_rows = []
    primary_comparisons = []
    if args.mode == "full":
        for symbol in symbols:
            for arm in ARM_NAMES:
                for scope in SCOPES:
                    subset = [
                        row for row in event_rows
                        if row["symbol"] == symbol and row["arm"] == arm
                        and row["scope"] == scope and row["data_evaluable"]
                    ]
                    denominator = len(subset)
                    natural = natural_by_key[(symbol, arm, scope)]
                    data_subset_rows.append({
                        "symbol": symbol,
                        "arm": arm,
                        "scope": scope,
                        "data_evaluable_E": denominator,
                        "S0": sum(row["S0"] for row in subset) / denominator if denominator else None,
                        "S5": sum(row["S5"] for row in subset) / denominator if denominator else None,
                        "S10": sum(row["S10"] for row in subset) / denominator if denominator else None,
                        "S21": sum(row["S21"] for row in subset) / denominator if denominator else None,
                        "StrictStageRecall5W10": natural["data_evaluable_strict_recall"],
                        "QualifiedStageRecall5": natural["data_evaluable_qualified_stage_recall"],
                        "no_formal_alert_rate": natural["data_evaluable_no_formal_alert_rate"],
                        "first_window_coverage": natural["data_evaluable_first_window_coverage"],
                        "zero_denominator_is_null": True,
                    })
    _write_csv(out / "data_evaluable_scores.csv", data_subset_rows)
    _write_csv(out / "first_alert_failure_attribution.csv", attribution_rows)
    _write_csv(out / "pending_claims.csv", pending_rows)
    d1 = _d1_rows(candidates, windows)
    _write_csv(out / "D1_t07a_ratios.csv", d1)

    paired_rows = []
    paired_event_rows = []
    paired_ledger = []
    if args.mode == "full":
        by_key = {(row["symbol"], row["asof"], row["run_arm"]): row for row in predictions}
        for symbol, asof in sorted({(row["symbol"], row["asof"]) for row in predictions}):
            book = books[symbol]
            published = next(row["asof_session"] for row in scans if row["symbol"] == symbol and row["asof"] == asof)
            action = action_session_after_close(session_strings, published)
            anchor = _event_by_anchor(book)
            for comparison in ("W1", "C1"):
                b0, variant = by_key[(symbol, asof, "B0")], by_key[(symbol, asof, comparison)]
                for scope in SCOPES:
                    record = {
                        "symbol": symbol, "asof": asof, "scope": scope,
                        "comparison": comparison, "action_session": action,
                        "joint_formal_opportunity": False,
                        "b0_interval_start": b0["interval_start"],
                        "b0_interval_end": b0["interval_end"],
                        "variant_interval_start": variant["interval_start"],
                        "variant_interval_end": variant["interval_end"],
                        "deployable": False,
                    }
                    if b0["interval_start"] is not None and variant["interval_start"] is not None:
                        gate_b0 = formal_interval_gate(action, b0["interval_start"], b0["interval_end"])
                        gate_variant = formal_interval_gate(
                            action, variant["interval_start"], variant["interval_end"]
                        )
                        record["joint_formal_opportunity"] = gate_b0["formal"] and gate_variant["formal"]
                        target_status, event, blocker = _next_target(book, anchor, scope, action, HORIZON)
                        record["target_status"] = target_status
                        record["target_event_id"] = event.event_id if event else None
                        record["unknown_blocker_session"] = blocker
                    paired_ledger.append(record)

        for comparison in ("W1", "C1"):
            for scope in SCOPES:
                joint = [
                    row for row in paired_ledger
                    if row["comparison"] == comparison and row["scope"] == scope
                    and row["joint_formal_opportunity"]
                ]
                first_by_event = {}
                for item in sorted(joint, key=lambda row: (row["symbol"], row["action_session"], row["asof"])):
                    if item.get("target_status") != "event":
                        continue
                    first_by_event.setdefault((item["symbol"], item["target_event_id"]), item)
                scores = []
                for (asset, event_id), item in first_by_event.items():
                    event = next(event for event in books[asset].events if event.event_id == event_id)
                    score = {
                        "symbol": asset,
                        "scope": scope,
                        "event_id": event_id,
                        "peak_date": books[asset].sessions[event.peak_session],
                        "comparison": f"{comparison}-B0",
                        "asof": item["asof"],
                    }
                    for arm, start_key, end_key in (
                        ("B0", "b0_interval_start", "b0_interval_end"),
                        (comparison, "variant_interval_start", "variant_interval_end"),
                    ):
                        start, end = item[start_key], item[end_key]
                        width = end - start + 1
                        hit = hit_k(event.peak_session, item["action_session"], start, end, 10)
                        random = random_placement_expectation(
                            item["action_session"], width, event.peak_session, 10
                        )
                        score[f"S10_{arm}"] = hit - random
                    score["S10_difference"] = score[f"S10_{comparison}"] - score["S10_B0"]
                    paired_event_rows.append(score)
                    scores.append(score)
                event_denominator = len({
                    (row["symbol"], row["event_id"])
                    for row in event_rows
                    if row["arm"] == "B0" and row["scope"] == scope
                })
                paired_rows.append({
                    "comparison": f"{comparison}-B0",
                    "scope": scope,
                    "joint_formal_asset_asofs": len(joint),
                    "resolved_event_targets": len(scores),
                    "pending_or_unknown": sum(row.get("target_status") == "pending" for row in joint),
                    "event_denominator": event_denominator,
                    "paired_S10_B0": sum(row["S10_B0"] for row in scores) / len(scores) if scores else None,
                    f"paired_S10_{comparison}": (
                        sum(row[f"S10_{comparison}"] for row in scores) / len(scores) if scores else None
                    ),
                    "paired_S10_difference": (
                        sum(row["S10_difference"] for row in scores) / len(scores) if scores else None
                    ),
                    "deployable": False,
                    "interpretation": "same asset/asof joint opportunity diagnostic; not deployable",
                })
    with JsonlGzWriter(out / "conditional_pairing_ledger.jsonl.gz") as writer:
        for row in paired_ledger:
            writer.write(row)
    _write_csv(out / "paired_budget_scores.csv", paired_rows)
    _write_csv(out / "paired_event_scores.csv", paired_event_rows)

    failure_rows = []
    for row in windows:
        if row["status"] != "fit_ok":
            failure_rows.append({
                "record_type": "window",
                "symbol": row["symbol"],
                "asof": row["asof"],
                "window": row.get("n"),
                "status": row["status"],
                "reason": row.get("reason") or row.get("error"),
            })
    for row in unknown_rows:
        failure_rows.append({
            "record_type": "label",
            "symbol": row["symbol"],
            "asof": None,
            "window": None,
            "status": row["label_state"],
            "reason": row.get("reason"),
            "scope": row["scope"],
            "session": row["session"],
            "date": row["date"],
        })
    _write_csv(out / "failure_and_pending_register.csv", failure_rows)

    frozen_files = {
        "baseline_manifest.json": T00_DIR / "baseline_manifest.json",
        "sample_consumption_register.json": T00_DIR / "sample_consumption_register.json",
        "preserved_legacy_sha256.json": T00_DIR / "preserved_legacy_sha256.json",
        "fit_contract_frozen.json": T01_CONTRACT_PATH,
        "scoring_contract_frozen.json": T02_CONTRACT_PATH,
        "preregistration.json": PREREG_PATH,
        "README.md": PREREG_PATH.with_name("README.md"),
    }
    for name, source in frozen_files.items():
        shutil.copyfile(source, out / name)
    (out / "shard_run_manifests.json").write_text(
        json.dumps(
            sorted(manifests, key=lambda item: (item["symbol"], item["shard"]["index"])),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    experiment = {
        "preregistration": json.loads(prereg_bytes),
        "preregistration_sha256": PREREG_SHA256,
        "run_id": args.run_id,
        "mode": args.mode,
        "symbols": list(symbols),
        "shards": args.shards,
        "source_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "merged_at_utc": datetime.now(UTC).isoformat(),
        "planned_symbol_asofs": asof_count,
        "window_rows": len(windows),
        "fit_attempt_rows": len(attempts),
        "evidence_scope": "development_diagnostic",
    }
    (out / "experiment_manifest.json").write_text(
        json.dumps(experiment, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    env = (
        f"Python: {platform.python_version()}\n"
        f"Mode: {args.mode}\nRun ID: {args.run_id}\n"
        f"Command: python scripts/research/t03_merge_and_score.py --inputs "
        f"{args.inputs} --out {out} --mode {args.mode} --run-id {args.run_id} "
        f"--symbols {args.symbols} --shards {args.shards}\n"
        "Source: full-close frozen qfq parquet; no network access.\n"
        "Pilot outputs are engineering/timing only; no effect comparison is read.\n"
    )
    (out / "environment_and_commands.txt").write_text(env, encoding="utf-8")
    _copy_source_snapshot(out)

    if args.mode == "full":
        comparisons = []
        per_event = {
            (row["symbol"], row["arm"], row["scope"], row["event_id"]): row
            for row in event_rows
        }
        for variant in ("W1", "C1"):
            baseline = [
                row for row in event_rows
                if row["arm"] == "B0" and row["scope"] == "stage"
            ]
            values, years = [], []
            for base in baseline:
                comp = per_event.get((base["symbol"], variant, "stage", base["event_id"]))
                if comp is not None:
                    values.append(comp["S10"] - base["S10"])
                    years.append(int(base["peak_date"][:4]))
            low, high = year_block_bootstrap(years, values, confidence=0.975)
            mean_delta = sum(values) / len(values) if values else None
            costs_ok = True
            b0_costs = [
                row for row in natural_rows
                if row["arm"] == "B0" and row["scope"] == "stage"
            ]
            variant_costs = [
                row for row in natural_rows
                if row["arm"] == variant and row["scope"] == "stage"
            ]
            b0_years = sum(row.get("asset_years") or 0.0 for row in b0_costs)
            variant_years = sum(row.get("asset_years") or 0.0 for row in variant_costs)
            b0_rate = (
                sum(row.get("claim_notices") or 0 for row in b0_costs) / b0_years
                if b0_years else None
            )
            variant_rate = (
                sum(row.get("claim_notices") or 0 for row in variant_costs) / variant_years
                if variant_years else None
            )
            b0_occupied = sum(row.get("alert_occupied_sessions") or 0 for row in b0_costs)
            variant_occupied = sum(row.get("alert_occupied_sessions") or 0 for row in variant_costs)
            if b0_rate is not None and variant_rate is not None:
                costs_ok &= variant_rate <= 1.25 * b0_rate
            costs_ok &= variant_occupied <= 1.25 * b0_occupied
            if mean_delta is None:
                outcome = "INSUFFICIENT_EVIDENCE"
            elif mean_delta >= 0.05 and low is not None and low > 0 and costs_ok:
                outcome = "IMPROVED_DEV_ONLY"
            elif high is not None and high < 0:
                outcome = "REGRESSION"
            elif len(values) < 30 or (low is not None and high is not None and high - low > 0.20):
                outcome = "INSUFFICIENT_EVIDENCE"
            else:
                outcome = "NO_CLEAR_GAIN"
            comparisons.append({
                "comparison": f"S10({variant}) - S10(B0)",
                "events": len(values),
                "mean_delta": mean_delta,
                "ci_97_5_low": low,
                "ci_97_5_high": high,
                "cost_within_tolerance": costs_ok,
                "outcome": outcome,
            })
        for arm in ARM_NAMES:
            values = [
                row["S10"] for row in event_rows
                if row["arm"] == arm and row["scope"] == "stage"
            ]
            years = [
                int(row["peak_date"][:4]) for row in event_rows
                if row["arm"] == arm and row["scope"] == "stage"
            ]
            low, high = year_block_bootstrap(years, values, confidence=0.95)
            comparisons.append({
                "comparison": f"S10({arm}) vs 0",
                "events": len(values),
                "mean_delta": sum(values) / len(values) if values else None,
                "ci_95_low": low,
                "ci_95_high": high,
                "cost_within_tolerance": None,
                "outcome": "DESCRIPTIVE_DEVELOPMENT_DIAGNOSTIC",
            })
        primary_comparisons = comparisons
        _write_csv(out / "primary_comparisons.csv", primary_comparisons)

    report = [
        "# T03 B0 / W1 / C1 研究报告",
        "",
        "- evidence_scope: `development_diagnostic`",
        f"- run_id: `{args.run_id}`; mode: `{args.mode}`; planned symbol-asofs: **{asof_count}**",
        f"- preregistration SHA-256: `{PREREG_SHA256}`（运行时校验；未编辑）",
        "- 样本均为已消费开发数据，不是留出样本或独立确认。",
        "- G1 = `DEFERRED_NOT_PREREGISTERED`；本次不得据此补登记或调阈值。",
        "- 旧 PR #50 的 m∈[0.1,0.9]、ω∈[6,13]、ahead≤90 合格框**未使用**；B0/W1/C1 均注入 T01 的 `g_fco_standard` 过滤结果。",
        "- W1 只取 B0 已拟合窗口中的 `selected_windows('thin')` 28 个窗口；没有二次拟合。",
        "- 主 S10 遵守冻结预注册：按 T02 关联的 episode 首条 claim（任意宽度/提前量）计分，不按区间挑事件；正式提醒指标另列。",
        "- 数据/运行失败仍留在端到端 E 中，主 S10 对这些事件记 hit=0、r=0；另列 data-evaluable 子集与未知标签。",
        "- 历史重放使用模拟 17:00 Asia/Shanghai 可用时刻及下一交易日 action；真实 PIT vintage/送达证据未建立。",
        "- D1 Q/R/U/N 是资格率诊断；alert metrics = NOT_APPLICABLE。",
    ]
    if args.mode == "pilot":
        elapsed = sum(float(item.get("elapsed_seconds") or 0.0) for item in manifests)
        attempts_per_second = len(attempts) / elapsed if elapsed > 0 else None
        report.extend([
            "",
            "Pilot 仅用于工程与耗时检查；未读取效果比较。",
            f"- fit attempts: {len(attempts)}; aggregate shard wall time: {elapsed:.3f}s; attempts/s: {attempts_per_second}",
        ])
    else:
        report.extend(["", "## 主比较", "", "详见 `primary_comparisons.csv`、`natural_budget_scores.csv` 与 `paired_budget_scores.csv`。"])
        report.extend(["", "| Arm | Stage E | Mean S10 |", "|---|---:|---:|"])
        for arm in ARM_NAMES:
            values = [
                row["S10"] for row in event_rows
                if row["arm"] == arm and row["scope"] == "stage"
            ]
            report.append(
                f"| {arm} | {len(values)} | "
                f"{sum(values) / len(values):.6f} |" if values else f"| {arm} | 0 | null |"
            )
        report.extend(["", "| Comparison | Events | Mean Δ | 97.5% CI | Outcome |", "|---|---:|---:|---:|---|"])
        for comparison in primary_comparisons[:2]:
            low, high = comparison["ci_97_5_low"], comparison["ci_97_5_high"]
            interval = f"[{low:.6f}, {high:.6f}]" if low is not None and high is not None else "null"
            delta = comparison["mean_delta"]
            report.append(
                f"| {comparison['comparison']} | {comparison['events']} | "
                f"{delta:.6f} | {interval} | {comparison['outcome']} |"
                if delta is not None
                else f"| {comparison['comparison']} | {comparison['events']} | null | {interval} | {comparison['outcome']} |"
            )
    (out / "RESEARCH_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    _checksums(out)
    return {"output": str(out), "planned_symbol_asofs": asof_count, "window_rows": len(windows)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=("pilot", "full"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--shards", type=int, required=True)
    args = parser.parse_args()
    result = merge(args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
