"""Score the first watch actually emitted by the market panel in an historical replay."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from research.data.breadth_alerts import RULE_VERSION, build_trend_ledger
from research.eval.breadth_trend_study import (
    PEAK_RIGHT,
    TASKS,
    TOP_WINDOW,
    dated,
    fingerprint,
    read_panel,
    score,
    top_dates,
)


def replay(rows):
    ledger = build_trend_ledger(rows, evidence="research_replay")
    start = next((i for i, day in enumerate(ledger) if day["state"] != "unavailable"), len(rows))
    prices = [row["label_close"] for row in rows]
    peaks = {task: top_dates(prices, task) for task in TOP_WINDOW}
    issued = {kind: [] for kind in TASKS}
    changes = []
    seen = set()
    for i, day in enumerate(ledger):
        for alert in day["alerts"]:
            if alert["update_date"] != day["asof"]:
                continue
            changes.append({
                "asof": day["asof"], "phase": day["phase"]["id"],
                "maturity": day["phase"]["maturity"], "id": alert["id"],
                "kind": alert["kind"], "level": alert["level"], "title": alert["title"],
                "trigger_date": alert["trigger_date"], "message": alert["message"],
                "reasons": alert["reasons"], "next_check": alert["next_check"],
            })
            if alert["level"] == "watch" and alert["trigger_date"] == day["asof"]:
                if alert["id"] in seen:
                    raise ValueError(f"multiple first watches for {alert['id']}")
                seen.add(alert["id"])
                issued[alert["kind"]].append(i)
    outcomes = []
    tasks = {}
    # Keep every eligible price peak after warm-up in the denominator, including quiet days.
    opportunities = list(range(start, len(rows)))
    for task, selected in issued.items():
        stats = score(rows, task, selected, opportunities, peaks, outcomes, {"task": task})
        tasks[task] = {"first_watches": len(selected), **stats}
    phase_days = Counter(day["phase"]["id"] for day in ledger[start:])
    mature_days = Counter(day["phase"]["maturity"] for day in ledger[start:])
    return {
        "rule_version": RULE_VERSION, "mode": "research_replay",
        "first_publication_at": None,
        "first_evaluable": rows[start]["date"] if start < len(rows) else None,
        "cutoff": rows[-1]["date"], "evaluable_sessions": sum(
            day["state"] != "unavailable" for day in ledger[start:]
        ), "phase_days": dict(phase_days), "maturity_days": dict(mature_days),
        "top_window_sessions": TOP_WINDOW, "top_right_confirmation_sessions": PEAK_RIGHT,
        "tasks": tasks, "latest": ledger[-1],
    }, changes, outcomes


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--rows", type=Path, required=True)
    cli.add_argument("--index", type=Path, required=True)
    cli.add_argument("--contracts", type=Path)
    cli.add_argument("--asof", type=dated, required=True)
    cli.add_argument("--out", type=Path, required=True)
    args = cli.parse_args()
    rows = read_panel(args.rows, args.index, args.contracts, args.asof)
    summary, changes, outcomes = replay(rows)
    sources = [args.rows, args.index] + ([args.contracts] if args.contracts else [])
    summary["inputs"] = [{"name": f.name, "sha256": fingerprint(f)} for f in sources]
    args.out.mkdir(parents=True, exist_ok=True)
    for name, value in (("panel_summary", summary), ("panel_changes", changes), ("panel_outcomes", outcomes)):
        (args.out / f"{name}.json").write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
