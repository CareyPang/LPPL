"""Pre-registered event study for the CITIC seat / basis states (docs/preregistration_nt_futures_signal.md)."""
from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path

SEED = 20261128
SHIFTS = 2000
DEDUP = 20
HORIZONS = (5, 20, 60)
FIRST, LAST = "2015-04-17", "2026-08-28"
PERIODS = (("2015–2018", "2015", "2019"), ("2019–2022", "2019", "2023"), ("2023–2026", "2023", "2027"))
PRODUCTS = ("IF", "IH", "IC", "IM")


def states(panel: dict) -> tuple[list[str], list[float], dict[str, list[bool]]]:
    days = sorted(panel)
    close = [panel[d]["IF"]["spot"] for d in days]
    seat = [panel[d]["IF"]["cl"] + panel[d]["IH"]["cl"] for d in days]
    basis = [panel[d]["IC"]["basis"] for d in days]
    net = [sum(panel[d][p]["ts"] - panel[d][p]["tl"] for p in PRODUCTS if "ts" in panel[d][p]) for d in days]
    n = len(days)
    r1 = [i > 0 and seat[i] - seat[i - 1] >= 5000 for i in range(n)]
    r2 = [i > 0 and basis[i - 1] < 0 < basis[i] for i in range(n)]
    r3 = [i > 0 and net[i] < net[i - 1] for i in range(n)]
    r4 = [i > 0 and close[i] / close[i - 1] - 1 >= 0.02 for i in range(n)]
    x1 = [i > 0 and seat[i] - seat[i - 1] <= -5000 for i in range(n)]
    events = {
        "E1": r1,
        "E2": r2,
        "E3": [a and b for a, b in zip(r1, r2, strict=True)],
        "E4": [a and b and c and d for a, b, c, d in zip(r1, r2, r3, r4, strict=True)],
        "E5": [a and not c for a, c in zip(r1, r3, strict=True)],
        "E6": x1,
    }
    return days, close, events


def dedup(flags: list[bool], lo: int, hi: int) -> list[int]:
    picked, last = [], -10**9
    for i in range(lo, hi + 1):
        if flags[i] and i - last > DEDUP:
            picked.append(i)
            last = i
    return picked


def forward(close: list[float], i: int, h: int) -> float:
    return close[i + h] / close[i] - 1


def summarize(close: list[float], idx: list[int]) -> dict:
    out: dict = {"n": len(idx)}
    for h in HORIZONS:
        values = [forward(close, i, h) for i in idx]
        out[f"median_{h}"] = statistics.median(values) if values else None
        out[f"mean_{h}"] = statistics.fmean(values) if values else None
        out[f"up_{h}"] = sum(v > 0 for v in values) / len(values) if values else None
    drawdowns = [min(close[i + 1:i + 21]) / close[i] - 1 for i in idx]
    out["median_drawdown_20"] = statistics.median(drawdowns) if drawdowns else None
    return out


def run(panel: dict) -> dict:
    days, close, events = states(panel)
    # the registered last day left fewer than 60 sessions; the registered intent is a complete 60-day window
    lo, hi = days.index(FIRST), min(days.index(LAST), len(days) - 1 - max(HORIZONS))
    span = hi - lo + 1
    base = summarize(close, list(range(lo, hi + 1)))
    rng = random.Random(SEED)
    shifts = [rng.randrange(1, span) for _ in range(SHIFTS)]
    result = {"first": FIRST, "last": days[hi], "days": span, "baseline": base, "events": {}}
    for name, flags in events.items():
        idx = dedup(flags, lo, hi)
        stats = summarize(close, idx)
        stats["dates"] = [days[i] for i in idx]
        diff = stats["mean_20"] - base["mean_20"] if idx else None
        stats["diff_20"] = diff
        if idx:
            window = flags[lo:hi + 1]
            extreme = 0
            for shift in shifts:
                moved = [False] * lo + window[-shift:] + window[:-shift]
                sample = dedup(moved, lo, hi)
                value = statistics.fmean(forward(close, i, 20) for i in sample) - base["mean_20"]
                extreme += abs(value) >= abs(diff)
            stats["p_two_sided"] = extreme / SHIFTS
        else:
            stats["p_two_sided"] = None
        stats["periods"] = {}
        for label, start, end in PERIODS:
            part = [i for i in idx if start <= days[i] < end]
            everyday = [i for i in range(lo, hi + 1) if start <= days[i] < end]
            mean = statistics.fmean(forward(close, i, 20) for i in part) if part else None
            ref = statistics.fmean(forward(close, i, 20) for i in everyday)
            stats["periods"][label] = {"n": len(part), "mean_20": mean, "baseline_20": ref,
                                       "diff_20": mean - ref if part else None}
        later = [stats["periods"][label] for label, _, _ in PERIODS[1:]]
        stats["passed"] = bool(
            len(idx) >= 15
            and stats["p_two_sided"] < 0.05 / len(events)
            and all(p["n"] >= 5 for p in later)
            and len({p["diff_20"] > 0 for p in later}) == 1
        )
        result["events"][name] = stats
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run(json.loads(args.panel.read_text(encoding="utf-8")))
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
