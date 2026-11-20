from datetime import date, timedelta

import pandas as pd
import pytest

from research.data import breadth
from research.data.breadth_alerts import build_trend_ledger, classify_phase


def panel(direction):
    rows = []
    for i in range(61):
        day = date(2025, 1, 1) + timedelta(days=i)
        rows.append(
            {
                "date": day.isoformat(),
                "sh": 1000 + direction * i,
                "P20": 0.5 + direction * i * 0.002,
                "P60": 0.5 + direction * i * 0.001,
                "P250": 0.42,
                "red": 0.5,
                "MCL": direction * i / 100,
                "trin_amt": 1.0,
                "trin_vol": 1.0,
                "amount_ratio20": 1.0,
            }
        )
    return rows


def next_day(rows, **overrides):
    prev = rows[-1]
    day = date.fromisoformat(prev["date"]) + timedelta(days=1)
    rows.append({**prev, "date": day.isoformat(), **overrides})
    return rows[-1]


def by_kind(snapshot, kind):
    return next(a for a in snapshot["alerts"] if a["kind"] == kind)


def test_prior_phase_is_independent_of_alert_day_and_future_rows():
    rows = panel(1)
    phase = classify_phase(rows)
    assert (phase["id"], phase["maturity"], phase["leg_sessions"]) == (
        "medium_up",
        "middle_late",
        56,
    )
    warning_day = next_day(rows, red=0.85, trin_amt=1.9)
    ledger = build_trend_ledger(rows)
    old = ledger[-1]
    assert old["phase"] == phase and old["phase"]["asof"] < old["asof"]
    initial = by_kind(old, "stage_top")
    assert initial["level"] == "watch" and initial["is_new"]
    next_day(rows, red=0.43, MCL=-0.1, P20=0.49)
    new = build_trend_ledger(rows)
    assert old == new[-2]
    stronger = by_kind(new[-1], "stage_top")
    assert stronger["level"] == "strengthening"
    assert stronger["id"] == initial["id"]
    assert stronger["trigger_date"] == warning_day["date"] and not stronger["is_new"]
    assert stronger["update_date"] == rows[-1]["date"]


def test_panic_watch_recovery_reversal_and_second_low_are_distinct():
    rows = panel(-1)
    first = next_day(rows, sh=930, red=0.1, MCL=-3, trin_amt=0.4)
    next_day(rows, sh=925, red=0.15, MCL=-4, trin_amt=0.35)
    bounce = next_day(rows, sh=933, red=0.75, MCL=-1, P20=0.45, P60=0.46, trin_amt=0.95)
    next_day(rows, sh=921, red=0.18, MCL=-4, P20=0.35, P60=0.36, trin_amt=0.33)
    ledger = build_trend_ledger(rows, evidence="experimental")
    expect = by_kind(ledger[-4], "rebound")
    assert expect["level"] == "watch" and expect["trigger_date"] == first["date"]
    assert by_kind(ledger[-3], "rebound")["id"] == expect["id"]
    assert not by_kind(ledger[-3], "rebound")["is_new"]
    assert by_kind(ledger[-2], "rebound")["level"] == "strengthening"
    reversal = by_kind(ledger[-2], "reversal")
    assert reversal["trigger_date"] == bounce["date"] and reversal["level"] == "watch"
    assert by_kind(ledger[-1], "reversal")["level"] == "invalidated"
    assert any(a["id"] == expect["id"] and not a["active"] for a in ledger[-1]["alerts"])
    assert all(a["evidence"] == "experimental" for a in ledger[-1]["alerts"])


def test_reversal_strengthens_only_after_a_higher_retest_and_sustained_breadth():
    rows = panel(-1)
    next_day(rows, sh=944, red=0.72, P20=0.41, P60=0.46, MCL=-0.2)
    next_day(rows, sh=948, P20=0.42, P60=0.47, MCL=-0.1)
    next_day(rows, sh=944, red=0.36, P20=0.41, P60=0.465, MCL=-0.3)
    next_day(rows, sh=952, red=0.71, P20=0.43, P60=0.47, MCL=-0.1)
    ledger = build_trend_ledger(rows)
    assert [by_kind(s, "reversal")["level"] for s in ledger[-4:]] == [
        "watch",
        "watch",
        "watch",
        "strengthening",
    ]


