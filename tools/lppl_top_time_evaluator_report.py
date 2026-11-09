"""Reproduce evaluator evidence without downloads, fitting, or legacy writes.

The 24 worlds check software arithmetic, never forecast skill. Real prices only
check retrospective label semantics. The old forecast cache is admission-audited,
not silently given hindsight stage claims or synthetic publication times.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from research.eval.top_time.cli import run_bundle
from research.eval.top_time.contracts import (
    VERSION,
    Forecast,
    LabelBook,
    Protocol,
    ScheduledRun,
    TopEvent,
)
from research.eval.top_time.labels import build_labels
from research.eval.top_time.scoring import evaluate

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "docs/research/evidence/top-time-label-review-20261106"
ARCHIVE = ROOT / "docs/research/evidence/window-cluster-20261106/v1"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def preserved_files():
    paths = [ROOT / name for name in ("research/eval/interval.py", "research/labels/top.py",
                                     "tools/lppl_window_cluster_research.py")]
    for folder in (OLD, ARCHIVE):
        paths.extend(p for p in folder.rglob("*") if p.is_file())
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)}


def calendar(n):
    return tuple((date(2020, 1, 1) + timedelta(days=i)).isoformat() for i in range(n))


def assert_subset(actual, expected, context):
    for key, value in expected.items():
        if isinstance(value, dict):
            assert_subset(actual[key], value, context + "." + key)
        elif actual[key] != value:
            raise AssertionError(f"{context}.{key}: {actual[key]!r} != {value!r}")


def golden_cases(out):
    source = ROOT / "tests/fixtures/top_time/scoring_cases.json"
    fixture = json.loads(source.read_text(encoding="utf-8"))
    summaries, details = [], []
    for case in fixture["cases"]:
        spec = fixture["books"][case["book"]]
        book = LabelBook(symbol=fixture["symbol"], sessions=calendar(201),
                         asof_session=spec["asof_session"],
                         events=[TopEvent(**fixture["events"][eid]) for eid in spec["events"]],
                         known={s: tuple(fixture["known_masks"][m]) for s, m in spec["known"].items()},
                         pending=spec["pending"], metadata={"truth_source": "manual_fixture"})
        result = evaluate(book, [Forecast(**r) for r in case["forecasts"]],
                          [ScheduledRun(**r) for r in case["runs"]],
                          config=Protocol(**fixture["protocol"]))
        expect = case["expected"]
        assert_subset(result.metrics["stage"], expect["stage"], case["id"])
        assert_subset(result.metrics["stage"]["event_only"], expect["event_only_stage"], case["id"])
        for section in ("short", "diagnostics", "family"):
            if section in expect:
                assert_subset(result.metrics[section], expect[section], case["id"])
        claims = {r["prediction_id"]: r for r in result.claims}
        for pid, expected in expect.get("claims", {}).items():
            assert_subset(claims[pid], expected, case["id"] + "." + pid)
        row = {"case": case["id"], "contract_pass": True}
        for scale in ("stage", "short"):
            row.update({f"{scale}_{key}": result.metrics[scale][key] for key in ("E", "P", "TP", "FN")})
        row["stage_event_only_TP"] = result.metrics["stage"]["event_only"]["TP"]
        summaries.append(row)
        details.append({"case": case["id"], "expected": expect, "result": result.to_dict()})
    pd.DataFrame(summaries).to_csv(out / "golden_cases.csv", index=False, lineterminator="\n")
    write(out / "golden_details.json", {"status": "SYNTHETIC_CONTRACT_NOT_MODEL_SKILL", "cases": details})
    return len(summaries), source


def real_labels(out):
    case_source = OLD / "selected_real_cases.json"
    review = json.loads(case_source.read_text(encoding="utf-8"))
    comparison = review["right_context_semantic_comparison"]["cases"]
    inputs = {s: ROOT / f"data/frozen/v20261104/{s}_qfq.parquet" for s in ("sh000001", "sh600519")}
    frames = {s: pd.read_parquet(p).set_index("date") for s, p in inputs.items()}
    # Union preserves inter-file holes; it does not attest official calendar completeness.
    dates = sorted(set().union(*(set(f.index) for f in frames.values())))
    dates = [d for d in dates if pd.Timestamp("2022-01-01") <= d <= pd.Timestamp("2025-01-01")]
    sessions = [d.strftime("%Y-%m-%d") for d in dates]
    rows, audit = [], []
    for symbol, frame in frames.items():
        prices = frame.reindex(dates)["close"].tolist()
        for right in (21, 42):
            book = build_labels(symbol, sessions, prices, config=Protocol(stage_right=right),
                                input_status="FROZEN_QFQ_NOT_HISTORICAL_PIT")
            for case in [c for c in comparison if c["symbol"] == symbol]:
                i = sessions.index(case["peak_date"])
                linked = {s: [e for e in book.events if e.scale == s and i in e.candidate_sessions]
                          for s in ("short", "stage")}
                actual = {s: bool(linked[s]) if book.known[s][i] else None for s in linked}
                expected = case[f"stage_L63_R{right}"]
                if actual["stage"] != expected or actual["short"] is not True:
                    raise AssertionError(f"real semantic mismatch: {symbol} {case['peak_date']} R{right}: {actual}")
                rows.append({"symbol": symbol, "peak_date": case["peak_date"], "stage_right": right,
                             "short": actual["short"], "stage": actual["stage"], "contract_pass": True,
                             "status": "VERIFIED_CONDITIONAL_LABEL_NOT_FORECAST"})
                audit.append({"symbol": symbol, "peak_date": case["peak_date"], "stage_right": right,
                              "events": [asdict(e) for es in linked.values() for e in es],
                              "status": "OFFICIAL_CALENDAR_AND_PIT_NOT_ESTABLISHED"})
    pd.DataFrame(rows).to_csv(out / "real_labels.csv", index=False, lineterminator="\n")
    write(out / "real_label_audit.json", {"calendar": "union of existing observed rows, not official",
          "price": "frozen qfq close; adjustment history not attested", "cases": audit})
    return rows, [case_source, *inputs.values()]


def synthetic_labels(out):
    source = OLD / "synthetic_cases.json"
    cases = json.loads(source.read_text(encoding="utf-8"))["cases"]
    rows = []
    for case in cases:
        anchors = case["anchors"]
        prices = np.interp(range(181), [a[0] for a in anchors], [a[1] for a in anchors]).round(2).tolist()
        # The old examples define structural neighborhoods, not fully observed RISE search.
        book = build_labels(case["id"], calendar(181), prices,
                            config=Protocol(stage_right=21, require_stage_rise=False), input_status="SYNTHETIC")
        for pos, peak in enumerate(case["peaks"]):
            actual = {s: any(peak in e.candidate_sessions for e in book.events if e.scale == s)
                      if book.known[s][peak] else None for s in ("short", "stage")}
            expected = {s: case[f"expected_{s}"][pos] for s in ("short", "stage")}
            if actual != expected:
                raise AssertionError(f"synthetic semantic mismatch {case['id']} {peak}: {actual}!={expected}")
            rows.append({"case": case["id"], "peak": peak, **actual, "contract_pass": True})
    write(out / "synthetic_label_checks.json", {"status": "SYNTHETIC_NOT_MODEL_SKILL", "checks": rows})
    return len(rows), source


def admission_audit(out):
    source = ARCHIVE / "asofs.csv.gz"
    frame = pd.read_csv(source)
    required = ["prediction_id", "episode_id", "scope", "published_at", "published_session",
                "action_session", "actionability", "on_time"]
    report = {"evidence_status": "VERIFIED_SCHEMA_AUDIT", "source": source.relative_to(ROOT).as_posix(),
              "rows": len(frame), "columns": list(frame.columns),
              "missing_forecast_contract_fields": [c for c in required if c not in frame],
              "formal_stage_performance": "NOT_ESTABLISHED", "admitted_as_formal_stage_forecasts": 0,
              "reason": "No contemporaneous explicit stage claims or publication/action ledger. Fit scale/date is not such a ledger.",
              "old_results": "preserved; no reinterpretation as stage predictions"}
    write(out / "archived_forecast_admission.json", report)
    return report, source


def toy_input():
    sessions = list(calendar(351))
    return {"schema_version": VERSION, "symbol": "SYNTHETIC", "sessions": sessions,
            "prices": np.interp(range(351), [0, 100, 160, 220, 280, 350], [120, 105, 90, 140, 110, 115]).round(2).tolist(),
            "price_basis": "synthetic units", "calendar_status": "SYNTHETIC", "price_basis_status": "SYNTHETIC",
            "publication_status": "SYNTHETIC", "input_status": "SYNTHETIC", "mode": "fixture", "protocol": {},
            "runs": [{"run_id": "r1", "symbol": "SYNTHETIC", "cutoff_session": 200, "status": "ON_TIME_INTERVAL"}],
            "forecasts": [{"prediction_id": "p1", "episode_id": "e1", "symbol": "SYNTHETIC", "scope": "stage",
                           "interval_start": 215, "interval_end": 224, "data_cutoff_session": 200,
                           "published_session": 200, "published_at": sessions[200] + "T16:00:00+08:00",
                           "action_session": 201, "actionability": "verified", "run_id": "r1"}]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out
    if out.exists():
        raise FileExistsError("new output directory required; never overwrite evidence")
    before = preserved_files()
    inputs = [ROOT / "tests/fixtures/top_time/scoring_cases.json", OLD / "synthetic_cases.json",
              OLD / "selected_real_cases.json", ARCHIVE / "asofs.csv.gz",
              *(ROOT / f"data/frozen/v20261104/{s}_qfq.parquet" for s in ("sh000001", "sh600519"))]
    sources = [Path(__file__), *sorted((ROOT / "research/eval/top_time").glob("*.py"))]
    locked = {p.relative_to(ROOT).as_posix(): digest(p) for p in inputs + sources}
    started = time.perf_counter()
    out.mkdir(parents=True, exist_ok=False)
    goldens, golden_source = golden_cases(out)
    synthetic, synthetic_source = synthetic_labels(out)
    real, real_sources = real_labels(out)
    admission, archive_source = admission_audit(out)
    write(out / "example_input.json", toy_input())
    toy = run_bundle(out / "example_input.json", out / "example_result")
    after = preserved_files()
    if before != after:
        raise AssertionError("legacy evaluator or evidence changed")
    if locked != {p.relative_to(ROOT).as_posix(): digest(p) for p in inputs + sources}:
        raise AssertionError("input or implementation changed during evidence generation")
    write(out / "preserved_legacy_sha256.json", {"unchanged": True, "files": before})
    write(out / "protocol.json", Protocol().to_dict())
    summary = {"evaluator_version": VERSION, "golden_contract_cases_passed": goldens,
               "synthetic_label_checks_passed": synthetic, "real_label_checks_passed": len(real),
               "preserved_legacy_files": len(before), "archived_rows_audited": admission["rows"],
               "formal_stage_forecasts_admitted": 0, "predictive_skill": "NOT_ESTABLISHED",
               "example_stage_counts": {k: toy["metrics"]["stage"][k] for k in ("E", "P", "TP", "FN")},
               "elapsed_seconds": time.perf_counter() - started,
               "timing_scope": "label/scoring/evidence IO only; no optimization, network or service SLA"}
    write(out / "summary.json", summary)
    assert set(inputs) == {golden_source, synthetic_source, archive_source, *real_sources}
    manifest = {"evaluator_version": VERSION, "evidence_boundary": "implementation and conditional labels, not model skill",
                "input_sha256": {p.relative_to(ROOT).as_posix(): locked[p.relative_to(ROOT).as_posix()] for p in inputs},
                "source_sha256": {p.relative_to(ROOT).as_posix(): locked[p.relative_to(ROOT).as_posix()] for p in sources},
                "output_sha256": {p.relative_to(out).as_posix(): digest(p) for p in sorted(out.rglob("*")) if p.is_file()}}
    write(out / "manifest.json", manifest)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
