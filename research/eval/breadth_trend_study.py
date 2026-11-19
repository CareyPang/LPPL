"""Offline exploratory study of price/breadth warnings. No trading or publishing entry points.

python -m research.eval.breadth_trend_study --rows rows.csv --index index.json --out study/
As archived history is retrospective, even a successful match is never proof of public issuance.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import date
from pathlib import Path
from statistics import mean, median

from research.data.breadth_alerts import classify_phase

TASKS = ("rebound_end", "stage_top", "rebound", "reversal")
PHASES = ("short_rebound", "medium_up", "early_decline", "sustained_decline", "mixed")
MATURITIES = ("early", "middle_late", "unclear")
TOP_WINDOW = {"rebound_end": 5, "stage_top": 10}
PEAK_RIGHT = {"rebound_end": 5, "stage_top": 20}
PREFERRED = {
    "rebound_end": {"short_rebound"},
    "stage_top": {"medium_up"},
    "rebound": {"early_decline", "sustained_decline"},
    "reversal": {"sustained_decline"},
}
PRODUCTS = ("IF", "IH", "IC", "IM")
CONTRACT_PAIRS = tuple(
    (layer, f"{layer}_{product.lower()}") for layer in ("amount", "shares") for product in PRODUCTS
)
LAYERS = ("stage", "breadth", "amount", "shares", "amount_basis", "shares_basis") + tuple(
    added for _, added in CONTRACT_PAIRS
)
# Pair supports are separate. Within one pair, task and stage, BOTH methods see the same dates.
PAIRS = (
    ("stage", "breadth"),
    ("breadth", "amount"),
    ("breadth", "shares"),
    ("amount", "shares"),
    ("amount", "amount_basis"),
    ("shares", "shares_basis"),
) + CONTRACT_PAIRS
BUDGET = 4


def number(value):
    if value is None or value == "":
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def dated(value):
    return date.fromisoformat(value).isoformat()


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_panel(source, index_file, contracts=None, asof=None):
    """Retain all index trading sessions. A missing breadth observation stays missing."""
    if source.suffix.lower() == ".json":
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
        source_rows = list(payload["history"])
        latest = payload["latest"]
        source_rows = [dict(r, **latest) if r["date"] == latest["date"] else r for r in source_rows]
        if latest["date"] not in {r["date"] for r in source_rows}:
            source_rows.append(latest)
    else:
        with source.open(encoding="utf-8-sig", newline="") as src:
            source_rows = list(csv.DictReader(src))
    points = {}
    for r in source_rows:
        day = dated(r["date"])
        if day in points:
            raise ValueError(f"duplicate breadth date {day}")
        point = {
            k: number(r.get(k))
            for k in (
                "sh",
                "red",
                "P20",
                "P60",
                "P250",
                "MCL",
                "trin_amt",
                "trin_vol",
                "amount_ratio20",
            )
        }
        point["basis"] = r.get("basis") or json.loads(r.get("basis_json") or "{}")
        points[day] = point
    if not points:
        raise ValueError("empty breadth source")
    if contracts:
        with contracts.open(encoding="utf-8-sig", newline="") as file:
            seen = set()
            for r in csv.DictReader(file):
                d, prod = dated(r["date"]), r["product"]
                if (d, prod) in seen:
                    raise ValueError(f"duplicate external contract {d} {prod}")
                seen.add((d, prod))
                spot, close = number(r["spot_close"]), number(r["futures_close"])
                if d in points and spot and spot > 0 and close and close > 0:
                    points[d]["basis"].setdefault(
                        prod, {"symbol": r["symbol"], "pct": 100 * (close / spot - 1)}
                    )
    raw = json.loads(index_file.read_text(encoding="utf-8-sig"))["price_history"]
    dates = list(map(dated, raw["dates"]))
    closes = raw["close"]
    if dates != sorted(set(dates)) or len(closes) != len(dates):
        raise ValueError("index sessions must be unique, ordered and aligned")
    end = min(dates[-1], max(points), dated(asof) if asof else dates[-1])
    sessions = set(dates)
    if any(d <= end and d >= dates[0] and d not in sessions for d in points):
        raise ValueError("breadth observation without index session")
    rows = []
    for d, px in zip(dates, closes, strict=True):
        if d > end:
            break
        if number(px) is None or float(px) <= 0:
            raise ValueError(f"invalid index price {d}")
        r = dict(points.get(d, {}))
        # Both archives may carry different rounding. Use the historical breadth index quote
        # for phase/alerts, the fixed close series for prices used in independent labels.
        r.update(date=d, sh=r.get("sh") or float(px), label_close=float(px))
        rows.append(r)
    if not rows:
        raise ValueError("no index sessions before cutoff")
    return rows


def contract_change(prev, cur, product):
    a = prev.get("basis", {}).get(product, {})
    b = cur.get("basis", {}).get(product, {})
    if not a.get("symbol") or a["symbol"] != b.get("symbol"):
        return None
    old, new = number(a.get("pct")), number(b.get("pct"))
    return None if old is None or new is None else new - old


def basis_move(prev, cur):
    """Equal-weight, unannualized changes (percentage points), full 4-product, no rolls."""
    changes = [contract_change(prev, cur, prod) for prod in PRODUCTS]
    return mean(changes) if all(v is not None for v in changes) else None


def signals(task, phase, prev, cur):
    """Hypotheses specified for the study, independent of public UI alert lifecycle.

    Every available layer uses the same threshold: at least half its evidence
    families agree. Correlated breadth readings give ONE family vote. Both TRIN
    variants use the same relative market turnover (currency amount) control.
    """
    favored = phase in PREFERRED[task]
    result = dict.fromkeys(LAYERS)
    result["stage"] = favored
    fields = ("red", "P20", "P60", "P250", "MCL")
    if any(prev.get(k) is None or cur.get(k) is None for k in fields):
        return result
    top = task in TOP_WINDOW
    if top:
        breadth = (
            cur["red"] < prev["red"]
            and cur["MCL"] < prev["MCL"]
            and (cur["P20"] < prev["P20"] or cur["P60"] < prev["P60"])
        )
    elif task == "rebound":
        breadth = cur["red"] < 0.5 and cur["P20"] < 0.5 and cur["P60"] < 0.5
    else:
        breadth = (
            cur["red"] > 0.5
            and cur["P20"] > prev["P20"]
            and (cur["P60"] > prev["P60"] or cur["P250"] > prev["P250"])
        )
    # The second version uses phase OR breadth; a research watch can originate in any phase.
    result["breadth"] = favored or breadth
    total = cur.get("amount_ratio20")
    moves = {prod.lower(): contract_change(prev, cur, prod) for prod in PRODUCTS}
    moves["basis"] = basis_move(prev, cur)
    for layer, key in (("amount", "trin_amt"), ("shares", "trin_vol")):
        ratio = cur.get(key)
        if ratio is None or total is None:
            continue
        if top:
            flow = cur["red"] > 0.5 and ratio > 1 and total >= 1
        elif task == "rebound":
            flow = cur["red"] < 0.5 and ratio < 1 and total <= 1
        else:
            flow = cur["red"] > 0.5 and ratio <= 1 and total >= 1
        votes = int(favored) + int(breadth) + int(flow)
        result[layer] = votes >= 2
        for product, move in moves.items():
            if move is not None:
                confirms = move < 0 if top else move > 0
                result[f"{layer}_{product}"] = votes + int(confirms) >= 2
    return result


def feature_days(rows, start=None):
    prior = []
    daily = []
    unavailable = 0
    for i, row in enumerate(rows):
        if row.get("red") is not None and (not start or row["date"] >= start):
            details = classify_phase(prior)
            phase = details["id"]
            if phase in PHASES and i:
                daily.append(
                    (
                        i,
                        phase,
                        details["maturity"],
                        {t: signals(t, phase, rows[i - 1], row) for t in TASKS},
                    )
                )
            else:
                unavailable += 1
        prior.append(row)
    return daily, unavailable


def top_dates(prices, task):
    """Later, fully matured labels. No percentage drawdown filter. First maximum wins ties."""
    left = 20 if task == "rebound_end" else 126
    right = PEAK_RIGHT[task]
    peaks = set()
    for i in range(left, len(prices) - right):
        value = prices[i]
        if value <= max(prices[i - right : i]) or value < max(prices[i + 1 : i + right + 1]):
            continue
        start = i - left
        leg = prices[start:i]
        # Choose the LAST occurrence of the lowest close as the leg's start.
        minimum = min(leg)
        low_idx = start + max(j for j, x in enumerate(leg) if x == minimum)
        age = i - low_idx
        if task == "stage_top":
            if age >= 20 and value > prices[i - 20]:
                peaks.add(i)
        elif age >= 3 and low_idx >= 5 and prices[low_idx] < prices[low_idx - 5]:
            peaks.add(i)
    return peaks


def eligible_peaks(dates, peaks, window, right, n):
    left = 126 if right == PEAK_RIGHT["stage_top"] else 20
    mature = [i for i in dates if i >= left and i + window - 1 + right < n]
    return {e for e in peaks if any(i <= e < i + window for i in mature)}, mature


def match_peaks(alerts, peaks, width):
    """Earliest issued alert claims the first unmatched covered event; one-to-one."""
    hits = {}
    remaining = set(peaks)
    for i in sorted(alerts):
        candidates = [e for e in remaining if i <= e < i + width]
        if candidates:
            event = min(candidates)
            hits[i] = event
            remaining.remove(event)
    return hits


def followup(rows, i, task):
    p = [r["label_close"] for r in rows]
    if task == "rebound":
        item = {f"ret{h}": p[i + h] / p[i] - 1 if i + h < len(p) else None for h in (1, 5, 10)}
        future = p[i + 1 : i + 11]
        item["best_close_ret10"] = max(future) / p[i] - 1 if len(future) == 10 else None
        item["worst_close_ret10"] = min(future) / p[i] - 1 if len(future) == 10 else None
        return item
    if i < 19 or i + 20 >= len(rows):
        return {"status": "immature"}
    future = p[i + 1 : i + 21]
    floor = min(p[i - 19 : i + 1])
    # An interior local trough after an upswing (peak above signal close), followed
    # by a recovery, is an observable retest. A drop on day one alone is insufficient.
    retests = [
        j
        for j in range(2, len(future) - 2)
        if max(future[:j]) > p[i]
        and max(future[:j]) > future[j]
        and min(future[j - 2 : j]) > future[j]
        and min(future[j + 1 : j + 3]) >= future[j]
        and max(future[j + 1 : j + 3]) > future[j]
    ]
    base_breadth = rows[i].get("P60")
    last_five = [r.get("P60") for r in rows[i + 16 : i + 21]]
    if base_breadth is None or any(v is None for v in last_five):
        return {"status": "missing_followup_breadth"}
    held = min(future) >= floor
    higher = any(future[j] > floor for j in retests)
    improved = sum(v > base_breadth for v in last_five) >= 3
    return {
        "status": "mature",
        "held": held,
        "had_retest": bool(retests),
        "higher_low": higher,
        "breadth_improved": improved,
        "reversal": held and higher and improved and future[-1] > p[i],
    }


def comparable_outcome(rows, i, task):
    if task in TOP_WINDOW:
        left = 20 if task == "rebound_end" else 126
        return i >= left and i + TOP_WINDOW[task] - 1 + PEAK_RIGHT[task] < len(rows)
    if task == "rebound":
        return i + 10 < len(rows)
    return followup(rows, i, task)["status"] == "mature"


def select_pairs(opportunities, methods, budget=BUDGET):
    """One ticket per method per block of K encounters in the same phase.

    Online policy: first true criterion, else the last slot. Never pick an ex-post max.
    Incomplete block tickets stay in the ledger and do not enter the equal-count table.
    """
    selected = {m: [] for m in methods}
    for offset in range(0, len(opportunities), budget):
        block = opportunities[offset : offset + budget]
        for method in methods:
            first = next((i for i, rules in block if rules[method]), None)
            if first is not None or len(block) == budget:
                selected[method].append(
                    (
                        first if first is not None else block[-1][0],
                        first is None,
                        len(block) == budget,
                    )
                )
    return selected


def score(rows, task, chosen, opportunities, peaks, outcomes, info):
    stats = {}
    if task in TOP_WINDOW:
        width, right = TOP_WINDOW[task], PEAK_RIGHT[task]
        possible, mature = eligible_peaks(opportunities, peaks[task], width, right, len(rows))
        picked = [i for i in chosen if i in mature]
        hits = match_peaks(picked, possible, width)
        leads = [event - t for t, event in hits.items()]
        stats.update(
            opportunity_peaks=len(possible),
            mature_alerts=len(picked),
            hits=len(hits),
            missed=len(possible) - len(hits),
            false_alerts=len(picked) - len(hits),
            immature_alerts=len(chosen) - len(picked),
            lead_ge5=sum(n >= 5 for n in leads),
            median_lead=median(leads) if leads else None,
        )
        for i in chosen:
            event = hits.get(i)
            outcomes.append(
                dict(
                    info,
                    date=rows[i]["date"],
                    status=(
                        "immature"
                        if i not in mature
                        else "hit"
                        if event is not None
                        else "missed_window"
                    ),
                    peak=rows[event]["date"] if event is not None else None,
                    lead=event - i if event is not None else None,
                    window_end=rows[i + width - 1]["date"] if i + width - 1 < len(rows) else None,
                )
            )
    else:
        labels = [followup(rows, i, task) for i in chosen]
        for i, label in zip(chosen, labels, strict=True):
            outcomes.append(dict(info, date=rows[i]["date"], **label))
        if task == "rebound":
            for k in ("ret1", "ret5", "ret10", "best_close_ret10", "worst_close_ret10"):
                values = [v[k] for v in labels if v[k] is not None]
                stats[k + "_n"] = len(values)
                stats[k + "_mean"] = mean(values) if values else None
                if k in ("ret1", "ret5", "ret10"):
                    stats[k + "_positive"] = sum(v > 0 for v in values)
        else:
            complete = [r for r in labels if r["status"] == "mature"]
            stats.update(
                mature_alerts=len(complete),
                immature_alerts=sum(r["status"] == "immature" for r in labels),
                missing_followup=sum(r["status"] == "missing_followup_breadth" for r in labels),
            )
            for key in ("held", "had_retest", "higher_low", "breadth_improved", "reversal"):
                stats[key] = sum(r[key] for r in complete)
    return stats


def study(rows, start=None):
    daily, unavailable = feature_days(rows, start)
    prices = [r["label_close"] for r in rows]
    peaks = {task: top_dates(prices, task) for task in TOP_WINDOW}
    alerts, outcomes, comparisons = [], [], []
    # Natural signals are rising edges; an unobserved gap cannot count as a fresh edge.
    for task in TASKS:
        known = {i for i, _, _, _ in daily if comparable_outcome(rows, i, task)}
        for layer in LAYERS:
            previous, prev_i = None, None
            for i, phase, maturity, tests in daily:
                cond = tests[task][layer]
                if cond is True and prev_i == i - 1 and previous is False:
                    alerts.append(
                        dict(
                            mode="natural",
                            task=task,
                            phase=phase,
                            layer=layer,
                            maturity=maturity,
                            pair="",
                            date=rows[i]["date"],
                            forced=False,
                            complete=None,
                        )
                    )
                previous, prev_i = cond, i
        strata = [(phase, mat) for phase in PHASES for mat in MATURITIES]
        for phase, maturity in strata:
            items = [
                (i, tests[task]) for i, p, mat, tests in daily if (p, mat) == (phase, maturity)
            ]
            for left, right in PAIRS:
                pair = left + "_vs_" + right
                methods = (left, right)
                common = [
                    (i, rules) for i, rules in items if all(rules[m] is not None for m in methods)
                ]
                selected = select_pairs(common, methods)
                grouped = [i for i, _ in common[: (len(common) // BUDGET) * BUDGET]]
                # A pair only scores after EVERY possible issue date in its block
                # has equally complete outcomes. This cannot change either issue date.
                scoreable = set()
                for offset in range(0, len(grouped), BUDGET):
                    block = grouped[offset : offset + BUDGET]
                    if known.issuperset(block):
                        scoreable.update(block)
                for method, tickets in selected.items():
                    info = dict(task=task, phase=phase, maturity=maturity, pair=pair, layer=method)
                    for i, forced, complete in tickets:
                        alerts.append(
                            dict(
                                info,
                                mode="equal_budget",
                                date=rows[i]["date"],
                                forced=forced,
                                complete=complete,
                                paired_followup=i in scoreable,
                            )
                        )
                    chosen = [i for i, _, _ in tickets if i in scoreable]
                    stats = score(rows, task, chosen, sorted(scoreable), peaks, outcomes, info)
                    comparisons.append(
                        dict(
                            info,
                            phase_days=len(items),
                            common_days=len(common),
                            completed_blocks=len(grouped) // BUDGET,
                            quota_alerts=len(grouped) // BUDGET,
                            forced=sum(f and c for _, f, c in tickets),
                            paired_scored_alerts=len(chosen),
                            paired_forced=sum(f for i, f, _ in tickets if i in scoreable),
                            status=(
                                "scored"
                                if chosen
                                else "awaiting_common_outcomes"
                                if grouped
                                else "insufficient_common_days"
                            ),
                            **stats,
                        )
                    )
    # Unrestricted truth counts keep right-censoring and gaps visible, even if a method
    # had no complete blocks. Per-phase opportunity denominators must never be summed.
    first = next((entry[0] for entry in daily), None)
    source_first = next((i for i, r in enumerate(rows)
                         if r.get("red") is not None and (not start or r["date"] >= start)), None)
    dates = range(source_first, len(rows)) if source_first is not None else []
    targets = {}
    for task, width in TOP_WINDOW.items():
        possible, _ = eligible_peaks(dates, peaks[task], width, PEAK_RIGHT[task], len(rows))
        targets[task] = [rows[i]["date"] for i in sorted(possible)]
    natural = {}
    natural_by_phase = []
    for task in TASKS:
        natural[task] = {}
        for method in LAYERS:
            eligible = [i for i, _, _, tests in daily if tests[task][method] is not None]
            issued = {
                a["date"]
                for a in alerts
                if a["task"] == task and a["mode"] == "natural" and a["layer"] == method
            }
            selected = [i for i in eligible if rows[i]["date"] in issued]
            info = dict(task=task, phase="all", maturity="all", pair="natural", layer=method)
            stats = score(rows, task, selected, list(dates), peaks, outcomes, info)
            natural[task][method] = dict(input_days=len(eligible), alerts=len(selected), **stats)
            for phase, maturity in sorted({(p, m) for _, p, m, _ in daily}):
                dates_in_group = [i for i, p, m, _ in daily if (p, m) == (phase, maturity)]
                chosen = [i for i in selected if i in dates_in_group]
                group = dict(info, phase=phase, maturity=maturity)
                stats = score(rows, task, chosen, dates_in_group, peaks, [], group)
                natural_by_phase.append(
                    dict(
                        group,
                        phase_days=len(dates_in_group),
                        input_days=len(set(eligible) & set(dates_in_group)),
                        alerts=len(chosen),
                        **stats,
                    )
                )
    return (
        dict(
            schema="breadth-trend-study.v1",
            evidence="exploratory_retrospective_replay",
            scoring_first_date=rows[source_first]["date"] if source_first is not None else None,
            outcome_definitions={
                "rebound_end":"20-session start search; at least 3 sessions up from a low after weakness; "
                              "peak beats its prior 5 closes and is unbeaten over the next 5",
                "stage_top":"peak beats its prior 20 closes and is unbeaten over the next 20; "
                            "the most recent 126-session low is at least 20 sessions earlier; "
                            "close above 20 sessions ago; no subsequent drawdown target",
                "rebound":"1/5/10-session forward close returns; best and worst forward closes over 10",
                "reversal":"20-session hold above prior 20-session low, higher retest low after an upswing, "
                           "ending above signal close and P60 above signal-day level on >=3 of last 5 days",
            },
            budget_rule="First qualifying day in four same-phase, same-maturity common observations "
                        "or a forced fourth ticket; score completed blocks only after every candidate "
                        "has a mature outcome. Retrospective coverage, not a probability.",
            trigger_rule="Natural alerts require false -> true on adjacent observed trading sessions; "
                         "amount and shares vary TRIN only and use the same total currency turnover control.",
            first_feature_date=rows[first]["date"] if first is not None else None,
            last_date=rows[-1]["date"],
            sessions_with_phase_and_breadth=len(daily),
            breadth_days_without_known_phase=unavailable,
            phase_maturity_days={
                p: {m: sum(s == p and a == m for _, s, a, _ in daily) for m in MATURITIES}
                for p in PHASES
            },
            phase_days={p: sum(s == p for _, s, _, _ in daily) for p in PHASES},
            natural_by_phase=natural_by_phase,
            observable_price_peak_dates=targets,
            natural=natural,
            equal_budget_opportunities=BUDGET,
            layers=list(LAYERS),
            same_contract_days={
                prod: sum(
                    contract_change(rows[i - 1], rows[i], prod) is not None for i, _, _, _ in daily
                )
                for prod in PRODUCTS
            },
            basis_products=list(PRODUCTS),
        ),
        comparisons,
        alerts,
        outcomes,
    )


def write_csv(path, records, base):
    fields = list(dict.fromkeys(list(base) + [k for r in records for k in r]))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rows", required=True, type=Path, help="normalized breadth cache CSV or published JSON"
    )
    parser.add_argument("--index", required=True, type=Path, help="index JSON with price_history")
    parser.add_argument("--contracts", type=Path, help="optional historic individual contracts CSV")
    parser.add_argument("--asof", type=dated, help="last observation day, also clips all outcomes")
    parser.add_argument("--start", type=dated, help="first signal day; earlier rows remain warm-up")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    rows = read_panel(args.rows, args.index, args.contracts, args.asof)
    summary, comparisons, alerts, outcomes = study(rows, args.start)
    sources = [args.rows, args.index] + ([args.contracts] if args.contracts else [])
    summary["inputs"] = [{"name": p.name, "sha256": fingerprint(p)} for p in sources]
    summary["requested_start"] = args.start
    summary["requested_asof"] = args.asof
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    write_csv(args.out / "comparisons.csv", comparisons, ("task", "phase", "pair", "layer"))
    write_csv(args.out / "alerts.csv", alerts, ("mode", "date", "task", "phase", "layer"))
    write_csv(args.out / "outcomes.csv", outcomes, ("date", "task", "phase", "layer", "pair"))


if __name__ == "__main__":
    main()
