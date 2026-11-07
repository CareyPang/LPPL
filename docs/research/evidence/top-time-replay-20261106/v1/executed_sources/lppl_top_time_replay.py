"""Execute the frozen saved-fit replay protocol; no network or optimizer."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import shutil
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

import pandas as pd

from research.eval.top_time.contracts import Protocol
from research.eval.top_time.labels import build_labels
from research.eval.top_time.replay import (
    BASELINE,
    REPLAY_STATUS,
    REPLAY_VERSION,
    build_replay,
    common_event_opportunity,
)
from research.eval.top_time.scoring import evaluate

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "docs/research/2026-11-06-top-time-replay-protocol.md"
OLD = ROOT / "docs/research/evidence/window-cluster-20261106/v1"
RAW = Path("D:/CodexData/temp/lppl-oscillation-artifacts-20261106")
PRICE = ROOT / "data/frozen/v20261024"
SOURCES = [Path(__file__), ROOT / "research/eval/top_time/replay.py",
           ROOT / "research/eval/top_time/contracts.py", ROOT / "research/eval/top_time/labels.py",
           ROOT / "research/eval/top_time/scoring.py", PROTOCOL_PATH]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")


class CsvSink:
    def __init__(self, path, fields=None):
        if str(path).endswith(".gz"):
            self.stream = io.TextIOWrapper(gzip.GzipFile(filename=str(path), mode="wb", mtime=0),
                                           encoding="utf-8", newline="")
        else:
            self.stream = open(path, "w", encoding="utf-8", newline="")
        self.writer = None
        self.rows = 0
        if fields:
            self.writer = csv.DictWriter(self.stream, fieldnames=fields, lineterminator="\n")
            self.writer.writeheader()

    def add(self, rows):
        for row in rows:
            if self.writer is None:
                self.writer = csv.DictWriter(self.stream, fieldnames=list(row), lineterminator="\n")
                self.writer.writeheader()
            self.writer.writerow({k: json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (list, dict)) else v
                                  for k, v in row.items()})
            self.rows += 1

    def close(self):
        self.stream.close()


def compressed_jsonl(path):
    return io.TextIOWrapper(gzip.GzipFile(filename=str(path), mode="wb", mtime=0), encoding="utf-8", newline="\n")


def append_json(stream, value):
    stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False)+"\n")


def run(output: Path, freeze_commit: str):
    if output.exists() and any(output.iterdir()):
        raise ValueError("output must be a new empty directory; old evidence is protected")
    frozen = subprocess.check_output(["git", "show", f"{freeze_commit}:docs/research/2026-11-06-top-time-replay-protocol.md"], cwd=ROOT)
    if hashlib.sha256(frozen).hexdigest() != sha(PROTOCOL_PATH):
        raise ValueError("working protocol differs from its frozen commit")
    old_manifest = json.loads((OLD / "manifest.json").read_text(encoding="utf-8"))
    symbols = [s["symbol"] for s in old_manifest["source_statistics"]]
    original_arms = tuple(old_manifest["arms"])
    arms = (*original_arms, BASELINE)
    inputs = [OLD / "asofs.csv.gz", OLD / "manifest.json"]
    inputs += [RAW / f"{s}.parquet" for s in symbols]
    inputs += [PRICE / f"{s}_qfq.parquet" for s in symbols]
    before = {str(p): sha(p) for p in inputs+SOURCES}
    if before[str(OLD / "asofs.csv.gz")] != old_manifest["outputs"]["asofs"]["sha256"]:
        raise ValueError("saved asofs no longer match original manifest")
    for symbol in symbols:
        for path in (RAW / f"{symbol}.parquet", PRICE / f"{symbol}_qfq.parquet"):
            expected = next(v for k, v in old_manifest["before_sha256"].items()
                            if Path(k).name == path.name and ("artifacts" in k) == (path.parent == RAW))
            if sha(path) != expected:
                raise ValueError(f"immutable input differs: {path}")
    output.mkdir(parents=True, exist_ok=True)
    source_out = output / "executed_sources"
    source_out.mkdir()
    for path in SOURCES:
        shutil.copyfile(path, source_out / path.name)
    generated = datetime.now(UTC).isoformat()
    started = time.perf_counter()
    config = Protocol()
    all_asofs = pd.read_csv(OLD / "asofs.csv.gz")
    if all_asofs.duplicated(["symbol", "date", "arm"]).any():
        raise ValueError("duplicate saved aggregate")
    daily_sink = CsvSink(output / "daily_replay_ledger.csv.gz")
    preview_sink = CsvSink(output / "daily_ledger_preview.csv")
    forecast_sink = CsvSink(output / "hypothetical_forecasts.csv.gz")
    forecast_preview = CsvSink(output / "forecast_preview.csv")
    event_sink = CsvSink(output / "event_scores.csv")
    schedule_sink = CsvSink(output / "scan_inventory.csv")
    evaluation_stream = compressed_jsonl(output / "evaluations.jsonl.gz")
    label_stream = compressed_jsonl(output / "label_books.jsonl.gz")
    summary, input_map, event_table, denominator_checks = [], [], [], []
    aggregate = defaultdict(lambda: {"E": 0, "P": 0, "TP": 0, "FN": 0, "event_only_TP": 0,
                                    "common_E": 0, "common_TP": 0, "notifications": 0,
                                    "scheduled_runs": 0, "input_evaluable_runs": 0,
                                    "pending_claims": 0, "widths": [], "leads_success": [],
                                    "failures": Counter(), "misses": Counter()})
    source_identity = {str(p): before[str(p)] for p in inputs}
    for symbol in symbols:
        price_full = pd.read_parquet(PRICE / f"{symbol}_qfq.parquet").sort_values("date").reset_index(drop=True)
        if price_full.date.duplicated().any():
            raise ValueError("duplicate price dates")
        price_full["date"] = pd.to_datetime(price_full.date)
        price = price_full[price_full.date <= "2019-12-31"].copy()
        sessions = tuple(price.date.dt.strftime("%Y-%m-%d"))
        session_index = {d: i for i, d in enumerate(sessions)}
        source = all_asofs[all_asofs.symbol == symbol].copy()
        planned = set(source.loc[source.scheduled, "date"])
        if not all(sum(source.date == d) == len(original_arms) for d in planned):
            raise ValueError("not all nine strategies have an explicit scheduled status")
        for row in source.itertuples():
            if row.date != sessions[int(row.position)]:
                raise ValueError("asof position drift")
        start = min(session_index[d] for d in planned)
        end = max(i for i, d in enumerate(sessions) if d <= "2018-12-31")
        evaluation_start = start+config.horizon
        raw = pd.read_parquet(RAW / f"{symbol}.parquet", columns=["date", "n"])
        raw["date"] = pd.to_datetime(raw.date).dt.strftime("%Y-%m-%d")
        if raw.duplicated(["date", "n"]).any():
            raise ValueError("duplicate saved raw fit window")
        counts = raw.groupby("date").size().to_dict()
        fit_dates = set(counts)
        schedule_sink.add([{"symbol": symbol, "date": d, "session": session_index[d],
                            "raw_fit_rows": int(counts.get(d, 0)), "all_arm_rows": int(sum(source.date == d))}
                           for d in sorted(planned)])
        source_id = hashlib.sha256("|".join([symbol, before[str(OLD / "asofs.csv.gz")],
                                            before[str(PRICE / f"{symbol}_qfq.parquet")],
                                            before[str(RAW / f"{symbol}.parquet")]]).encode()).hexdigest()
        input_map.append({"source_id": source_id, "symbol": symbol,
                          "asofs_sha256": before[str(OLD / "asofs.csv.gz")],
                          "price_sha256": before[str(PRICE / f"{symbol}_qfq.parquet")],
                          "raw_fit_sha256": before[str(RAW / f"{symbol}.parquet")],
                          "prediction_start": sessions[start], "prediction_end": sessions[end],
                          "label_observation_end": sessions[-1], "evaluation_start": sessions[evaluation_start],
                          "evaluation_end": sessions[end], "planned_scans": len(planned),
                          "days_without_saved_fit": sum(d not in fit_dates for d in planned),
                          "price_basis": "FROZEN_QFQ_SNAPSHOT_NOT_STRICT_PIT",
                          "calendar_basis": "OBSERVED_DATE_INDEX_NOT_INDEPENDENT_EXCHANGE_CALENDAR"})
        common_dates = set(source.groupby("date").own_evaluable.all().loc[lambda s: s].index)
        labels = build_labels(symbol, sessions, [str(p) if pd.notna(p) else None for p in price.close],
                              config=config, input_status="FROZEN_QFQ_SNAPSHOT_NOT_STRICT_PIT")
        append_json(label_stream, asdict(labels))
        common_events = {event.event_id: common_event_opportunity(event.peak_session, sessions,
                         scheduled_dates=planned, common_evaluable_dates=common_dates,
                         first_schedule_session=start, horizon=config.horizon)
                         for event in labels.events}
        E_by_scope = defaultdict(set)
        for arm in arms:
            arm_rows = source[source.arm == arm].to_dict("records") if arm != BASELINE else []
            for scope in ("stage", "short"):
                bundle = build_replay(symbol, sessions, arm_rows, scheduled_dates=planned, fit_dates=fit_dates,
                                      arm=arm, scope=scope, source_id=source_id,
                                      protocol_hash=sha(PROTOCOL_PATH), generated_at=generated,
                                      start_session=start, end_session=end, config=config)
                daily_sink.add(bundle.daily)
                preview_sink.add(bundle.daily[:8] + bundle.daily[-3:])
                forecast_sink.add(bundle.forecast_audit)
                forecast_preview.add(bundle.forecast_audit[:3])
                scored = evaluate(labels, bundle.forecasts, bundle.runs, config=config, mode="diagnostic",
                                  start_session=evaluation_start, end_session=end)
                append_json(evaluation_stream, {"symbol": symbol, "arm": arm, "scope_probe": scope,
                                                "evidence_status": REPLAY_STATUS, **scored.to_dict()})
                metric = scored.metrics[scope]
                E_by_scope[scope].add(metric["E"])
                ev_rows = []
                for row in scored.events:
                    if row["scale"] != scope:
                        continue
                    paired, reason, opportunities = common_events[row["event_id"]]
                    item = {"symbol": symbol, "arm": arm, "scope_probe": scope, **row,
                            "peak_date": sessions[row["peak_session"]], "common_eligible": paired,
                            "common_reason": reason, "scheduled_opportunities": opportunities}
                    ev_rows.append(item)
                    event_table.append(item)
                event_sink.add(ev_rows)
                common_E = sum(r["common_eligible"] for r in ev_rows)
                common_TP = sum(r["common_eligible"] and r["strict_hit"] for r in ev_rows)
                row = {"symbol": symbol, "arm": arm, "scope_probe": scope,
                       **{k: metric[k] for k in ("E", "P", "TP", "FP", "FN", "recall", "precision", "pending_claims",
                                                 "known_anchors", "unknown_anchors")},
                       "event_only_TP": metric["event_only"]["TP"],
                       "common_E": common_E, "common_TP": common_TP,
                       "common_recall": common_TP/common_E if common_E else None,
                       "hypothetical_notifications": len(bundle.forecasts),
                       "scheduled_scans": len(bundle.runs),
                       "input_evaluable_scans": sum(r.status != "FAILED" for r in bundle.runs),
                       "width_median": metric["width_distribution"]["median"],
                       "success_lead_median": metric["successful_lead_distribution"]["median"],
                       "failure_counts": metric["failure_counts"], "missed_event_reasons": metric["missed_event_reasons"]}
                summary.append(row)
                group = aggregate[(arm, scope)]
                for key in ("E", "P", "TP", "FN", "common_E", "common_TP", "event_only_TP", "pending_claims"):
                    group[key] += row[key]
                group["notifications"] += len(bundle.forecasts)
                group["scheduled_runs"] += len(bundle.runs)
                group["input_evaluable_runs"] += row["input_evaluable_scans"]
                group["widths"].extend(metric["width_distribution"]["values"])
                group["leads_success"].extend(metric["successful_lead_distribution"]["values"])
                group["failures"].update(metric["failure_counts"])
                group["misses"].update(metric["missed_event_reasons"])
        for scope, denominators in E_by_scope.items():
            if len(denominators) != 1:
                raise AssertionError("strategy event denominators drifted")
            denominator_checks.append({"symbol": symbol, "scope_probe": scope,
                                       "E": next(iter(denominators)), "all_arms_same_E": True})
        print(f"completed {symbol}: {len(planned)} saved scan dates; labels and 20 probes", flush=True)
    for sink in (daily_sink, preview_sink, forecast_sink, forecast_preview, event_sink, schedule_sink):
        sink.close()
    evaluation_stream.close()
    label_stream.close()
    pooled = []
    for (arm, scope), g in aggregate.items():
        pooled.append({"arm": arm, "scope_probe": scope, **{k: g[k] for k in ("E", "P", "TP", "FN", "event_only_TP",
                                                                                            "common_E", "common_TP", "pending_claims")},
                       "FP": g["P"]-g["TP"], "recall": g["TP"]/g["E"] if g["E"] else None,
                       "precision": g["TP"]/g["P"] if g["P"] else None,
                       "common_recall": g["common_TP"]/g["common_E"] if g["common_E"] else None,
                       "hypothetical_notifications": g["notifications"], "scheduled_scans": g["scheduled_runs"],
                       "input_evaluable_scans": g["input_evaluable_runs"],
                       "width_median": median(g["widths"]) if g["widths"] else None,
                       "success_lead_median": median(g["leads_success"]) if g["leads_success"] else None,
                       "failure_counts": dict(g["failures"]), "missed_event_reasons": dict(g["misses"])})
    for filename, rows in (("summary_by_symbol.csv", summary), ("summary_pooled.csv", pooled),
                            ("denominator_checks.csv", denominator_checks)):
        sink = CsvSink(output / filename)
        sink.add(rows)
        sink.close()
    index = {(r["symbol"], r["arm"], r["scope_probe"], r["event_id"]): r for r in event_table}
    pairs = []
    for arm, reference in old_manifest["pair_references"].items():
        for row in event_table:
            if row["arm"] != arm or not row["common_eligible"]:
                continue
            ref = index[(row["symbol"], reference, row["scope_probe"], row["event_id"])]
            pairs.append({"symbol": row["symbol"], "scope_probe": row["scope_probe"], "arm": arm,
                          "reference": reference, "event_id": row["event_id"], "peak_date": row["peak_date"],
                          "reference_hit": ref["strict_hit"], "candidate_hit": row["strict_hit"],
                          "gain": row["strict_hit"] and not ref["strict_hit"],
                          "loss": ref["strict_hit"] and not row["strict_hit"]})
    sink = CsvSink(output / "paired_common_events.csv")
    sink.add(pairs)
    sink.close()
    actual = CsvSink(output / "actual_published_forecasts.csv", fields=["prediction_id", "symbol", "scope", "data_cutoff",
                    "generated_at", "sealed_at", "published_at", "first_actionable_at", "interval_start", "interval_end",
                    "publication_evidence", "source_hash", "rule_version"])
    actual.close()
    json_write(output / "input_map.json", {"sources": input_map, "input_hashes": source_identity})
    after = {str(p): sha(p) for p in inputs+SOURCES}
    if before != after:
        raise AssertionError("inputs or executed sources changed during execution; evidence invalid")
    manifest = {"version": REPLAY_VERSION, "protocol_commit": freeze_commit, "protocol_sha256": sha(PROTOCOL_PATH),
                "replay_generated_at": generated, "finished_at": datetime.now(UTC).isoformat(),
                "evidence_status": REPLAY_STATUS, "model_fit_calls": 0, "network_fetches": 0,
                "actual_published_forecast_rows": 0, "daily_rows": daily_sink.rows,
                "hypothetical_forecast_rows": forecast_sink.rows,
                "source_parameters": config.to_dict(), "arms": arms, "scope_probes": ["stage", "short"],
                "pair_references": old_manifest["pair_references"],
                "comparison": "development replay; interval-localization probes, not scale-classification performance",
                "calendar": "observed-index only; exchange completeness and actual actionability NOT_ESTABLISHED",
                "timing": "five-observation saved scan grid, no new fits on other daily ledger rows",
                "common_subset": "fixed [peak-H,peak) saved-scan availability diagnostic; not the exact "
                                 "action-adjusted opportunity range [peak-H-1,peak-2] and not exhaustive coverage",
                "before_sha256": before, "after_sha256": after, "input_and_source_unchanged": True,
                "elapsed_seconds": time.perf_counter()-started,
                "outputs": {str(p.relative_to(output)).replace("\\", "/"): {"sha256": sha(p), "bytes": p.stat().st_size}
                            for p in sorted(output.rglob("*")) if p.is_file()}}
    json_write(output / "manifest.json", manifest)
    return pooled, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--protocol-commit", required=True)
    args = parser.parse_args()
    pooled, manifest = run(args.out.resolve(), args.protocol_commit)
    print(json.dumps({"daily_rows": manifest["daily_rows"], "hypothetical_forecast_rows": manifest["hypothetical_forecast_rows"],
                      "stage": [r for r in pooled if r["scope_probe"] == "stage"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
