"""Replay the frozen 14-alert Shanghai stage-top sample on ETF 510210.

The command 'freeze' projects the original archive, including its scoring calendar.
Only dated state changes enter the trading schedules; outcome labels are joined afterwards.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from research.backtest.stage_etf import simulate
from research.data.stage_etf_quote_sample import CSV_SHA256
from research.eval.breadth_trend_study import PEAK_RIGHT, TOP_WINDOW, eligible_peaks, top_dates

REPORT = Path("reports/stage_etf_20261118")
OUTCOMES = Path("reports/breadth_trend_20261118/panel_v2_outcomes.json")
START = "2025-11-28"
END = "2026-11-18"
CAPITAL = 1_000_000
RATE = 0.00025
MIN_FEE = 5
TASK = "stage_top"
CHANGE_HASH = "808b722606d9354bc86e00155972690b0609ec0ef1a694c8d199c856da1b3d1a"
INDEX_HASH = "55f3547596f790c1a9fa1e36e0270e7b27c6bde1344673e178cf3ac6b5448430"


def verify_inputs(bars, frozen):
    if hashlib.sha256(bars.read_bytes()).hexdigest() != CSV_SHA256:
        raise ValueError("expected exact 236-row frozen ETF quote sample")
    manifests = {
        frozen
        / "frozen_events.csv": "33f18055e6b9e2a7b1b5140862716a272d50d89efef215351a7fae2bd068f9c5",
        frozen
        / "scoring_calendar.csv": "8803ea4fc805ea490633ee66a531014b10b75f6069b67879793d16074a43afa8",
        OUTCOMES: "4a3bbf7f31c0b1ad0a8f9f3edd4f49f205cd6e5af345785d123c50af23abe6b8",
    }
    for path, expected in manifests.items():
        data = path.read_text(encoding="utf-8-sig").encode("utf-8")
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"frozen research input mismatch: {path}")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def freeze(changes, index, output):
    for path, digest in ((changes, CHANGE_HASH), (index, INDEX_HASH)):
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"unexpected / non-original source bytes: {path}")
    raw = read_json(index)["price_history"]
    days = raw["dates"]
    if days != sorted(set(days)) or days[-1] != END:
        raise ValueError("unexpected index calendar")
    width, right = TOP_WINDOW[TASK], PEAK_RIGHT[TASK]
    peaks, _ = eligible_peaks(
        range(days.index(START), len(days)), top_dates(raw["close"], TASK), width, right, len(days)
    )
    events = [
        {
            "date": r["asof"],
            "episode_id": r["id"],
            "trigger": r["trigger_date"],
            "level": r["level"],
        }
        for r in read_json(changes)
        if r["kind"] == TASK
    ]
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "frozen_events.csv", events)
    write_csv(
        output / "scoring_calendar.csv",
        [
            {"date": day, "evaluable_peak": int(i in peaks)}
            for i, day in enumerate(days)
            if START <= day <= END
        ],
    )


def action_schedule(days, events, delay):
    """A release is actionable at that close plus delay sessions; a new watch cancels it."""
    by_day = defaultdict(list)
    for event in events:
        by_day[event["date"]].append(event)
    if set(by_day) - set(days) or delay < 0:
        raise ValueError("invalid event date or lag")
    actions, pending, active = [], None, set()
    for i, day in enumerate(days):
        rows = by_day[day]
        for row in rows:
            if row["level"] == "invalidated":
                active.remove(row["episode_id"])
                pending = (i + delay, row) if not active else None
        for row in rows:
            if row["level"] == "watch":
                if row["episode_id"] in active:
                    raise ValueError("duplicate watch")
                active.add(row["episode_id"])
                pending = None
                actions.append(
                    {"date": day, "reason": "watch", "episode_id": row["episode_id"], "target": 0.5}
                )
            elif row["level"] not in {"strengthening", "invalidated"}:
                raise ValueError(f"unknown level: {row['level']}")
        if pending and i == pending[0]:
            actions.append(
                {
                    "date": day,
                    "reason": "release",
                    "episode_id": pending[1]["episode_id"],
                    "target": 1,
                }
            )
            pending = None
    return actions


def drawdown(daily):
    peak = daily[0]
    worst, start, end = 0.0, peak["date"], peak["date"]
    for row in daily:
        if row["nav"] > peak["nav"]:
            peak = row
        loss = 1 - row["nav"] / peak["nav"]
        if loss > worst:
            worst, start, end = loss, peak["date"], row["date"]
    return round(100 * worst, 6), start, end


def stats(result):
    daily = result["daily"]
    last = daily[-1]
    mdd, peak_day, low_day = drawdown(daily)
    return {
        "end_nav": last["nav"],
        "return_pct": round((last["nav"] / CAPITAL - 1) * 100, 6),
        "fees": last["fees"],
        "fills": len(result["trades"]),
        "close_days_below_75pct": sum(row["position_weight"] < 0.75 for row in daily),
        "max_close_drawdown_pct": mdd,
        "drawdown_start": peak_day,
        "drawdown_end": low_day,
    }


def episode_rows(result, events, scores, bars, peaks):
    marks = {row["date"]: row for row in bars}
    by_id, changes = defaultdict(dict), defaultdict(dict)
    for fill in result["trades"]:
        if fill["episode_id"]:
            by_id[fill["episode_id"]][fill["side"]] = fill
    for row in events:
        changes[row["episode_id"]][row["level"]] = row["date"]
    rows = []
    for key, state in changes.items():
        sell, buy = by_id[key]["sell"], by_id[key]["buy"]
        if not sell["date"] < buy["date"]:
            raise ValueError("expected a completed round trip")
        label = scores[state["watch"]]
        forgone_move = round(sell["shares"] * (buy["price"] - sell["price"]), 2)
        fees = round(buy["fee"] + sell["fee"], 2)
        highs = [float(v["high"]) for d, v in marks.items() if sell["date"] <= d < buy["date"]]
        max_rise = max(0, max([buy["price"], *highs]) - sell["price"])
        terminal = float(bars[-1]["close"])
        remaining_pnl = round((buy["shares"] - sell["shares"]) * (terminal - buy["price"]), 2)
        rows.append(
            {
                "episode_id": key,
                "watch": state["watch"],
                "strengthening": state.get("strengthening"),
                "release": state["invalidated"],
                "window_end": label["window_end"],
                "score": label["status"],
                "credited_peak": label["peak"],
                "lead": label["lead"],
                "peaks_in_original_window": "|".join(
                    d for d in peaks if state["watch"] <= d <= label["window_end"]
                ),
                "sell_date": sell["date"],
                "sell_price": sell["price"],
                "sold": sell["shares"],
                "sell_fee": sell["fee"],
                "after_sell_shares": sell["shares_after"],
                "buy_date": buy["date"],
                "buy_price": buy["price"],
                "bought": buy["shares"],
                "buy_fee": buy["fee"],
                "after_buy_shares": buy["shares_after"],
                "gross_forgone_cny": forgone_move,
                "round_trip_fees": fees,
                "net_cost_cny": round(forgone_move + fees, 2),
                "later_share_pnl_cny": remaining_pnl,
                "terminal_contribution_cny": round(-forgone_move - fees + remaining_pnl, 2),
                "largest_interim_forgone_cny": round(max_rise * sell["shares"], 2),
            }
        )
    return rows


def peak_rows(paths, peaks, scores):
    lookup = {score["peak"]: score for score in scores.values() if score["peak"]}
    output = []
    for peak in peaks:
        label = lookup.get(peak, {})
        for name, result in paths.items():
            daily = result["daily"]
            idx = next(i for i, r in enumerate(daily) if r["date"] == peak)
            window = daily[idx : idx + 21]
            if len(window) != 21:
                raise ValueError("incomplete post-peak scoring window")
            start, low = window[0], min(window, key=lambda row: row["nav"])
            cost = round(start["nav"] - low["nav"], 2)
            output.append(
                {
                    "peak": peak,
                    "credited_watch": label.get("date"),
                    "lead": label.get("lead"),
                    "path": name,
                    "shares": start["shares"],
                    "open_weight_pct": round(start["open_weight"] * 100, 6),
                    "close_weight_pct": round(start["position_weight"] * 100, 6),
                    "peak_nav": start["nav"],
                    "window_end": window[-1]["date"],
                    "min_nav_date": low["date"],
                    "min_nav": low["nav"],
                    "peak_to_min_loss_pct": round(100 * cost / start["nav"], 6),
                    "peak_to_min_loss_cny": cost,
                }
            )
    return output


def run(bars_path, corporate_path, frozen, output):
    verify_inputs(bars_path, frozen)
    calendar = read_csv(frozen / "scoring_calendar.csv")
    events = read_csv(frozen / "frozen_events.csv")
    bars = [
        {**r, "volume": r["volume_lots"]} for r in read_csv(bars_path) if START <= r["date"] <= END
    ]
    days = [r["date"] for r in bars]
    if days != [r["date"] for r in calendar] or len(days) != 235:
        raise ValueError("ETF sessions must exactly match the complete frozen index calendar")
    if any(
        float(r["volume"]) <= 0
        or not (
            0
            < float(r["low"])
            <= min(float(r["open"]), float(r["close"]))
            <= max(float(r["open"]), float(r["close"]))
            <= float(r["high"])
        )
        for r in bars
    ):
        raise ValueError("untradeable or inconsistent sample prices")
    with corporate_path.open(encoding="utf-8-sig", newline="") as f:
        actions = csv.DictReader(f)
        if actions.fieldnames != [
            "record_date",
            "ex_date",
            "pay_date",
            "cash_per_unit",
            "split_ratio",
        ] or list(actions):
            raise ValueError(
                "unexpected corporate actions for this frozen zero-distribution sample"
            )
    schedules = {
        "hold": [],
        "release_next": action_schedule(days, events, 0),
        "release_plus5": action_schedule(days, events, 5),
    }
    paths, metrics = {}, {}
    for name, schedule in schedules.items():
        for slip in (0, 5):
            result = simulate(
                bars,
                schedule,
                [],
                cash=CAPITAL,
                target=1,
                commission_rate=RATE,
                minimum_fee=MIN_FEE,
                slippage_bps=slip,
            )
            metrics[f"{name}_slip{slip}"] = stats(result)
            if slip == 0:
                paths[name] = result
    scores = {x["date"]: x for x in read_json(OUTCOMES) if x["task"] == TASK}
    peaks = [r["date"] for r in calendar if r["evaluable_peak"] == "1"]
    trips = episode_rows(paths["release_next"], events, scores, bars, peaks)
    relative_terminal = (
        paths["release_next"]["daily"][-1]["nav"] - paths["hold"]["daily"][-1]["nav"]
    )
    if round(sum(r["terminal_contribution_cny"] for r in trips) - relative_terminal, 2) != 0:
        raise ValueError("per-episode attribution does not reconcile to terminal wealth")
    positions = peak_rows(paths, peaks, scores)
    false = [r for r in trips if r["score"] == "missed_window"]
    if (len(scores), len(trips), len(false), len(peaks)) != (14, 14, 11, 5):
        raise ValueError("new denominators conflict with original 14-alert frozen study")
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "episodes.csv", trips)
    write_csv(output / "peaks.csv", positions)
    write_csv(
        output / "fills.csv",
        [{"path": name, **t} for name, result in paths.items() for t in result["trades"]],
    )
    fields = ["date", "shares", "cash", "receivable", "nav", "position_weight", "fees"]
    write_csv(
        output / "daily_positions.csv",
        [
            {"path": name, **{k: r[k] for k in fields}}
            for name, result in paths.items()
            for r in result["daily"]
        ],
    )
    summary = {
        "evidence": "historical_replay",
        "first_publication_at": None,
        "instrument": "SSE:510210",
        "start": START,
        "end": END,
        "sessions": len(days),
        "initial_capital": CAPITAL,
        "fee_rate": RATE,
        "minimum_fee": MIN_FEE,
        "paths": metrics,
        "false": {
            "episodes": len(false),
            "gross_upside_forgone": round(sum(max(0, r["gross_forgone_cny"]) for r in false), 2),
            "gross_declines_avoided": round(sum(max(0, -r["gross_forgone_cny"]) for r in false), 2),
            "fees": round(sum(r["round_trip_fees"] for r in false), 2),
            "net_cost": round(sum(r["net_cost_cny"] for r in false), 2),
        },
    }
    # Commission sensitivity changes just one input. Primary public tariff stays fixed above.
    summary["commission_sensitivity_zero_slippage"] = {}
    for rate in (0.0001, 0.00023, RATE, 0.0005):
        ends = {
            name: simulate(
                bars,
                schedules[name],
                [],
                cash=CAPITAL,
                target=1,
                commission_rate=rate,
                minimum_fee=MIN_FEE,
            )["daily"][-1]["nav"]
            for name in ("hold", "release_next")
        }
        summary["commission_sensitivity_zero_slippage"][str(rate)] = {
            **ends,
            "difference_cny": round(ends["release_next"] - ends["hold"], 2),
        }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("freeze")
    prep.add_argument("--changes", type=Path, required=True)
    prep.add_argument("--index", type=Path, required=True)
    prep.add_argument("--out", type=Path, default=REPORT)
    replay = sub.add_parser("run")
    replay.add_argument("--bars", type=Path, required=True)
    replay.add_argument("--corporate-actions", type=Path, required=True)
    replay.add_argument("--frozen", type=Path, default=REPORT)
    replay.add_argument("--out", type=Path, default=REPORT)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.changes, args.index, args.out)
    else:
        run(args.bars, args.corporate_actions, args.frozen, args.out)


if __name__ == "__main__":
    main()
