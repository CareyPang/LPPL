"""Recreate post-fit TOP_RULE diagnostics from saved synthetic fits; no optimization."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from research.lppls import core


def diagnostics(evidence: Path) -> dict:
    result = json.loads((evidence / "results.json").read_text(encoding="utf-8"))
    cases = {case["name"]: case for case in json.loads(
        (evidence / "inputs.json").read_text(encoding="utf-8"))}
    rows = []
    for row in result["rows"]:
        case = cases[row["case"]]
        if case["inside"]:
            rows.append({"case": case["name"], "method": row["method"], "seed": row["seed"],
                         "filter_status": "NOT_APPLICABLE_future_only_rule"})
            continue
        fit = core.unpack(np.array(row["theta"]), np.array(case["t"]), np.array(case["y"]))
        passed, reasons = core.qualifies(fit, core.TOP_RULE)
        rows.append({"case": case["name"], "method": row["method"], "seed": row["seed"],
                     "filter": "existing_core_TOP_RULE", "pass": passed, "reasons": reasons,
                     "B": fit.B, "damping": fit.damping, "n_osc_cycles": fit.n_osc(), "r2": fit.r2,
                     "tc_absolute_error_if_pass": row["tc_absolute_error"] if passed else None})
    return {"purpose": "Post-fit deterministic diagnostics; no optimizer rerun; not production box rule",
            "rule": core.TOP_RULE, "rows": rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit("Preserve existing evidence; choose a new output file.")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(diagnostics(args.evidence), indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