def test_opposite_short_term_observation_succeeds_previous_episode_with_both_ids():
    rows = panel(-1)
    for i in range(1, 9):
        next_day(rows, sh=940 + i, P20=0.38 + 0.01 * i, P60=0.44 + 0.002 * i)
    first = next_day(rows, sh=948, red=0.76, trin_amt=1.8)
    for i in range(5):
        next_day(rows, sh=930 - i, red=0.35, MCL=-2 - i, P20=0.32, P60=0.40, trin_amt=0.95)
    next_day(rows, sh=918, red=0.10, MCL=-3, P20=0.30, P60=0.38, trin_amt=0.33)
    ledger = build_trend_ledger(rows)
    old = by_kind(next(s for s in ledger if s["asof"] == first["date"]), "rebound_end")
    assert old["active"]
    new, archived = by_kind(ledger[-1], "rebound"), by_kind(ledger[-1], "rebound_end")
    assert new["active"] and new["is_new"]
    assert archived["id"] == old["id"] and not archived["active"]
    assert archived["trigger_date"] == old["trigger_date"]
    assert archived["update_date"] == new["trigger_date"]
    assert archived["closure_reason"] == "new_opposite_observation"
    assert archived["replaced_by"] == new["id"]


def test_early_rally_trin_remains_context_until_breadth_independently_deteriorates():
    rows = panel(-1)
    for i in range(1, 7):
        next_day(rows, sh=940 + i, P20=0.38 + 0.01 * i, P60=0.44 + 0.002 * i)
    first = next_day(rows, sh=947, red=0.82, trin_amt=1.9)
    next_day(rows, sh=947.5, red=0.43, MCL=-2, trin_amt=0.84)
    before, after = build_trend_ledger(rows)[-2:]
    assert before["rule_version"] == "stage-breadth-2"
    assert before["phase"]["maturity"] == "early"
    assert "1.90倍" in before["context_note"] and "留意" in before["context_note"]
    assert all(item["kind"] != "rebound_end" for item in before["alerts"])
    assert by_kind(after, "rebound_end")["trigger_date"] > first["date"]


def test_early_selling_extreme_is_context_and_broad_recovery_can_warn_in_early_decline():
    rows = panel(1)
    for i in range(2):
        next_day(rows, sh=1045 - i, red=0.45, P20=0.50, P60=0.52, MCL=-1)
    next_day(rows, sh=1040, red=0.13, trin_amt=0.3, MCL=-2)
    next_day(rows, sh=1044, red=0.75, P20=0.55, P60=0.56, MCL=-0.4)
    before, after = build_trend_ledger(rows)[-2:]
    assert before["phase"]["maturity"] == "early"
    assert "上涨股票只占" in before["context_note"]
    assert not any(item["kind"] == "rebound" for item in before["alerts"])
    assert after["phase"]["id"] == "early_decline"
    assert by_kind(after, "reversal")["is_new"]


def test_roll_missing_and_insufficient_history_do_not_fabricate_evidence():
    rows = panel(1)
    rows[-1]["basis"] = {"IF": {"symbol": "IF2608", "pct": -5}}
    next_day(rows, red=0.85, trin_amt=2.0, basis={"IF": {"symbol": "IF2609", "pct": -3}})
    warning = build_trend_ledger(rows)[-1]
    assert all("期货" not in s for s in by_kind(warning, "stage_top")["reasons"])
    assert build_trend_ledger(rows[:20])[-1]["state"] == "unavailable"
    assert build_trend_ledger([{**r, "P60": None} for r in rows])[-1]["alerts"] == []
    with pytest.raises(ValueError, match="increasing"):
        build_trend_ledger([*rows, rows[-1]])


def test_snapshot_legacy_optional_fields_and_rules_are_available_to_real_consumers():
    rows = panel(-1)
    next_day(rows, red=0.12, trin_amt=0.35)
    for row in rows:
        row["basis_json"] = "{}"
    snapshot = breadth._build_output(pd.DataFrame(rows))
    assert snapshot["trend_alerts"]["asof"] == snapshot["asof"]
    assert by_kind(snapshot["trend_alerts"], "rebound")["level"] == "watch"
    assert snapshot["trend_alerts"]["evidence"] == "experimental"
    assert snapshot["history"][-1]["basis"] == {}
    assert snapshot["history"][-1]["down_mean_amount"] is None
    assert snapshot["history"][-1]["trin_vol"] == 1
