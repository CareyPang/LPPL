"""Artifact arithmetic checks; no labels, fitting, or strategy selection."""
import csv
import gzip
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
V1 = HERE / "v1"


def rows(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as stream:
        yield from csv.DictReader(stream)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


manifest = json.loads((V1 / "manifest.json").read_text(encoding="utf-8"))
for relative, item in manifest["outputs"].items():
    assert digest(V1 / relative) == item["sha256"], relative
for path, expected in manifest["before_sha256"].items():
    assert digest(Path(path)) == expected, path
assert manifest["before_sha256"] == manifest["after_sha256"]
assert not list(rows(V1 / "actual_published_forecasts.csv"))
forecasts = {r["new_forecast_id"]: r for r in rows(V1 / "hypothetical_forecasts.csv.gz")}
assert len(forecasts) == manifest["hypothetical_forecast_rows"]
episodes = {}
for record in forecasts.values():
    i, left, right = map(int, (record["session"], record["interval_start"], record["interval_end"]))
    assert left == i+math.floor(float(record["interval_lo_saved"]))
    assert right == i+math.ceil(float(record["interval_hi_saved"]))
    assert int(record["width_inclusive"]) == right-left+1
    assert int(record["hypothetical_action_session"]) == i+1
    assert not record["original_published_at"]
    assert record["evidence_status"] == "HYPOTHETICAL_REPLAY_CLAIM_NOT_ORIGINAL"
    key = (record["symbol"], record["arm"], record["scope_probe"])
    if key not in episodes or i > episodes[key][1]:
        assert record["claim_change"] == "FIRST_CLAIM"
        episodes[key] = record["episode_id"], max(i, min(right, i+63))
    else:
        assert record["claim_change"] == "REVISION"
        assert record["episode_id"] == episodes[key][0]
    assert int(record["episode_original_expiry_session"]) == episodes[key][1]
seen, daily_counts, emitted = set(), Counter(), set()
for row in rows(V1 / "daily_replay_ledger.csv.gz"):
    assert row["record_id"] not in seen
    seen.add(row["record_id"])
    daily_counts[row["status"]] += 1
    assert not row["original_published_at"]
    assert row["replay_generated_at"] == manifest["replay_generated_at"]
    if row["scheduled"] == "False":
        assert row["status"] == "NOT_SCHEDULED"
        assert not row["new_forecast_id"]
    if row["new_forecast_id"]:
        assert row["new_forecast_id"] in forecasts
        emitted.add(row["new_forecast_id"])
assert len(seen) == manifest["daily_rows"]
assert emitted == set(forecasts)
evaluation_count = successful_stage = successful_short = 0
with gzip.open(V1 / "evaluations.jsonl.gz", "rt", encoding="utf-8") as stream:
    for line in stream:
        evaluation_count += 1
        value = json.loads(line)
        scope = value["scope_probe"]
        metric = value["metrics"][scope]
        claims = [c for c in value["claims"] if c["scope"] == scope and c["is_first"]
                  and not c["pending"] and not c["boundary_excluded"]]
        events = [e for e in value["events"] if e["scale"] == scope]
        assert metric["P"] == len(claims)
        assert metric["E"] == len(events)
        assert metric["TP"] == sum(c["strict_hit"] for c in claims)
        assert metric["FN"] == metric["E"]-metric["TP"]
        for claim in claims:
            if not claim["strict_hit"]:
                continue
            record = forecasts[claim["prediction_id"]]
            left, right, action = map(int, (record["interval_start"], record["interval_end"], record["hypothetical_action_session"]))
            peak = claim["target_session"]
            assert left <= peak <= right
            assert peak-action >= 5 and left-action >= 5 and right-left+1 <= 10
            assert not claim["duplicate_event"]
            if scope == "stage":
                successful_stage += 1
            else:
                successful_short += 1
denominators = list(rows(V1 / "denominator_checks.csv"))
assert all(r["all_arms_same_E"] == "True" for r in denominators)
result = {"status": "VERIFIED_ARTIFACT_ARITHMETIC_NOT_PREDICTIVE_VALIDATION",
          "manifest_sha256": digest(V1 / "manifest.json"), "verified_output_hashes": len(manifest["outputs"]),
          "input_and_source_hashes_unchanged": True, "daily_rows": len(seen),
          "daily_status_counts": dict(daily_counts), "hypothetical_forecast_rows": len(forecasts),
          "actual_published_rows": 0, "evaluations": evaluation_count,
          "strict_stage_success_records_across_strategies": successful_stage,
          "strict_short_success_records_across_strategies": successful_short,
          "same_denominator_checks": len(denominators), "models_run": 0}
(HERE / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
print(json.dumps(result, ensure_ascii=False))
