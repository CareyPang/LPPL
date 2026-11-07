"""Execute frozen claim-boundary ablations on saved fits; no fitting/network."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import shutil
import subprocess
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

import pandas as pd

from research.eval.top_time.claim_boundary import (
    VERSION,
    build_claims,
    formal_dates,
    integer_date_cluster,
    visible_units,
)
from research.eval.top_time.contracts import Forecast, LabelBook, TopEvent
from research.eval.top_time.replay import build_replay
from research.eval.top_time.scoring import evaluate
from research.lppls.window_clusters import analyze_asof
from tools.lppl_top_time_replay import CsvSink, append_json, compressed_jsonl, json_write, sha

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "docs/research/evidence/window-cluster-20261106/v1"
REPLAY = ROOT / "docs/research/evidence/top-time-replay-20261106/v1"
RAW = Path("D:/CodexData/temp/lppl-oscillation-artifacts-20261106")
PROTOCOL = ROOT / "docs/research/2026-11-06-claim-boundary-ablation-protocol.md"
ARM_SPECS = {
    "continuous_full_any": ("full", False, False),
    "calendar_full_any": ("full", True, False),
    "calendar_thin_any": ("thin", True, False),
    "calendar_full_cross": ("full", True, True),
}
PAIRS = {
    "date_width": ("continuous_full_any", "calendar_full_any"),
    "window_selection": ("calendar_full_any", "calendar_thin_any"),
    "cross_scale": ("calendar_full_any", "calendar_full_cross"),
}
SOURCES = [Path(__file__), ROOT / "research/eval/top_time/claim_boundary.py",
           ROOT / "research/eval/top_time/contracts.py", ROOT / "research/eval/top_time/scoring.py",
           ROOT / "research/eval/top_time/replay.py", ROOT / "research/lppls/window_clusters.py",
           ROOT / "research/lppls/oscillations.py", ROOT / "tools/lppl_top_time_replay.py", PROTOCOL]


def load_books():
    books = {}
    with gzip.open(REPLAY / "label_books.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            d = json.loads(line)
            d["sessions"] = tuple(d["sessions"])
            d["events"] = [TopEvent(**e) for e in d["events"]]
            d["known"] = {k: tuple(v) for k, v in d["known"].items()}
            books[d["symbol"]] = LabelBook(**d)
    return books


def candidate_rows(symbol, source, raw, scales):
    """Only current fits and original as-of grid metadata enter generation."""
    groups = {str(date)[:10]: d for date, d in raw.groupby("date")}
    lookup = {(str(d), mode): group for (d, mode), group in scales.groupby(["date", "mode"])}
    base = source[source.arm == "cluster_any_full"].sort_values("position")
    empty = raw.iloc[:0]
    arms = {a: [] for a in (*ARM_SPECS, "calendar_fixed_10")}
    checked = 0
    for old in base.to_dict("records"):
        date = str(old["date"])
        analyses = {}
        for mode in ("full", "thin"):
            original = lookup[(date, mode)]
            expected = sorted({n for cell in original.expected_windows for n in json.loads(cell)})
            analyses[mode] = analyze_asof(groups.get(date, empty), expected, mode=mode)
        # The continuous arm must reproduce the sealed original selection.
        r = analyses["full"]
        c = r["clusters"]["any"]["primary"]
        alarm = bool(r["evaluable"] and c)
        assert alarm == bool(old["own_alarm"]) and r["evaluable"] == bool(old["own_evaluable"]), date
        if alarm:
            assert math.isclose(c["lo"], old["interval_lo"], rel_tol=0, abs_tol=1e-12)
            assert math.isclose(c["hi"], old["interval_hi"], rel_tol=0, abs_tol=1e-12)
            assert c["id"] == old["cluster_id"]
        checked += 1
        for arm, (mode, integer_width, cross) in ARM_SPECS.items():
            result = analyses[mode]
            chosen = (integer_date_cluster(result["fits"], result["scales"], cross=cross)
                      if result["evaluable"] and integer_width else
                      result["clusters"]["any"]["primary"] if not integer_width else None)
            arms[arm].append(dict(symbol=symbol, arm=arm, date=date, position=int(old["position"]),
                                  own_evaluable=bool(result["evaluable"]), status="ok" if result["evaluable"] else "source_unavailable",
                                  own_alarm=bool(result["evaluable"] and chosen),
                                  interval_lo=chosen["lo"] if chosen else None,
                                  interval_hi=chosen["hi"] if chosen else None,
                                  member_windows=chosen["members"] if chosen else [],
                                  mass=chosen["mass"] if chosen else None))
        arms["calendar_fixed_10"].append(dict(symbol=symbol, arm="calendar_fixed_10", date=date,
            position=int(old["position"]), own_evaluable=True, own_alarm=True, interval_lo=6., interval_hi=15.,
            status="fixed_calendar", member_windows=[], mass=None))
    return arms, checked


def observations_as_forecasts(ledger):
    return [Forecast(f"observation:{r['prediction_id']}", f"observation:{r['prediction_id']}",
                     r["symbol"], "stage", r["interval_start"], r["interval_end"],
                     r["position"], r["position"], f"{r['date']}T17:00:00+08:00",
                     r["position"]+1, "theoretical") for r in ledger
            if r["signal"] and not r["formal_eligible"]]


def run(output: Path, freeze_commit: str):
    if output.exists():
        raise ValueError("output must not exist; sealed evidence is never overwritten")
    frozen = subprocess.check_output(["git", "show", f"{freeze_commit}:{PROTOCOL.relative_to(ROOT).as_posix()}"], cwd=ROOT)
    if hashlib.sha256(frozen).hexdigest() != sha(PROTOCOL):
        raise ValueError("working protocol differs from frozen commit")
    old_manifest = json.loads((OLD / "manifest.json").read_text(encoding="utf-8"))
    replay_manifest = json.loads((REPLAY / "manifest.json").read_text(encoding="utf-8"))
    symbols = [r["symbol"] for r in old_manifest["source_statistics"]]
    inputs = [OLD / "manifest.json", OLD / "asofs.csv.gz", OLD / "scales.csv.gz",
              REPLAY / "manifest.json", REPLAY / "label_books.jsonl.gz", REPLAY / "event_scores.csv",
              REPLAY / "summary_by_symbol.csv", REPLAY / "scan_inventory.csv"]
    inputs += [RAW / f"{s}.parquet" for s in symbols]
    # Every sealed input is authenticated before reading it for the experiment.
    before = {str(p): sha(p) for p in inputs+SOURCES}
    for name, key in (("asofs.csv.gz", "asofs"), ("scales.csv.gz", "scales")):
        assert sha(OLD / name) == old_manifest["outputs"][key]["sha256"]
    for symbol in symbols:
        path = RAW / f"{symbol}.parquet"
        expected = next(v for k, v in old_manifest["before_sha256"].items() if Path(k).name == path.name and "artifacts" in k)
        assert sha(path) == expected
    # Replay manifest output schema is itself part of the frozen input contract.
    for name, item in replay_manifest["outputs"].items():
        path = REPLAY / name
        if path in inputs:
            assert sha(path) == item["sha256"]
    books = load_books()
    asofs = pd.read_csv(OLD / "asofs.csv.gz", float_precision="round_trip")
    scales = pd.read_csv(OLD / "scales.csv.gz")
    scans = pd.read_csv(REPLAY / "scan_inventory.csv")
    old_summary = pd.read_csv(REPLAY / "summary_by_symbol.csv")
    output.mkdir(parents=True)
    code_dir = output / "executed_sources"
    code_dir.mkdir()
    for p in SOURCES:
        shutil.copyfile(p, code_dir / p.name)
    generated = datetime.now(UTC).isoformat()
    started = time.perf_counter()
    summary, event_rows, comparisons, pairing = [], [], [], []
    ledger_sink = CsvSink(output / "lifecycle_ledger.csv.gz")
    candidate_sink = CsvSink(output / "candidate_intervals.csv.gz")
    evaluation_sink = compressed_jsonl(output / "evaluations.jsonl.gz")
    forecasts_sink = compressed_jsonl(output / "formal_forecasts.jsonl.gz")
    reconstructed = 0

    def score(book, forecasts, experiment, arm, mode, start, end, ledger=None):
        scored = evaluate(book, forecasts, mode="diagnostic", start_session=start, end_session=end)
        metric = scored.metrics["stage"]
        tag = dict(symbol=book.symbol, experiment=experiment, arm=arm, score_mode=mode)
        append_json(evaluation_sink, {**tag, **scored.to_dict()})
        counts = Counter(r["state"] for r in ledger or [])
        signals = [r for r in ledger or [] if r["signal"]]
        transitions = [(a, b) for a, b in zip(signals, signals[1:], strict=False) if not a["formal_eligible"]]
        row = {**tag, **{k: metric[k] for k in ("E", "P", "TP", "FP", "FN", "pending_claims")},
               "notifications": len(forecasts), "early_observations": counts["EARLY_OBSERVATION"],
               "nonformal_observations": counts["NONFORMAL_OBSERVATION"],
               "formal_candidates": sum(r["formal_eligible"] for r in ledger or []),
               "formal_withheld": counts["FORMAL_WITHHELD_BY_PAIR"],
               "new_formal": counts["NEW_FORMAL"], "formal_revisions": counts["FORMAL_REVISION"],
               "all_signal_outputs": len(signals), "duplicate_event_claims": scored.metrics["diagnostics"]["duplicate_claims"],
               "observation_successors": len(transitions),
               "observation_to_formal": sum(b["delivered"] for a, b in transitions),
               "observation_tail_unresolved": int(bool(signals and not signals[-1]["formal_eligible"])),
               "successful_leads": metric["successful_lead_distribution"]["values"],
               "successful_lead_median": metric["successful_lead_distribution"]["median"]}
        summary.append(row)
        lookup = {f.prediction_id: f for f in forecasts}
        events = {}
        for event in scored.events:
            if event["scale"] != "stage":
                continue
            f = lookup.get(event["first_prediction_id"])
            item = {**tag, **event, "peak_date": book.sessions[event["peak_session"]],
                    "first_cutoff_date": book.sessions[f.data_cutoff_session] if f else "",
                    "interval_start": f.interval_start if f else None, "interval_end": f.interval_end if f else None,
                    "lead": event["peak_session"]-f.action_session if f else None,
                    "window_lead": f.interval_start-f.action_session if f else None,
                    "width": f.interval_end-f.interval_start+1 if f else None}
            event_rows.append(item)
            events[event["event_id"]] = item
        return events, metric

    for symbol in symbols:
        book = books[symbol]
        source = asofs[asofs.symbol == symbol].copy()
        inventory = scans[scans.symbol == symbol]
        planned = set(inventory.date)
        fits = set(inventory.loc[inventory.raw_fit_rows > 0, "date"])
        start_scan = int(inventory.session.min())
        start, end = start_scan + 63, max(i for i, d in enumerate(book.sessions) if d <= "2018-12-31")
        for arm in old_manifest["arms"]:
            rows = source[source.arm == arm].sort_values("position").to_dict("records")
            old_bundle = build_replay(symbol, book.sessions, rows, scheduled_dates=planned, fit_dates=fits,
                arm=arm, scope="stage", source_id=sha(OLD/"asofs.csv.gz"), protocol_hash=sha(PROTOCOL),
                generated_at=generated, start_session=start_scan, end_session=end)
            _, old_metric = score(book, old_bundle.forecasts, "saved_same_sequence", arm, "old_episode_first", start, end)
            reference = old_summary[(old_summary.symbol == symbol) & (old_summary.arm == arm) & (old_summary.scope_probe == "stage")].iloc[0]
            assert (old_metric["E"], old_metric["TP"], old_metric["FN"]) == (reference.E, reference.TP, reference.FN)
            score(book, visible_units(old_bundle.forecasts), "saved_same_sequence", arm, "visible_record_first", start, end)
            ledger, formal = build_claims(symbol, arm, rows)
            ledger_sink.add([{**r, "experiment": "saved_lifecycle", "generated_at": generated} for r in ledger])
            score(book, formal, "saved_lifecycle", arm, "formal_episode_first", start, end, ledger)
            score(book, visible_units(formal), "saved_lifecycle", arm, "formal_visible_first", start, end, ledger)
            score(book, observations_as_forecasts(ledger), "saved_observation_diagnostic", arm,
                  "not_formal_forecasts", start, end)
        raw = pd.read_parquet(RAW / f"{symbol}.parquet")
        raw["date"] = pd.to_datetime(raw.date).dt.strftime("%Y-%m-%d")
        arms, checked = candidate_rows(symbol, source, raw, scales[scales.symbol == symbol])
        reconstructed += checked
        natural_events = {}
        for arm, rows in arms.items():
            candidate_sink.add(rows)
            ledger, formal = build_claims(symbol, arm, rows)
            ledger_sink.add([{**r, "experiment": "natural", "generated_at": generated} for r in ledger])
            for f in formal:
                append_json(forecasts_sink, dict(experiment="natural", arm=arm, **asdict(f)))
            score(book, formal, "natural", arm, "formal_episode_first", start, end, ledger)
            natural_events[arm], _ = score(book, visible_units(formal), "natural", arm, "formal_visible_first", start, end, ledger)
            score(book, observations_as_forecasts(ledger), "natural_observation_diagnostic", arm,
                  "not_formal_forecasts", start, end)
        for pair, (left, right) in PAIRS.items():
            left_dates, right_dates = formal_dates(arms[left]), formal_dates(arms[right])
            common = left_dates & right_dates
            pairing.append(dict(symbol=symbol, pair=pair, left=left, right=right,
                                left_natural=len(left_dates), right_natural=len(right_dates),
                                paired_notifications_each=len(common),
                                left_withheld=len(left_dates-common), right_withheld=len(right_dates-common),
                                identical_notification_dates=True))
            counts = []
            for arm in (left, right, "calendar_fixed_10"):
                ledger, formal = build_claims(symbol, arm, arms[arm], allowed_dates=common)
                counts.append(len(formal))
                assert {book.sessions[f.published_session] for f in formal} == common
                ledger_sink.add([{**r, "experiment": f"paired_{pair}", "generated_at": generated} for r in ledger])
                for f in formal:
                    append_json(forecasts_sink, dict(experiment=f"paired_{pair}", arm=arm, **asdict(f)))
                paired_events, _ = score(book, visible_units(formal), f"paired_{pair}", arm,
                                         "formal_visible_first", start, end, ledger)
                for event_id, row in paired_events.items():
                    natural = natural_events[arm][event_id]
                    comparisons.append(dict(symbol=symbol, pair=pair, arm=arm, event_id=event_id,
                        peak_date=row["peak_date"], natural_first=natural["first_prediction_id"],
                        paired_first=row["first_prediction_id"], natural_hit=natural["strict_hit"],
                        paired_hit=row["strict_hit"], lost_hit=natural["strict_hit"] and not row["strict_hit"],
                        gained_hit=row["strict_hit"] and not natural["strict_hit"],
                        lost_claim=bool(natural["first_prediction_id"] and not row["first_prediction_id"])))
            assert len(set(counts)) == 1
        print(f"completed {symbol}: {checked} original scans reproduced", flush=True)
    ledger_sink.close()
    candidate_sink.close()
    evaluation_sink.close()
    forecasts_sink.close()
    for name, rows in (("summary_by_asset.csv", summary), ("event_scores.csv", event_rows),
                       ("pairing_inventory.csv", pairing), ("pairing_event_changes.csv", comparisons)):
        sink = CsvSink(output / name)
        sink.add(rows)
        sink.close()
    pooled = []
    groups = {}
    for row in summary:
        groups.setdefault((row["experiment"], row["arm"], row["score_mode"]), []).append(row)
    for (experiment, arm, mode), rows in groups.items():
        totals = {key: sum(r[key] for r in rows) for key in rows[0]
                  if key not in {"symbol", "experiment", "arm", "score_mode", "successful_leads", "successful_lead_median"}}
        leads = sorted(v for r in rows for v in r["successful_leads"])
        totals.update(experiment=experiment, arm=arm, score_mode=mode, successful_leads=leads,
                      successful_lead_median=median(leads) if leads else None,
                      observation_to_formal_fraction=(totals["observation_to_formal"]/totals["observation_successors"]
                                                      if totals["observation_successors"] else None))
        pooled.append(totals)
    sink = CsvSink(output / "summary_pooled.csv")
    sink.add(pooled)
    sink.close()
    after = {str(p): sha(p) for p in inputs+SOURCES}
    assert before == after
    outputs = {p.name: {"sha256": sha(p), "bytes": p.stat().st_size} for p in sorted(output.iterdir()) if p.is_file()}
    json_write(output / "manifest.json", dict(version=VERSION, protocol_commit=freeze_commit,
        generated_at=generated, finished_at=datetime.now(UTC).isoformat(), elapsed_seconds=time.perf_counter()-started,
        model_fit_calls=0, network_fetches=0, original_published_forecasts=0, minimum_complete_cycles=1.5,
        reproduced_original_scans=reconstructed, paired_comparisons=PAIRS,
        before_sha256=before, after_sha256=after, inputs_and_sources_unchanged=True,
        outputs=outputs, evidence_status="CONDITIONAL_CONSUMED_DEVELOPMENT_REPLAY_NOT_PROSPECTIVE"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--freeze-commit", required=True)
    args = parser.parse_args()
    run(args.out, args.freeze_commit)
