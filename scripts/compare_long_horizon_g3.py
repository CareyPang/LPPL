"""Run the unchanged website G3 fit on six additional, registered windows.

Local research only. Keep these cells separate from the original sparse27
export and the independent future-only experiment. This is a fit comparison,
not an out-of-sample forecast evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from research.pipeline.global_terminal import atomic_json, clean, derived_and_rules, fit_job, fit_key, method_identity

WINDOWS = (900, 925, 950, 6500, 6600, 6700)
ASSETS = ("US_IXIC", "US_NDX")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--asof", default="2026-11-20")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "cells").mkdir(exist_ok=True)
    method = method_identity()
    tasks, data_versions = [], {}
    for asset in ASSETS:
        record = json.loads((args.source / "global" / f"{asset}_latest.json").read_text(encoding="utf-8"))
        data_versions[asset] = record["data_version"]
        history = record["price_history"]
        frame = pd.DataFrame({"date": pd.to_datetime(history["dates"]), "close": history["close"]})
        frame = frame[frame.date <= pd.Timestamp(args.asof)]
        for n in WINDOWS:
            key = fit_key(frame, pd.Timestamp(args.asof), n, "g3", method)
            tail = frame.tail(n)
            tasks.append({"asset_id": asset, "asof": args.asof, "n": n, "optimizer": "g3", "key": key,
                          "dates": tail.date.dt.strftime("%Y-%m-%d").tolist(), "close": tail.close.tolist()})
    protocol = {"schema_version": "long_g3_comparison_v1", "asof": args.asof, "assets": list(ASSETS),
                "windows": list(WINDOWS), "method": method, "expected": len(tasks),
                "selection_status": "exploratory comparison chosen after reviewing prior results",
                "first_visible_at": None, "stage_top_score": None,
                "fit_input_hashes": [t["key"] for t in tasks]}
    digest = hashlib.sha256(json.dumps(protocol, sort_keys=True).encode()).hexdigest()
    manifest = root / "protocol.json"
    if manifest.exists():
        previous = json.loads(manifest.read_text(encoding="utf-8"))
        if previous["protocol_hash"] != digest:
            raise ValueError("Protocol changed; choose a new output directory instead of overwriting")
    else:
        atomic_json(manifest, {**protocol, "protocol_hash": digest, "registered_at": datetime.now(UTC).isoformat()})
    cells, pending = [], []
    for task in tasks:
        path = root / "cells" / f"{task['key']}.json"
        if path.exists():
            cell = json.loads(path.read_text(encoding="utf-8"))
            if cell.get("fit_input_hash") != task["key"]:
                raise ValueError("Cell hash identity mismatch")
            cells.append(cell)
        else:
            pending.append(task)

    def save_progress():
        complete = sum(c["status"] == "complete" for c in cells)
        failed = sum(c["status"] != "complete" for c in cells)
        atomic_json(root / "progress.json", {"expected": len(tasks), "completed": complete, "failed": failed,
                    "pending": len(tasks) - len(cells), "updated_at": datetime.now(UTC).isoformat()})

    save_progress()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fit_job, task): task for task in pending}
        for future in as_completed(futures):
            task = futures[future]
            cell = future.result()
            atomic_json(root / "cells" / f"{task['key']}.json", cell)
            cells.append(cell)
            save_progress()
            print(f"{len(cells)}/{len(tasks)} {task['asset_id']} n={task['n']} {cell['status']} {cell['seconds']:.2f}s", flush=True)
    summary = {**protocol, "protocol_hash": digest, "assets": {}, "counts": json.loads((root / "progress.json").read_text())}
    for asset in ASSETS:
        rows = []
        for cell in sorted((c for c in cells if c["asset_id"] == asset), key=lambda c: c["n"]):
            if cell["status"] != "complete":
                rows.append({"n": cell["n"], "status": "failed", "error": cell.get("error")})
                continue
            derived, rules = derived_and_rules([cell["row"]])
            row = derived.iloc[0]
            rows.append({"n": cell["n"], "status": "complete", "ahead": row.ahead, "m": row.m, "omega": row.w,
                         "B": row.B, "sse": row.sse, "full_cycles": row.n_osc,
                         "box_pass": bool(rules.box.iloc[0]), "cycles_1_5_pass": bool(rules.box_cycles_1_5.iloc[0]),
                         "fit_input_hash": cell["fit_input_hash"], "seconds": cell["seconds"],
                         "optimizer_calls": cell["optimizer_calls"]})
        summary["assets"][asset] = {"asof": args.asof, "data_version": data_versions[asset], "windows": rows}
    atomic_json(root / "summary.json", clean(summary))
    print(str(root / "summary.json"), flush=True)


if __name__ == "__main__":
    main()
