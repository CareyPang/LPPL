"""Bounded global LPPLS research samples; no publication and no A-share overlays.

Reuses the repository's fit_asof and cluster aggregation. Outputs are local,
versioned research reconstructions, never forward-published forecasts. No
bootstrap, 104-week replay, price targets or fabricated fallback data.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import inspect
import json
import os
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np
import pandas as pd

from ..data.global_terminal import ASSETS, fetch_snapshot
from .stock_jobs import atomic_json as _atomic_json

WINDOWS = (10, 14, 18, 21, 30, 42, 52, 63, 64, 84, 105, 126,
           127, 168, 210, 252, 253, 315, 378, 441, 504,
           525, 630, 756, 1008, 1260, 1500)
SCALES = {"2-4w": (10, 20), "1-3m": (21, 63), "3-6m": (64, 126),
          "6-12m": (127, 252), "12-24m": (253, 504), "2-6y": (505, 1500)}
MODEL_VERSION = "global_sparse27_v1_production_v2_box"
ROOT = Path(__file__).resolve().parents[2]


def atomic_json(path: Path, value: dict):
    """Windows readers can briefly deny rename; keep complete files and retry."""
    for attempt in range(7):
        try:
            return _atomic_json(path, value)
        except PermissionError:
            if attempt == 6:
                raise
            time.sleep(.05 * (attempt + 1))


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def method_identity() -> dict:
    import scipy
    paths = [ROOT / "research/pipeline/daily.py", ROOT / "research/features/lppls_scan.py",
             ROOT / "research/features/lppls_rules.py", ROOT / "research/lppls/core.py",
             ROOT / "research/optim/optimizers.py", ROOT / "research/lppls/scenarios.py"]
    hashes = {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        sha = None
    value = {"source_sha": sha, "math_hashes": hashes, "numpy": np.__version__, "scipy": scipy.__version__,
             "windows": list(WINDOWS), "box": "v2", "seed": 0, "bootstrap": 0, "q3": 0,
             "search_bounds": {"m": [.01, 2.0], "omega": [1, 50], "ahead_fraction": [-.2, .2]},
             "allow_inside": True}
    value["fit_wrapper_hash"] = hashlib.sha256(ast.dump(ast.parse(inspect.getsource(fit_job)), include_attributes=False).encode()).hexdigest()
    value["fit_environment"] = {"LPPLS_BOX": "v2", "LPPLS_Q3": "0", "LPPLS_G3": "0", "LPPLS_SIGN": "pos",
                                "LPPLS_ANCHOR": "end", "LPPLS_WINDOWS": "full", "ALLOW_INSIDE": True}
    # Git HEAD is provenance, not a mathematical dependency (frontend-only commits must not invalidate fits).
    value["hash"] = hashlib.sha256(json.dumps({k: v for k, v in value.items() if k != "source_sha"}, sort_keys=True).encode()).hexdigest()
    return value


def selected_asofs(frame: pd.DataFrame, offsets=(0, 5, 10)) -> list[pd.Timestamp]:
    dates = pd.DatetimeIndex(frame.date)
    if len(dates) <= max(offsets):
        raise ValueError("Insufficient trading days for registered replay offsets")
    return [pd.Timestamp(dates[-1 - offset]) for offset in offsets]


def fit_key(frame: pd.DataFrame, asof: pd.Timestamp, n: int, optimizer: str, method: dict) -> str:
    prefix = frame[frame.date <= asof].tail(n)
    if len(prefix) != n or prefix.date.iloc[-1] != asof:
        raise ValueError("Exact as-of and requested window must be present")
    content = prefix[["date", "close"]].to_csv(index=False, float_format="%.17g").encode()
    return hashlib.sha256(content + json.dumps({"n": n, "optimizer": optimizer, "method": method["hash"]}, sort_keys=True).encode()).hexdigest()


def fit_job(task: dict) -> dict:
    """Trace optimizer calls without changing their parameters or results."""
    os.environ["LPPLS_BOX"] = "v2"
    os.environ["LPPLS_Q3"] = "0"
    os.environ["LPPLS_G3"] = "0"
    os.environ["LPPLS_SIGN"] = "pos"
    os.environ["LPPLS_ANCHOR"] = "end"
    os.environ["LPPLS_WINDOWS"] = "full"
    from ..features import lppls_scan as scan
    from ..lppls import core
    from .daily import fit_asof
    if scan.BOX != "v2" or scan.Q3_K or scan.G3 or scan.SIGN != "pos" or scan.ANCHOR != "end":
        raise RuntimeError("Worker imported an incompatible fit configuration")
    core.ALLOW_INSIDE = True
    attempts, originals = [], {}
    for name in ("de_lbfgsb", "tcgrid_lm"):
        original = getattr(scan, name)
        originals[name] = original
        def traced(*args, _fn=original, _name=name, **kwargs):
            result = _fn(*args, **kwargs)
            attempts.append({"method": _name, "theta": result.theta.tolist(), "sse": result.sse,
                             "nfev": result.nfev, "seconds": result.seconds, "termination": result.message,
                             "model_parameters": int(kwargs.get("k", 4)), "seed": kwargs.get("seed", 0)})
            return result
        setattr(scan, name, traced)
    start = time.perf_counter()
    try:
        series = pd.Series(np.log(np.asarray(task["close"], dtype=float)), index=pd.to_datetime(task["dates"]))
        row = fit_asof(series, pd.Timestamp(task["asof"]), (task["n"],), opt=task["optimizer"]).iloc[0].to_dict()
        if not np.isfinite(row["sse"]):
            raise ValueError("Nonfinite fit SSE")
        return clean({"status": "complete", "asset_id": task["asset_id"], "asof": task["asof"],
                      "n": task["n"], "optimizer": task["optimizer"], "fit_input_hash": task["key"],
                      "row": row, "optimizer_calls": attempts, "seconds": time.perf_counter() - start,
                      "completed_at": datetime.now(UTC).isoformat(),
                      "attempt_scope": "optimizer calls including power fit; not every population member or TRF start"})
    except Exception as error:
        return clean({"status": "failed", "asset_id": task["asset_id"], "asof": task["asof"], "n": task["n"],
                      "fit_input_hash": task["key"], "error": f"{type(error).__name__}: {error}",
                      "optimizer_calls": attempts, "seconds": time.perf_counter() - start})
    finally:
        for name, original in originals.items():
            setattr(scan, name, original)


def derived_and_rules(rows: list[dict]):
    from ..features.lppls_rules import _derived, rules
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame.date)
    derived = _derived(frame)
    filters = rules(derived)
    # Same fitted candidates; separate research filter, not a future-only refit.
    filters["box_cycles_1_5"] = filters.box & (derived.ahead > 0) & (derived.n_osc >= 1.5)
    return derived, filters


def filter_diagnostics(derived, filters) -> dict:
    """Counts describe filter exclusions; overlapping failures are not additive."""
    gates = {"B_negative": derived.B < 0, "m_0_1_to_0_9": derived.m.between(.1, .9),
             "omega_6_to_13": derived.w.between(6, 13), "ahead_0_to_90": derived.ahead.between(0, 90)}
    cumulative = pd.Series(True, index=derived.index)
    sequential = {}
    for name, gate in gates.items():
        cumulative &= gate
        sequential[name] = int(cumulative.sum())
    return {"completed": len(derived), "standalone_pass": {k: int(v.sum()) for k, v in gates.items()},
            "sequential_pass": sequential, "box_qualified": int(filters.box.sum()),
            "cycles_1_5_qualified": int(filters.box_cycles_1_5.sum()),
            "tc_inside_sample": int((derived.ahead < 0).sum()), "ahead_over_90": int((derived.ahead > 90).sum()),
            "note": "单项失败可重叠；累计数按B、m、omega、ahead顺序，不表示各指标独立。"}


def aggregate(derived, filters, date, calendar, market, column="box") -> dict:
    from ..eval.export_contract import _scale_cluster_records, _to_cal
    from ..lppls.scenarios import scale_windows
    qualified = derived[filters[column]]
    clusters = _scale_cluster_records(qualified[["n", "ahead", "sse"]], calendar, date, market, SCALES)
    windows = scale_windows(qualified[["n", "ahead"]], SCALES)
    listed = [{"scale": row.scale, "q20_date": _to_cal(calendar, date, row.q20, market),
               "q80_date": _to_cal(calendar, date, row.q80, market), "n": int(row.n), "evidence": "research_candidate"}
              for row in windows.itertuples()]
    confidence, indicators = {}, {}
    for scale, (lo, hi) in SCALES.items():
        mask = derived.n.between(lo, hi)
        count = int(mask.sum())
        passed = int(filters.loc[mask, column].sum())
        fraction = passed / count if count else None
        confidence[scale] = fraction
        state = "not_computed" if not count else "signal" if clusters[scale] else "no_cluster" if passed else "no_qualified_fit"
        indicators[scale] = {"direction": "positive", "n_windows": count, "n_qualified_box": passed,
            "confidence": {column: fraction}, "signal_status": state,
            "display_only": scale == "2-4w", "evidence": "research_candidate"}
    return {"indicators": indicators, "scale_clusters": clusters, "scale_windows": listed,
            "lppls_confidence": {**confidence, "evidence": "research_candidate", "scale_evidence": {s: "research_candidate" for s in SCALES}},
            "signal_status": "signal" if any(v for s, v in clusters.items() if s != "2-4w") else "no_cluster" if len(qualified) else "no_qualified_fit",
            "drawdown_price": {"value": None, "evidence": "none"}}


def make_record(asset_id: str, frame: pd.DataFrame, metadata: dict, asof: pd.Timestamp,
                cells: list[dict], method: dict) -> dict:
    asset = ASSETS[asset_id]
    prefix = frame[frame.date <= asof].copy()
    if prefix.empty or prefix.date.iloc[-1] != asof:
        raise ValueError("Cannot publish an inexact replay date")
    expected = [n for n in WINDOWS if n <= len(prefix)]
    if {cell["n"] for cell in cells if cell["status"] == "complete"} != set(expected):
        raise ValueError("Do not aggregate an incomplete window plan")
    derived, filters = derived_and_rules([cell["row"] for cell in cells])
    calendar = pd.DatetimeIndex(prefix.date)
    top = aggregate(derived, filters, asof, calendar, asset["market"])
    top["indicators"]["rule_note"] = "v2 搜索后使用原生产 box；27个预登记稀疏窗口，非181窗完整扫描。box 不含振荡周期门槛。"
    top["scale_clusters_note"] = "复用现有分尺度聚类；share 是合格拟合数量占比，不是顶部概率；区间为20–80%分位。"
    top["window"] = {"start": None, "end": None, "evidence": "research_candidate", "rule": "按尺度查看独立聚类"}
    stock_meta = {"evidence": "research_candidate", "variant": "global_sparse27", "source": metadata["source"]}
    price = {"dates": [str(v.date()) for v in prefix.date], "source": metadata["source"],
             "adjustment": metadata["adjustment"], "volume_unit": metadata["volume_unit"],
             "note": "本次下载版本的历史重建；不是当时保存的原始行情。"}
    for column in ("open", "high", "low", "close", "volume"):
        values = prefix[column]
        if column in ("open", "high", "low"):
            values = values.where(np.isfinite(values) & (values > 0))
        price[column] = clean(values.tolist())
    ohlc = prefix[["open", "high", "low"]]
    invalid_fields = ~np.isfinite(ohlc) | (ohlc <= 0)
    missing_ohlc = invalid_fields.any(axis=1)
    price["ohlc_missing_dates"] = [str(value.date()) for value in prefix.loc[missing_ohlc, "date"]]
    price["ohlc_missing_count"] = int(missing_ohlc.sum())
    price["ohlc_invalid_fields"] = {str(prefix.loc[index, "date"].date()): [key for key in ("open", "high", "low") if invalid_fields.loc[index, key]]
                                     for index in prefix.index[missing_ohlc]}
    price["ohlc_sanitization"] = "nonpositive or nonfinite open/high/low exported as null; original source and model close unchanged"
    price["last_bar_kind"] = "close_only" if bool(missing_ohlc.iloc[-1]) else "ohlc"
    price["volume_missing_dates"] = [str(value.date()) for value in prefix.loc[prefix.volume.isna(), "date"]]
    if missing_ohlc.any():
        price["note"] += f"其中{int(missing_ohlc.sum())}日存在缺失或无效的开/高/低字段，保留收盘价，不补造K线。"
    fields = ["id", "ticker", "market", "kind", "currency", "timezone", "exchange", "fetched_at",
              "source", "url", "raw_sha256", "normalized_sha256", "adjustment", "volume_unit", "history_vintage",
              "normalizer_version", "metadata_file", "dropped_unclosed_bars", "provider_currency"]
    source_meta = {key: metadata.get(key) for key in fields}
    source_meta.update(asset_type=asset["kind"], source_asof=metadata["asof"], model_asof=str(asof.date()),
                       public_redistribution=metadata.get("public_redistribution", "NOT_ESTABLISHED"))
    return clean({"schema_version": "global_terminal_v1", "symbol": asset_id, "code": asset_id,
        "name": asset["name"], "asset_type": asset["kind"], "market": asset["market"],
        "currency": asset["currency"], "timezone": metadata["timezone"], "exchange": metadata["exchange"],
        "asof": str(asof.date()), "generated_at": datetime.now(UTC).isoformat(), "first_visible_at": None,
        "model_version": MODEL_VERSION, "fit_code_version": method["hash"], "source_sha": method["source_sha"],
        "data_version": metadata["normalized_sha256"], "source": metadata["source"], "source_meta": source_meta,
        "evidence": "research_candidate", "evidence_levels": {"research_candidate": "国际市场稀疏窗口研究样本"},
        "params": {**method, "optimizer": "de_lbfgsb" if asset_id == "US_MRVL" else "g3", "window_count": len(expected)},
        "future_calendar": {"market": asset["market"], "exchange": metadata["exchange"],
            "status": "weekday_estimate", "verified": False, "official_verification": "NOT_ESTABLISHED",
            "closures": [], "source": None, "holidays_through": None,
            "note": "未来日期按工作日外推，未核验本市场节假日；保留交易日提前量原值。"},
        "price_history": price, "top": top, "bottom": {}, "validation": [], "stock_meta": stock_meta,
        "replay_kind": "historical_reconstruction", "research": {
            "sample_scope": "current plus two registered earlier trading-day endpoints; no outcome scoring",
            "cycles_1_5": aggregate(derived, filters, asof, calendar, asset["market"], "box_cycles_1_5"),
            "cycles_1_5_rule": "production box AND ahead>0 AND full_cycles>=1.5; same fit pool, not future-only refit",
            "oscillation_formula": "omega/(2*pi)*log(abs(tc)/max(abs(tc-t2),1e-3))",
            "filter_diagnostics": filter_diagnostics(derived, filters),
            "fit_input_hashes": {str(cell["n"]): cell["fit_input_hash"] for cell in cells},
            "future_calendar_verified": False, "stage_top_score": None,
            "export_code_hash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        "status": "complete_sample", "fit_counts": {"expected": len(expected), "completed": len(cells), "failed": 0, "pending": 0}})


def history_frame(record: dict) -> dict:
    top = record["top"]
    windows = {scale: None for scale in SCALES}
    for window in top["scale_windows"]:
        windows[window["scale"]] = [window["q20_date"], window["q80_date"]]
    return {"asof": record["asof"], "close": record["price_history"]["close"][-1],
            "conf": {s: top["lppls_confidence"][s] for s in SCALES}, "w": windows,
            "clusters": top["scale_clusters"], "top": top, "evidence": "research_candidate",
            "stock_meta": record["stock_meta"], "model_version": record["model_version"],
            "data_version": record["data_version"], "first_visible_at": None,
            "fit_code_version": record["fit_code_version"], "record_version": record.get("record_version"),
            "archive_path": record.get("archive_path"),
            "research": record["research"], "params": record["params"],
            "future_calendar": record["future_calendar"], "source_meta": record["source_meta"],
            "snapshot_path": f"global/{record['symbol']}_{record['asof']}.json"}


def archive_record(output: Path, record: dict) -> dict:
    stable = {key: value for key, value in record.items() if key not in {"generated_at", "record_version", "archive_path"}}
    version = hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    relative = f"archive/{record['symbol']}/{record['asof']}/{version}.json"
    path = output / relative
    if path.exists():
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored_stable = {key: value for key, value in stored.items() if key not in {"generated_at", "record_version", "archive_path"}}
        stored_hash = hashlib.sha256(json.dumps(stored_stable, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if stored.get("record_version") != version or stored_hash != version:
            raise ValueError("Archived record identity mismatch")
        return stored
    stored = {**clean(record), "record_version": version, "archive_path": f"global/{relative}"}
    atomic_json(path, stored)
    return stored


def merge_history(existing: dict, record: dict) -> dict:
    """One selected frame per date; prior data/model/export versions remain explicit."""
    frame = history_frame(record)
    frames = {item["asof"]: item for item in existing.get("frames", [])}
    revisions = list(existing.get("revisions", []))
    previous = frames.get(record["asof"])
    if previous and previous.get("record_version") != frame["record_version"]:
        revisions.append(previous)
    frames[record["asof"]] = frame
    unique = {json.dumps(item, sort_keys=True): item for item in revisions}
    return {"schema_version": "global_terminal_history_v1", "symbol": record["symbol"], "name": record["name"],
            "asof": max(frames), "frames": [frames[date] for date in sorted(frames)], "revisions": list(unique.values()),
            "model_version": record["model_version"], "data_version": record["data_version"],
            "evidence": "research_candidate", "scale_evidence": {s: "research_candidate" for s in SCALES},
            "stock_meta": record["stock_meta"], "source": record["source"], "source_meta": record["source_meta"],
            "future_calendar": record["future_calendar"], "replay_kind": "historical_reconstruction",
            "note": "固定as-of研究重放，保留旧日期与旧版本；不是104周回测或预测效果检验。"}


def export_record(output: Path, record: dict, current: bool) -> dict:
    record = archive_record(output, record)
    atomic_json(output / f"{record['symbol']}_{record['asof']}.json", record)
    if current:
        atomic_json(output / f"{record['symbol']}_latest.json", record)
    history_path = output / f"{record['symbol']}_history.json"
    existing = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else {}
    history = merge_history(existing, record)
    atomic_json(history_path, history)
    return history


def checked_root(root: Path) -> Path:
    root = root.resolve()
    if root.is_relative_to(ROOT.resolve()):
        raise ValueError("Raw research output root must be outside the Git repository")
    return root


def reexport_cached(root: Path, manifest_path: Path) -> dict:
    """Read exact frozen source+fit hashes; no HTTP, optimizer or new cache key."""
    root = checked_root(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    method = manifest["method"]
    current = method_identity()
    ignored = {"hash", "source_sha"} if "fit_wrapper_hash" in method else {"hash"}
    expected_hash = hashlib.sha256(json.dumps({k: v for k, v in method.items() if k not in ignored}, sort_keys=True).encode()).hexdigest()
    if expected_hash != method["hash"]:
        raise ValueError("Frozen manifest method hash mismatch")
    for key in ("math_hashes", "numpy", "scipy", "windows", "box", "seed", "bootstrap", "q3", "search_bounds", "allow_inside"):
        if method[key] != current[key]:
            raise ValueError(f"Export-only mathematical dependency changed: {key}")
    if "fit_wrapper_hash" in method and method["fit_wrapper_hash"] != current["fit_wrapper_hash"]:
        raise ValueError("Export-only fit wrapper changed")
    legacy = "fit_wrapper_hash" not in method
    output = root / "global"
    output.mkdir(parents=True, exist_ok=True)
    audit = {"mode": "export_only", "no_network_or_fitting": True, "legacy_method_identity": legacy,
             "method_hash": method["hash"], "new_method_hash": current["hash"],
             "note": "Original cache identity retained; no silent migration to the current computation key.",
             "records": [], "errors": [], "generated_at": datetime.now(UTC).isoformat()}
    for entry in manifest["assets"]:
        asset_id = entry["id"]
        try:
            metadata = entry["source_meta"]
            if metadata.get("id") != asset_id or metadata.get("ticker") != ASSETS[asset_id]["ticker"]:
                raise ValueError("Frozen source asset identity mismatch")
            folder = root / "source" / asset_id
            for field, hash_field in (("raw_file", "raw_sha256"), ("normalized_file", "normalized_sha256")):
                path = (folder / metadata[field]).resolve()
                if not path.is_relative_to(folder.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != metadata[hash_field]:
                    raise ValueError("Frozen source path/checksum mismatch")
            frame = pd.read_parquet(folder / metadata["normalized_file"])
            dates = entry.get("completed_asofs", [])
            if not dates:
                raise ValueError("Frozen manifest has no completed dates")
            for day in dates:
                asof = pd.Timestamp(day)
                cells = []
                for n in WINDOWS:
                    key = fit_key(frame, asof, n, "de" if asset_id == "US_MRVL" else "g3", method)
                    path = root / "fits" / asset_id / day / f"{n}-{key}.json"
                    cell = json.loads(path.read_text(encoding="utf-8"))
                    if (cell.get("fit_input_hash") != key or cell.get("status") != "complete" or cell.get("n") != n
                        or cell.get("asset_id") != asset_id or cell.get("asof") != day):
                        raise ValueError("Frozen fit identity mismatch")
                    cells.append(cell)
                previous_path = output / f"{asset_id}_{day}.json"
                if previous_path.exists():
                    archive_record(output, json.loads(previous_path.read_text(encoding="utf-8")))
                record = make_record(asset_id, frame, metadata, asof, cells, method)
                if legacy:
                    record["research"]["fit_cache_identity_note"] = "Original completed run used its recorded legacy method hash without wrapper AST. Retained as-is, not silently migrated to the new computation key."
                history = export_record(output, record, day == max(dates))
                audit["records"].append({"asset": asset_id, "asof": day, "windows": len(cells), "history_frames": len(history["frames"])})
        except Exception as error:
            audit["errors"].append({"asset": asset_id, "error": f"{type(error).__name__}: {error}"})
    expected = sum(len(entry.get("completed_asofs", [])) for entry in manifest["assets"])
    audit["counts"] = {"exports_expected": expected, "exports_completed": len(audit["records"]), "exports_failed": len(audit["errors"])}
    audit["status"] = "complete" if expected and len(audit["records"]) == expected and not audit["errors"] else "partial"
    audit_path = root / "qa" / f"reexport-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    atomic_json(audit_path, audit)
    manifest["exported_at"] = audit["generated_at"]
    manifest["export_audit"] = str(audit_path.relative_to(root)).replace("\\", "/")
    manifest["counts"].update(audit["counts"])
    manifest["status"] = audit["status"] if manifest["status"] == "complete" else "partial"
    atomic_json(output / "catalog.json", manifest)
    atomic_json(root / "progress.json", manifest)
    print(json.dumps({"event": "reexport_finished", "status": audit["status"], "counts": audit["counts"]}), flush=True)
    return audit


def run(root: Path, asset_ids: list[str], workers: int, budget_seconds: float, refresh: bool = False) -> dict:
    root = checked_root(root)
    start = time.perf_counter()
    output = root / "global"
    output.mkdir(parents=True, exist_ok=True)
    method = method_identity()
    sources, failures, entries, errors = {}, {}, {}, []
    for asset_id in asset_ids:
        if time.perf_counter() - start >= budget_seconds:
            entries[asset_id] = {"id": asset_id, "symbol": asset_id, **ASSETS[asset_id], "status": "source_pending"}
            continue
        try:
            frame, metadata = fetch_snapshot(asset_id, root, refresh=refresh)
            selected_asofs(frame)  # Reject too-short sources here, not outside the source error boundary.
            sources[asset_id] = (frame, metadata)
            entries[asset_id] = {"id": asset_id, "symbol": asset_id, **ASSETS[asset_id], "status": "queued",
                "asof": metadata["asof"], "source": metadata["source"], "source_meta": metadata,
                "latest_path": f"global/{asset_id}_latest.json", "history_path": f"global/{asset_id}_history.json"}
            print(json.dumps({"event": "source", "id": asset_id, "asof": metadata["asof"], "rows": len(frame)}), flush=True)
        except Exception as error:
            failures[asset_id] = f"{type(error).__name__}: {error}"
            entries[asset_id] = {"id": asset_id, "symbol": asset_id, **ASSETS[asset_id], "status": "source_failed", "error": failures[asset_id]}
        time.sleep(.35)
    counters = {"expected": sum(sum(n <= len(f[f.date <= date]) for n in WINDOWS) for f, _ in sources.values() for date in selected_asofs(f)),
                "completed": 0, "failed": 0, "pending": 0, "source_failed": len(failures),
                "exports_expected": len(sources) * 3, "exports_completed": 0, "exports_failed": 0}
    def save_progress():
        counters["pending"] = counters["expected"] - counters["completed"] - counters["failed"]
        status = "complete" if (not counters["pending"] and not counters["failed"] and not failures
            and counters["exports_completed"] == counters["exports_expected"] and not counters["exports_failed"]
            and all(entry["status"] == "complete_sample" for entry in entries.values())) else "partial"
        snapshot = {"schema_version": "global_terminal_catalog_v1", "generated_at": datetime.now(UTC).isoformat(),
                    "status": status, "counts": counters.copy(), "elapsed_seconds": time.perf_counter() - start,
                    "method": method, "asof_offsets_trading_days": [0, 5, 10], "assets": list(entries.values()),
                    "errors": errors, "budget": {"seconds": budget_seconds,
                        "policy": "soft admission budget checked before each source fetch and asof batch; in-flight fetch/asof finishes"}}
        atomic_json(root / "progress.json", clean(snapshot))
        atomic_json(output / "catalog.json", clean(snapshot))
        return snapshot
    save_progress()
    stopped = False
    with ProcessPoolExecutor(max_workers=workers) as pool:
        # Current samples for all assets are completed before historical work.
        for offset in (0, 5, 10):
            for asset_id, (frame, metadata) in sources.items():
                if time.perf_counter() - start >= budget_seconds:
                    stopped = True
                    break
                asof = selected_asofs(frame, (offset,))[0]
                optimizer = "de" if asset_id == "US_MRVL" else "g3"
                cells, futures = [], {}
                for n in WINDOWS:
                    prefix = frame[frame.date <= asof].tail(n)
                    if len(prefix) < n:
                        continue
                    key = fit_key(frame, asof, n, optimizer, method)
                    path = root / "fits" / asset_id / str(asof.date()) / f"{n}-{key}.json"
                    if path.exists():
                        try:
                            cached = json.loads(path.read_text(encoding="utf-8"))
                            if (cached.get("fit_input_hash") != key or cached.get("status") != "complete"
                                or cached.get("n") != n or cached.get("asset_id") != asset_id or cached.get("asof") != str(asof.date())
                                or not np.isfinite(cached["row"]["sse"])):
                                raise ValueError("Cached fit incomplete or identity mismatch")
                            cells.append(cached)
                            counters["completed"] += 1
                        except (ValueError, KeyError, TypeError, OSError) as error:
                            counters["failed"] += 1
                            errors.append({"stage": "cache", "asset": asset_id, "asof": str(asof.date()), "n": n,
                                           "error": f"{type(error).__name__}: {error}"})
                        continue
                    task = {"asset_id": asset_id, "asof": str(asof.date()), "n": n, "optimizer": optimizer,
                            "key": key, "dates": [str(v.date()) for v in prefix.date], "close": prefix.close.tolist()}
                    futures[pool.submit(fit_job, task)] = path
                for future in as_completed(futures):
                    path = futures[future]
                    try:
                        cell = future.result()
                    except Exception as error:
                        cell = {"status": "failed", "error": f"{type(error).__name__}: {error}"}
                    atomic_json(path, clean(cell))
                    if cell["status"] == "complete":
                        cells.append(cell)
                        counters["completed"] += 1
                    else:
                        counters["failed"] += 1
                    save_progress()
                expected = sum(n <= len(frame[frame.date <= asof]) for n in WINDOWS)
                if len(cells) == expected:
                    try:
                        record = make_record(asset_id, frame, metadata, asof, cells, method)
                        historical = export_record(output, record, offset == 0)
                        counters["exports_completed"] += 1
                        done = entries[asset_id].setdefault("completed_asofs", [])
                        done.append(str(asof.date()))
                        entries[asset_id]["available_asofs"] = [item["asof"] for item in historical["frames"]]
                        entries[asset_id]["status"] = "complete_sample" if len(done) == 3 else "current_ready"
                        print(json.dumps({"event": "asof_complete", "id": asset_id, "asof": str(asof.date()),
                                          "windows": len(cells), "elapsed_seconds": round(time.perf_counter() - start, 2)}), flush=True)
                    except Exception as error:
                        counters["exports_failed"] += 1
                        entries[asset_id]["status"] = "export_failed"
                        errors.append({"stage": "export", "asset": asset_id, "asof": str(asof.date()),
                                       "error": f"{type(error).__name__}: {error}"})
                else:
                    entries[asset_id]["status"] = "fit_failed"
                save_progress()
            if stopped:
                break
    snapshot = save_progress()
    print(json.dumps({"event": "finished", "status": snapshot["status"], "counts": snapshot["counts"],
                      "elapsed_seconds": snapshot["elapsed_seconds"]}), flush=True)
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--assets", default=",".join(ASSETS))
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--budget-seconds", type=float, default=900)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--reexport-manifest", type=Path, help="Re-export frozen completed records only; no download, fit or cache migration")
    args = parser.parse_args()
    ids = args.assets.split(",")
    if any(asset not in ASSETS for asset in ids) or args.workers < 1 or args.budget_seconds <= 0:
        parser.error("Invalid assets, workers or time budget")
    if args.reexport_manifest and args.refresh:
        parser.error("Export-only mode cannot refresh data")
    result = reexport_cached(args.root, args.reexport_manifest) if args.reexport_manifest else run(args.root, ids, args.workers, args.budget_seconds, args.refresh)
    if result["status"] != "complete":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
