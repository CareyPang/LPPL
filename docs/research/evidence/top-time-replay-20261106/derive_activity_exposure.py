"""Derive notification exposure from the sealed daily ledger, without scoring."""
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
V1 = HERE / "v1"
LEDGER = V1 / "daily_replay_ledger.csv.gz"
MANIFEST = V1 / "manifest.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    inputs_before = {str(p.relative_to(HERE)): sha(p) for p in (LEDGER, MANIFEST)}
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert sha(LEDGER) == manifest["outputs"][LEDGER.name]["sha256"]
    dates = defaultdict(set)
    seen = set()
    row_counts, notifications, scheduled, revisions = Counter(), Counter(), Counter(), Counter()
    with gzip.open(LEDGER, "rt", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            key = row["symbol"], row["arm"], row["scope_probe"]
            unique = (*key, row["date"])
            assert unique not in seen, unique
            seen.add(unique)
            dates[row["symbol"]].add(row["date"])
            row_counts[key] += 1
            scheduled[key] += row["scheduled"] == "True"
            notifications[key] += bool(row["new_forecast_id"])
            revisions[key] += row["claim_change"] == "REVISION"
    assets = [{"symbol": symbol, "first_observation": min(days), "last_observation": max(days),
               "observed_days": len(days), "equivalent_asset_years_252": len(days)/252}
              for symbol, days in sorted(dates.items())]
    total_days = sum(a["observed_days"] for a in assets)
    pooled = defaultdict(lambda: {"observed_days": 0, "notifications": 0, "scheduled_scans": 0, "revisions": 0})
    output = []
    for (symbol, arm, scope), count in sorted(row_counts.items()):
        assert count == len(dates[symbol]), (symbol, arm, scope)
        key = symbol, arm, scope
        output.append({"level": "asset", "symbol": symbol, "arm": arm, "scope_probe": scope,
                       "observed_days": count, "equivalent_asset_years_252": count/252,
                       "hypothetical_notifications": notifications[key], "revision_notifications": revisions[key],
                       "scheduled_scans": scheduled[key],
                       "notifications_per_equivalent_asset_year": notifications[key]*252/count})
        group = pooled[(arm, scope)]
        group["observed_days"] += count
        group["notifications"] += notifications[key]
        group["scheduled_scans"] += scheduled[key]
        group["revisions"] += revisions[key]
    for (arm, scope), group in sorted(pooled.items()):
        assert group["observed_days"] == total_days
        output.append({"level": "pooled", "symbol": "ALL_SIX", "arm": arm, "scope_probe": scope,
                       "observed_days": total_days, "equivalent_asset_years_252": total_days/252,
                       "hypothetical_notifications": group["notifications"],
                       "revision_notifications": group["revisions"], "scheduled_scans": group["scheduled_scans"],
                       "notifications_per_equivalent_asset_year": group["notifications"]*252/total_days})
    csv_path = HERE / "activity_exposure.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(output)
    inputs_after = {str(p.relative_to(HERE)): sha(p) for p in (LEDGER, MANIFEST)}
    assert inputs_before == inputs_after
    summary = {"status": "DERIVED_ACTIVITY_CHECK_NO_RESCORE_NO_MODEL",
               "denominator": "one 252-observed-session equivalent asset-year per 252 actual ledger observations; "
                              "not calendar years, official exchange completeness, or historical production uptime",
               "scope": "full replay activity window, including warmup, unavailable and non-scan dates; "
                        "notification numerator includes all published hypothetical records and revisions in that same window",
               "pooling": "sum notifications / sum per-asset observed_days/252; never average asset rates",
               "stage_and_short": "independent probes using identical saved signals; rates per probe, do not add "
                                  "stage and short as actual deliveries",
               "assets": assets, "pooled_observed_days": total_days,
               "pooled_equivalent_asset_years_252": total_days/252,
               "ledger_rows_checked": len(seen), "output_rows": len(output),
               "pooled": [r for r in output if r["level"] == "pooled"],
               "source_hashes_before": inputs_before, "source_hashes_after": inputs_after,
               "sealed_v1_inputs_unchanged": True, "generator_sha256": sha(Path(__file__)),
               "csv_sha256": sha(csv_path)}
    json_path = HERE / "activity_exposure.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
    print(json.dumps({"assets": assets, "pooled": summary["pooled"],
                      "hashes": {p.name: sha(p) for p in (Path(__file__), csv_path, json_path)}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
