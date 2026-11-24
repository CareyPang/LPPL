"""Bounded, local-only replay of an explicitly supplied frozen V2588 kernel.

The verified archive supplies three mathematical functions, not an executable
pipeline. Only those AST definitions are compiled. No original archive is
modified; no network requests, deployment, or production-result rewrites occur.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import itertools
import json
import math
import os
import shutil
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np
import pandas as pd
import scipy
from scipy.optimize import differential_evolution, minimize

from ..lppls.spec import (
    LONG_B_MAX_EXCLUSIVE,
    LONG_CONDITION_MAX,
    LONG_CYCLE_RULES,
    LONG_DAMPING_MIN,
    LONG_FAMILIES,
    LONG_FAMILY_SPAN_MAX_SESSIONS,
    LONG_FAMILY_SPLIT,
    LONG_FIT_ORDER,
    LONG_INTERIOR_STATUS,
    LONG_M_BOUNDS,
    LONG_OMEGA_BOUNDS,
    LONG_R2_MIN,
    LONG_RANK_MIN,
    LONG_SEED_GAP_MAX_SESSIONS,
    LONG_SEEDS,
    LONG_TC_AHEAD,
    LONG_WINDOWS,
    SPEC_VERSION,
    long_cycle_threshold,
    long_fit_bounds,
    long_rule_definition,
    long_seed_base_pass,
)
from .global_terminal import atomic_json, clean

WINDOWS = LONG_WINDOWS
SEEDS = LONG_SEEDS
ASSETS = ("US_IXIC", "US_NDX")
ASOF = "2026-11-20"
HISTORY = ("2026-11-11", "2026-11-16", "2026-11-19")
VERSION = "v2588_future_only_six_windows_v1"
DE = {"strategy": "best1bin", "popsize": 25, "maxiter": 1500, "tol": 1e-8,
      "atol": 0.0, "mutation": [0.5, 1.0], "recombination": 0.7,
      "workers": 1, "updating": "deferred", "polish": False}
LB = {"maxiter": 500, "maxfun": 20000, "ftol": 1e-15, "gtol": 1e-5, "maxls": 20}
LEGACY_CALENDAR = {"status": "weekday_estimate", "source": "Monday-Friday extension; holidays not removed",
            "note": "Current and replay dates share this mapping; raw trading-session distance is primary. Original archive calendar dates are retained separately."}
HOLIDAYS = ("2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26")
CALENDAR = {"status": "us_cash_exchange_reference", "verified": False,
            "nasdaq_2026_status": "VERIFIED_for_listed_holidays", "nasdaq_2027_status": "NOT_ESTABLISHED",
            "source": ["https://www.nasdaqtrader.com/Trader.aspx?id=Calendar", "https://www.nyse.com/markets/hours-calendars"],
            "holidays": list(HOLIDAYS), "note": "2026 Nasdaq holidays and 2027 NYSE reference; no fit changes. Raw ahead values remain primary; weekday estimates retained separately."}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def signature(value):
    return hashlib.sha256(json.dumps(clean(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def kernel(path, expected_hash):
    """Load only inspected numerical definitions from a hash-frozen archive."""
    if digest(path) != expected_hash:
        raise ValueError("Frozen mathematical source hash mismatch")
    module = ast.parse(Path(path).read_text(encoding="utf-8-sig"))
    names = {"Xmat", "lin", "fit_one"}
    definitions = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if {n.name for n in definitions} != names:
        raise ValueError("Required frozen functions absent")
    namespace = {"np": np, "math": math, "differential_evolution": differential_evolution,
                 "minimize": minimize, "DE_CONFIG": DE, "LBFGS_CONFIG": LB,
                 "long_fit_bounds": long_fit_bounds,
                 "long_cycle_threshold": long_cycle_threshold,
                 "long_seed_base_pass": long_seed_base_pass}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def math_ast_hash(path):
    module = ast.parse(Path(path).read_text(encoding="utf-8-sig"))
    selected = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name in {"Xmat", "lin", "fit_one"}]
    return hashlib.sha256(ast.dump(ast.Module(body=selected, type_ignores=[]), include_attributes=False).encode()).hexdigest()


def prefix(frame, asof, n):
    part = frame[frame.date <= asof].tail(n)
    if len(part) != n or part.date.iloc[-1] != asof:
        raise ValueError(f"Exact input unavailable: {asof}/{n}")
    return part


def input_identity(frame):
    return signature({"dates": frame.date.tolist(), "close": frame.close.tolist()})


def date_for(asof, ahead):
    return str(np.busday_offset(np.datetime64(asof), int(round(float(ahead))), roll="forward", holidays=HOLIDAYS))


def weekday_date(asof, ahead):
    return str(np.busday_offset(np.datetime64(asof), int(round(float(ahead))), roll="forward"))


def fit_job(task):
    started = time.perf_counter()
    result = {k: task[k] for k in ("symbol", "asof", "n", "seed", "input_hash", "method_hash")}
    try:
        funcs = kernel(task["kernel_path"], task["kernel_sha256"])
        fit = funcs["fit_one"](np.log(np.asarray(task["close"], dtype=float)), task["seed"])
        result.update(status="complete", fit=clean(fit), origin="new_frozen_kernel_fit")
    except Exception as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
    result.update(seconds=time.perf_counter()-started, completed_at=datetime.now(UTC).isoformat())
    return clean(result)


def check_fit(fit, close, funcs):
    """Independent readback at archived parameters; not another optimizer run."""
    y = np.log(np.asarray(close, dtype=float))
    q = funcs["lin"](np.arange(len(y), dtype=float), y, *fit["x"])
    if not np.isclose(q["sse"], fit["sse"], rtol=1e-10, atol=1e-12):
        raise ValueError("Archived SSE does not reproduce on verified input")
    if not np.allclose(q["beta"], fit["beta"], rtol=1e-8, atol=1e-9):
        raise ValueError("Archived coefficients do not reproduce")
    if clean(fit["de_config"]) != DE or clean(fit["lbfgs_config"]) != LB:
        raise ValueError("Archived optimizer settings differ")
    if np.asarray(fit["de"].get("population", [])).shape != (75, 3):
        raise ValueError("Archived terminal population missing")
    residual = y-funcs["Xmat"](np.arange(len(y), dtype=float), *fit["x"]) @ np.asarray(fit["beta"])
    recent = {}
    for length in (60, 250):
        tail = residual[-length:]
        recent[f"last_{length}"] = {"observations": len(tail), "rmse_log": float(np.sqrt(np.mean(tail**2))),
                                   "mean_residual_log": float(np.mean(tail)), "last_residual_log": float(tail[-1]),
                                   "definition": "log(observed close)-log(fitted price); diagnostic only, no new gate"}
    return {"sse_absolute_error": abs(q["sse"]-fit["sse"]), "terminal_population": [75, 3],
            "recent_fit": recent}


def seed_summary(record):
    row = {k: record.get(k) for k in ("seed", "status", "seconds", "origin", "error", "input_hash")}
    if record.get("status") != "complete":
        return row
    fit = record["fit"]
    tc, m, omega = fit["x"]
    ahead = tc-(record["n"]-1)
    base = long_seed_base_pass(
        fit["optimizer_success"], m, omega, fit["beta"][1], fit["damping"],
        fit["r2"], fit["rank"], fit["condition"]
    )
    passes = {
        rule: bool(base and fit["nosc"] >= long_cycle_threshold(rule))
        for rule, _ in LONG_CYCLE_RULES
    }
    failed = []
    for name, ok in (
        ("optimizer_not_converged", fit["optimizer_success"]),
        ("m_gate", LONG_M_BOUNDS[0] < m < LONG_M_BOUNDS[1]),
        ("omega_gate", LONG_OMEGA_BOUNDS[0] < omega < LONG_OMEGA_BOUNDS[1]),
        ("top_sign", fit["beta"][1] < LONG_B_MAX_EXCLUSIVE),
        ("damping_below_1", fit["damping"] >= LONG_DAMPING_MIN),
        ("r2_below_0_9", fit["r2"] >= LONG_R2_MIN),
        ("rank_or_condition", fit["rank"] >= LONG_RANK_MIN and fit["condition"] <= LONG_CONDITION_MAX),
        ("parameter_boundary", fit["boundary_status"] == LONG_INTERIOR_STATUS),
    ):
        if not ok:
            failed.append(name)
    row.update(tc_ahead=ahead, tc_date=date_for(record["asof"], ahead), m=m, omega=omega,
               r2=fit["r2"], damping=fit["damping"], full_cycles=fit["nosc"], sse=fit["sse"],
               optimizer_success=fit["optimizer_success"], boundary_status=fit["boundary_status"],
               passes=passes, failed_gates=failed, original_tc_date=record.get("original_tc_date"),
               recent_fit=record.get("independent_readback", record.get("reuse_qc", {})).get("recent_fit"))
    row["weekday_estimate_date"] = weekday_date(record["asof"], ahead)
    return row


def summarize_windows(records, asof):
    windows = []
    for n in WINDOWS:
        seeds = [seed_summary(records.get((asof, n, s), {"seed": s, "status": "pending"})) for s in SEEDS]
        done = [s for s in seeds if s["status"] == "complete"]
        ahead = [s["tc_ahead"] for s in done]
        gap = max(ahead)-min(ahead) if len(done) == 2 else None
        eligible = {
            rule: bool(
                len(done) == len(SEEDS)
                and gap <= LONG_SEED_GAP_MAX_SESSIONS
                and all(s["passes"][rule] and s["boundary_status"] == LONG_INTERIOR_STATUS for s in done)
            )
            for rule, _ in LONG_CYCLE_RULES
        }
        reasons = {}
        for rule in eligible:
            reasons[rule] = (["incomplete_seed_pair"] if len(done) != len(SEEDS) else [])
            if gap is not None and gap > LONG_SEED_GAP_MAX_SESSIONS:
                reasons[rule].append("seed_tc_disagreement_gt_2_sessions")
            if any(s["boundary_status"] != LONG_INTERIOR_STATUS for s in done):
                reasons[rule].append("parameter_boundary")
            if any(not s["passes"][rule] for s in done):
                reasons[rule].append("seed_quality_gate_failed")
        # An average of incompatible optimizer modes is not a candidate date.
        point = float(np.mean(ahead)) if any(eligible.values()) else None
        windows.append({"n": n, "family": LONG_FAMILIES[0] if n < LONG_FAMILY_SPLIT else LONG_FAMILIES[1], "seeds": seeds,
                        "seed_gap_days": gap, "seed_gap_unit": "trading_sessions",
                        "seed_date_range": [date_for(asof, min(ahead)), date_for(asof, max(ahead))] if ahead else None,
                        "seed_ahead_range": [min(ahead), max(ahead)] if ahead else None,
                        "eligible": eligible, "rejection_reasons": reasons,
                        "point_ahead": point, "point_date": date_for(asof, point) if point is not None else None,
                        "weekday_estimate_point_date": weekday_date(asof, point) if point is not None else None})
    return windows


def summarize_rules(windows):
    output = {}
    for rule, _ in LONG_CYCLE_RULES:
        families = []
        qualified = [w for w in windows if w["eligible"][rule]]
        for family in LONG_FAMILIES:
            members = [w for w in qualified if w["family"] == family]
            dates = sorted(w["point_date"] for w in members)
            ahead = [w["point_ahead"] for w in members]
            families.append({"family": family, "qualified_windows": [w["n"] for w in members],
                             "dates": dates, "member_date_range": [dates[0], dates[-1]] if dates else None,
                             "tested_windows": [w["n"] for w in windows if w["family"] == family],
                             "member_span_trading_days": max(ahead)-min(ahead) if ahead else None,
                             "neighbour_agreement_within_5_days": len(ahead) >= 2 and max(ahead)-min(ahead) <= LONG_FAMILY_SPAN_MAX_SESSIONS,
                             "note": "Adjacent lengths count as one window family; member dates are not probabilities or confidence bounds."})
        # Maximal cross-family point groups; no single-link chains or duplicate subsets.
        groups = []
        for length in range(2, len(qualified)+1):
            for members in itertools.combinations(qualified, length):
                ahead = [w["point_ahead"] for w in members]
                if len({w["family"] for w in members}) == 2 and max(ahead)-min(ahead) <= LONG_FAMILY_SPAN_MAX_SESSIONS:
                    ids = {w["n"] for w in members}
                    groups = [g for g in groups if not set(g["members"]) < ids]
                    dates = sorted(w["point_date"] for w in members)
                    groups.append({"start": dates[0], "end": dates[-1], "members": sorted(ids),
                                   "families": 2, "span_trading_days": max(ahead)-min(ahead)})
        output[rule] = {"definition": long_rule_definition(rule),
                        "families": families, "cross_family_clusters": groups}
    return output


def snapshot(symbol, asof, records, manifest):
    windows = summarize_windows(records, asof)
    statuses = [s["status"] for w in windows for s in w["seeds"]]
    expected = len(WINDOWS) * len(SEEDS)
    counts = {"expected": expected, "completed": statuses.count("complete"), "failed": statuses.count("failed"),
              "pending": statuses.count("pending"), "not_available": statuses.count("not_available")}
    return {"schema_version": "long_horizon_v1", "symbol": symbol, "asof": asof,
            "status": "complete" if counts["completed"] == expected else "not_available" if counts["not_available"] else "incomplete" if counts["failed"] else "running",
            "model_version": VERSION, "method_hash": manifest["method_hash"], "counts": counts,
            "source": {"label": "Yahoo daily close, frozen reconstruction; not contemporaneously published forecast",
                       "data_version": manifest["inputs"][symbol].get("data_version"),
                       "input_hash": manifest["inputs"][symbol]["input_hash"]},
            "first_visible_at": None, "windows": windows, "rules": summarize_rules(windows),
            "calendar": CALENDAR, "method": manifest["method"],
            "limits": ["Selected retrospective research, not out-of-sample accuracy measurement.",
                       "Seed agreement measures numerical stability, not probability.",
                       "No fixed-tc profile, bootstrap or price forecast was run.",
                       "One adjacent-window family is one scale, even if several lengths pass."]}


def publish_summary(root, records, manifest, running=True):
    assets = {}
    for symbol in ASSETS:
        current = snapshot(symbol, ASOF, records[symbol], manifest)
        history = [snapshot(symbol, asof, records[symbol], manifest) for asof in HISTORY]
        current["history"] = history
        current["stability"] = {"history": history, "note": "Frozen historic input replay; no first-publication claim. Compare raw ahead and consistently mapped dates."}
        assets[symbol] = current
    counts = {key: sum(a["counts"][key] for a in assets.values()) for key in ("expected", "completed", "failed", "pending")}
    expected = len(ASSETS) * len(WINDOWS) * len(SEEDS)
    summary = {"schema_version": "long_horizon_v1", "generated_at": datetime.now(UTC).isoformat(),
               "counts": counts, "assets": assets, "status": "complete" if counts["completed"] == expected else "running" if running else "incomplete",
               "historical_reuse": manifest.get("historical_reuse", [])}
    summary["report_version"] = signature({k: v for k, v in summary.items() if k != "generated_at"})
    if not running:
        archive = root/"exports"/f"{summary['report_version']}.json"
        archive.parent.mkdir(exist_ok=True)
        if not archive.exists():
            atomic_json(archive, clean(summary))
    atomic_json(root/"summary.json", clean(summary))
    return summary


def load_inputs(global_root):
    frames, metadata = {}, {}
    for symbol in ASSETS:
        path = global_root/f"{symbol}_latest.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("symbol") != symbol or record.get("asof") != ASOF:
            raise ValueError(f"Unexpected source identity/asof: {symbol}")
        history = record["price_history"]
        frame = pd.DataFrame({"date": history["dates"], "close": history["close"]})
        if frame.date.duplicated().any() or frame.date.tolist() != sorted(frame.date) or not np.isfinite(frame.close).all() or (frame.close <= 0).any():
            raise ValueError("Invalid source close sequence")
        frames[symbol] = frame
        metadata[symbol] = {"path": str(path), "sha256": digest(path), "input_hash": input_identity(frame),
                            "first_date": frame.date.iloc[0], "last_date": frame.date.iloc[-1], "rows": len(frame),
                            "source_meta": record.get("source_meta"), "data_version": record.get("data_version")}
    return frames, metadata


def reuse_history(legacy_root, frames, funcs, manifest):
    """Read only the 72 requested historical seed records, verifying each suffix."""
    records = {s: {} for s in ASSETS}
    prior_root = legacy_root.parent/"V2588_V5_1_IXIC_NDX_20261111_backtest_recovered_20261112"
    sources = {"recent": legacy_root/"fit/fits.sqlite", "prior": prior_root/"v2588_checkpoint.sqlite"}
    manifest["historical_reuse"] = []
    recent_dates = pd.read_csv(legacy_root/"fit/fit_summary.csv")
    original_dates = {(str(r.asof), str(r.asset), int(r.window), int(r.seed)): str(r.tc_calendar)
                      for r in recent_dates.itertuples()}
    for symbol in ASSETS:
        asset = symbol.removeprefix("US_")
        for asof in HISTORY:
            source = sources["prior" if asof == "2026-11-11" else "recent"]
            code = prior_root/"code/v2588_lib.py" if asof == "2026-11-11" else legacy_root/"fit/code/legacy_lib.py"
            audit = {"symbol": symbol, "asof": asof, "database": str(source), "code_sha256": digest(code),
                     "math_ast_hash": math_ast_hash(code), "reused": 0, "errors": []}
            if audit["math_ast_hash"] != manifest["method"]["math_ast_hash"]:
                audit["errors"].append("Historical mathematical function AST differs; not reused")
                manifest["historical_reuse"].append(audit)
                continue
            original_input = (prior_root/"inputs" if asof == "2026-11-11" else legacy_root/"fit/inputs")/f"{asset.lower()}_daily.csv"
            old = pd.read_csv(original_input)
            audit["input_file"] = str(original_input)
            audit["input_file_sha256"] = digest(original_input)
            with sqlite3.connect(source.as_uri()+"?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                for n, seed in itertools.product(WINDOWS, SEEDS):
                    try:
                        part = prefix(frames[symbol], asof, n)
                        old_part = prefix(old, asof, n)
                        if part.date.tolist() != old_part.date.tolist() or not np.array_equal(part.close.to_numpy(), old_part.close.to_numpy()):
                            raise ValueError("Historical input suffix mismatch")
                        original_date = None
                        if asof == "2026-11-11":
                            found = db.execute("SELECT fit_json,tc_calendar FROM fits WHERE asof_date=? AND asset=? AND direction='TOP' AND window=? AND seed=? AND stage='key_asof' AND status='COMPLETED'", (asof, asset, n, seed)).fetchone()
                            if found is None:
                                raise ValueError("Requested prior record missing")
                            fit = json.loads(found["fit_json"])
                            original_date = found["tc_calendar"]
                        else:
                            found = db.execute("SELECT result,status FROM jobs WHERE id=?", (f"fit|{asof}|{asset}|{n}|{seed}|0",)).fetchone()
                            if found is None or found["status"] != "completed":
                                raise ValueError("Requested recent record missing")
                            fit = json.loads(found["result"])
                            original_date = original_dates.get((asof, asset, n, seed))
                        qc = check_fit(fit, part.close, funcs)
                        records[symbol][(asof, n, seed)] = {"symbol": symbol, "asof": asof, "n": n, "seed": seed,
                            "status": "complete", "fit": fit, "input_hash": input_identity(part), "method_hash": manifest["method_hash"],
                            "origin": "audited_historical_reuse", "original_tc_date": original_date, "reuse_qc": qc,
                            "seconds": fit.get("elapsed_seconds"), "source_database": str(source)}
                        audit["reused"] += 1
                    except Exception as error:
                        message = f"{type(error).__name__}: {error}"
                        audit["errors"].append(f"{n}/{seed}: {message}")
                        records[symbol][(asof, n, seed)] = {"seed": seed, "status": "not_available", "error": message}
            manifest["historical_reuse"].append(audit)
    for symbol, asof, n, seed in itertools.product(ASSETS, HISTORY, WINDOWS, SEEDS):
        records[symbol].setdefault((asof, n, seed), {"seed": seed, "status": "not_available",
                                                  "error": "Historical archive could not be verified; see reuse audit"})
    return records


def run(args):
    root, legacy, global_root = Path(args.root).resolve(), Path(args.legacy_root).resolve(), Path(args.global_root).resolve()
    repo = Path(__file__).resolve().parents[2]
    if root == repo or repo in root.parents:
        raise ValueError("Research output must be outside the Git checkout")
    root.mkdir(parents=True, exist_ok=True)
    (root/"fits").mkdir(exist_ok=True)
    (root/"inputs").mkdir(exist_ok=True)
    plan = json.loads((legacy/"fit/plan.json").read_text(encoding="utf-8"))
    original_code = legacy/"fit/code/legacy_lib.py"
    expected = plan["code"]["legacy_lib.py"]
    if digest(original_code) != expected:
        raise ValueError("Archive mathematical code differs from frozen plan")
    frozen = root/"kernel.py"
    if not frozen.exists():
        shutil.copyfile(original_code, frozen)
    funcs = kernel(frozen, expected)
    frames, inputs = load_inputs(global_root)
    method = {"model_version": VERSION, "lppls_spec": SPEC_VERSION,
              "math_ast_hash": math_ast_hash(frozen), "kernel_sha256": expected,
              "de": DE, "lbfgsb": LB, "numpy": np.__version__, "scipy": scipy.__version__, "seeds": list(SEEDS),
              "tc_ahead": list(LONG_TC_AHEAD), "m_bounds": list(LONG_M_BOUNDS),
              "omega_bounds": list(LONG_OMEGA_BOUNDS),
              # Kept as initial provenance so a display-calendar correction cannot invalidate 24 frozen fits.
              "windows": list(WINDOWS), "calendar": LEGACY_CALENDAR, "new_asof": ASOF, "historical_asofs": list(HISTORY)}
    if np.__version__ != plan["numpy"] or scipy.__version__ != plan["scipy"]:
        raise ValueError("Use the archived numpy/scipy versions for this comparison")
    manifest = {"schema_version": "long_horizon_protocol_v1", "registered_at": datetime.now(UTC).isoformat(),
                "method": method, "method_hash": signature(method), "inputs": inputs,
                "expected_current": len(ASSETS) * len(WINDOWS) * len(SEEDS),
                "expected_historical_reuse": len(ASSETS) * len(HISTORY) * len(WINDOWS) * len(SEEDS),
                "export_calendar": CALENDAR,
                "export_code_sha256": digest(Path(__file__)),
                "boundary": "Local research only; original 27-window and archived results are untouched"}
    manifest_path = root/"manifest.json"
    if manifest_path.exists():
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        if prior["method_hash"] != manifest["method_hash"] or any(prior["inputs"][s]["sha256"] != inputs[s]["sha256"] or prior["inputs"][s]["input_hash"] != inputs[s]["input_hash"] for s in ASSETS):
            raise ValueError("Frozen protocol/input changed; use a new output directory")
        manifest["registered_at"] = prior["registered_at"]
    atomic_json(manifest_path, manifest)
    for symbol, frame in frames.items():
        path = root/"inputs"/f"{symbol}.json"
        value = {"symbol": symbol, "asof": ASOF, "date": frame.date.tolist(), "close": frame.close.tolist()}
        if path.exists() and json.loads(path.read_text(encoding="utf-8")) != value:
            raise ValueError("Immutable input copy mismatch")
        if not path.exists():
            atomic_json(path, value)
    records = reuse_history(legacy, frames, funcs, manifest)
    atomic_json(manifest_path, manifest)
    jobs = []
    # Core first, then neighbours; ordering is frozen before current fits.
    for n, symbol, seed in itertools.product(LONG_FIT_ORDER, ASSETS, SEEDS):
        part = prefix(frames[symbol], ASOF, n)
        task = {"symbol": symbol, "asof": ASOF, "n": n, "seed": seed, "input_hash": input_identity(part),
                "method_hash": manifest["method_hash"], "kernel_path": str(frozen), "kernel_sha256": expected,
                "close": part.close.tolist()}
        key = signature({k: task[k] for k in ("symbol", "asof", "n", "seed", "input_hash", "method_hash")})
        path = root/"fits"/f"{key}.json"
        if path.exists():
            cached = json.loads(path.read_text(encoding="utf-8"))
            if any(cached.get(k) != task[k] for k in ("symbol", "asof", "n", "seed", "input_hash", "method_hash")):
                raise ValueError("Cached fit identity mismatch")
            if cached["status"] == "complete":
                cached["independent_readback"] = check_fit(cached["fit"], part.close, funcs)
                records[symbol][(ASOF, n, seed)] = cached
                continue
        jobs.append((task, path))
    publish_summary(root, records, manifest)
    print(json.dumps({"protocol": str(manifest_path), "new_pending": len(jobs), "reuse_counts": [a["reused"] for a in manifest["historical_reuse"]]}), flush=True)
    if args.export_only:
        return publish_summary(root, records, manifest, running=False)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fit_job, task): (task, path) for task, path in jobs}
        for future in as_completed(futures):
            task, path = futures[future]
            try:
                result = future.result()
                if result["status"] == "complete":
                    result["independent_readback"] = check_fit(result["fit"], task["close"], funcs)
            except Exception as error:
                result = {k: task[k] for k in ("symbol", "asof", "n", "seed", "input_hash", "method_hash")}
                result.update(status="failed", error=f"{type(error).__name__}: {error}")
            atomic_json(path, result)
            records[task["symbol"]][(ASOF, task["n"], task["seed"])] = result
            summary = publish_summary(root, records, manifest)
            print(json.dumps({"symbol": task["symbol"], "n": task["n"], "seed": task["seed"], "status": result["status"], "seconds": result.get("seconds"), "counts": summary["counts"]}), flush=True)
    return publish_summary(root, records, manifest, running=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--legacy-root", required=True)
    parser.add_argument("--global-root", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--export-only", action="store_true")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
