import hashlib
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

from research.eval import stage_etf_positions
from research.eval.breadth_trend_study import TOP_WINDOW, match_peaks
from research.eval.stage_etf_positions import (
    OUTCOMES,
    REPORT,
    action_schedule,
    episode_rows,
    read_csv,
    read_json,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / REPORT


def state(day, episode, level):
    return {"date": day, "episode_id": episode, "level": level}


def test_revision_cannot_silently_enter_frozen_replay(tmp_path, monkeypatch):
    # The third-party quote rows are not a repository fixture. Substitute only
    # its expected digest while preserving the production checks on research inputs.
    bars = tmp_path / "test_quotes.csv"
    bars.write_bytes(b"quote fixture")
    with pytest.raises(ValueError, match="frozen ETF quote sample"):
        stage_etf_positions.verify_inputs(bars, DATA)
    monkeypatch.setattr(
        stage_etf_positions, "CSV_SHA256", hashlib.sha256(bars.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(stage_etf_positions, "OUTCOMES", ROOT / OUTCOMES)
    stage_etf_positions.verify_inputs(bars, DATA)
    for filename in ["frozen_events.csv", "scoring_calendar.csv"]:
        (tmp_path / filename).write_bytes((DATA / filename).read_bytes())
    revisions = tmp_path / "frozen_events.csv"
    revisions.write_bytes(revisions.read_bytes().replace(b"strengthening", b"invalidated", 1))
    with pytest.raises(ValueError, match="frozen_events.csv"):
        stage_etf_positions.verify_inputs(bars, tmp_path)


@pytest.mark.parametrize("delay", [0, 5])
def test_all_frozen_schedule_prefixes_match_at_that_close(delay):
    days = [r["date"] for r in read_csv(DATA / "scoring_calendar.csv")]
    events = read_csv(DATA / "frozen_events.csv")
    full = action_schedule(days, events, delay)
    for i, day in enumerate(days):
        as_of = [e for e in events if e["date"] <= day]
        assert action_schedule(days[: i + 1], as_of, delay) == [
            action for action in full if action["date"] <= day
        ]


def test_new_watch_on_fifth_session_cancels_due_release_even_after_calendar_gap():
    days = [
        "2025-09-26",
        "2025-09-29",
        "2025-09-30",
        "2025-10-09",
        "2025-10-10",
        "2025-10-13",
        "2025-10-14",
        "2025-10-15",
        "2025-10-16",
        "2025-10-17",
        "2025-10-20",
        "2025-10-21",
        "2025-10-22",
        "2025-10-23",
    ]
    events = [
        state(days[0], "A", "watch"),
        state(days[1], "A", "invalidated"),
        state(days[6], "B", "watch"),
        state(days[7], "B", "invalidated"),
    ]
    delayed = action_schedule(days, events, 5)
    assert [(a["date"], a["target"], a["episode_id"]) for a in delayed] == [
        (days[0], 0.5, "A"),
        (days[6], 0.5, "B"),
        (days[12], 1, "B"),
    ]
    assert [a["date"] for a in action_schedule(days, events, 0) if a["target"] == 1] == [
        days[1],
        days[7],
    ]


def test_frozen_credit_is_one_to_one_even_if_three_windows_contain_march_peak():
    calendar = read_csv(DATA / "scoring_calendar.csv")
    days = [r["date"] for r in calendar]
    peaks = [i for i, row in enumerate(calendar) if row["evaluable_peak"] == "1"]
    episodes = read_csv(DATA / "episodes.csv")
    watches = [days.index(row["watch"]) for row in episodes]
    matched = {
        days[i]: days[p] for i, p in match_peaks(watches, peaks, TOP_WINDOW["stage_top"]).items()
    }
    original = {r["date"]: r for r in read_json(ROOT / OUTCOMES) if r["task"] == "stage_top"}
    assert {r["watch"] for r in episodes} == set(original)
    assert len(episodes) == len(set(watches)) == 14
    assert len(peaks) == 5 and len(matched) == 3
    for row in episodes:
        watch = row["watch"]
        assert (row["credited_peak"] or None) == matched.get(watch) == original[watch]["peak"]
        assert row["score"] == original[watch]["status"]
        assert row["window_end"] == original[watch]["window_end"]
    march = [r for r in episodes if "2026-03-02" in r["peaks_in_original_window"].split("|")]
    assert [r["watch"] for r in march] == ["2026-02-13", "2026-02-26", "2026-03-02"]
    assert [r["watch"] for r in march if r["credited_peak"]] == ["2026-02-13"]


def test_intraday_forgone_gain_stops_at_buyback_open():
    days = ["2025-09-01", "2025-09-02", "2025-09-03", "2025-09-04"]
    release = days[2]
    events = [state(days[0], "A", "watch"), state(release, "A", "invalidated")]
    trades = [
        {
            "date": days[1],
            "episode_id": "A",
            "side": "sell",
            "shares": 100,
            "price": 10,
            "fee": 5,
            "shares_after": 100,
        },
        {
            "date": days[3],
            "episode_id": "A",
            "side": "buy",
            "shares": 100,
            "price": 11,
            "fee": 5,
            "shares_after": 200,
        },
    ]
    bars = [dict(date=d, high=h, close=10) for d, h in zip(days, [50, 12, 10.5, 99], strict=True)]
    scores = {days[0]: dict(window_end=days[-1], status="missed_window", peak=None, lead=None)}
    (row,) = episode_rows({"trades": trades}, events, scores, bars, [])
    assert row["largest_interim_forgone_cny"] == 200
    assert row["gross_forgone_cny"] == 100
    assert row["net_cost_cny"] == 110
    trades[1]["price"] = 13
    (row,) = episode_rows({"trades": trades}, events, scores, bars, [])
    assert row["largest_interim_forgone_cny"] == 300  # include the opening gap


def test_all_daily_paths_reconcile_to_cash_shares_fees_and_common_close():
    calendar = [r["date"] for r in read_csv(DATA / "scoring_calendar.csv")]
    all_daily, fills = read_csv(DATA / "daily_positions.csv"), read_csv(DATA / "fills.csv")
    summary = read_json(DATA / "summary.json")
    events = read_csv(DATA / "frozen_events.csv")
    reference = {}
    for r in all_daily:
        if r["path"] == "hold":
            reference[r["date"]] = (
                Decimal(r["nav"]) - Decimal(r["cash"]) - Decimal(r["receivable"])
            ) / int(r["shares"])
    for path, lag in [("hold", None), ("release_next", 0), ("release_plus5", 5)]:
        actions = action_schedule(calendar, events, lag) if lag is not None else []
        at_close = {(a["episode_id"], a["date"]): a for a in actions}
        by_date = defaultdict(list)
        for t in (r for r in fills if r["path"] == path):
            if t["signal_date"]:
                assert t["date"] == calendar[calendar.index(t["signal_date"]) + 1]
                signal = at_close[t["episode_id"], t["signal_date"]]
                assert (signal["target"] == 1) == (t["side"] == "buy")
            by_date[t["date"]].append(t)
        daily = [r for r in all_daily if r["path"] == path]
        assert [r["date"] for r in daily] == calendar
        cash, shares, fees = Decimal(summary["initial_capital"]), 0, Decimal(0)
        for d in daily:
            for t in by_date[d["date"]]:
                quantity, price, fee = int(t["shares"]), Decimal(t["price"]), Decimal(t["fee"])
                assert quantity > 0 and quantity % 100 == 0
                assert Decimal(t["gross"]) == quantity * price
                shares_delta = quantity if t["side"] == "buy" else -quantity
                cash_delta = -shares_delta * price - fee
                assert cash_delta == Decimal(t["net_cash"])
                cash += cash_delta
                shares += shares_delta
                fees += fee
                assert cash == Decimal(t["cash_after"]) and shares == int(t["shares_after"])
            assert shares >= 0 and cash >= 0
            assert shares == int(d["shares"]) and cash == Decimal(d["cash"])
            assert Decimal(d["receivable"]) == 0 and fees == Decimal(d["fees"])
            assert shares * reference[d["date"]] + cash == Decimal(d["nav"])
        saved = summary["paths"][f"{path}_slip0"]
        assert Decimal(str(saved["end_nav"])) == Decimal(daily[-1]["nav"])
        assert saved["fills"] == sum(map(len, by_date.values()))


def test_episode_cost_plus_post_buyback_share_difference_explains_terminal_nav_gap():
    episodes = read_csv(DATA / "episodes.csv")
    daily = read_csv(DATA / "daily_positions.csv")
    last_hold = [r for r in daily if r["path"] == "hold"][-1]
    last_active = [r for r in daily if r["path"] == "release_next"][-1]
    final_mark = (Decimal(last_hold["nav"]) - Decimal(last_hold["cash"])) / int(last_hold["shares"])
    carry = sum(
        (int(r["bought"]) - int(r["sold"])) * (final_mark - Decimal(r["buy_price"]))
        for r in episodes
    )
    cost = sum(Decimal(r["net_cost_cny"]) for r in episodes)
    assert carry - cost == Decimal(last_active["nav"]) - Decimal(last_hold["nav"])
    missed = [r for r in episodes if r["score"] == "missed_window"]
    false = read_json(DATA / "summary.json")["false"]
    assert false["episodes"] == len(missed) == 11
    for field, key in [("fees", "round_trip_fees"), ("net_cost", "net_cost_cny")]:
        assert Decimal(str(false[field])) == sum(Decimal(r[key]) for r in missed)
