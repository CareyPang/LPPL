import json
from datetime import date, timedelta

import pytest

from research.eval import breadth_trend_study as study


def test_point_in_time_inputs_do_not_forward_fill_or_use_later_index(tmp_path):
    dates = ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"]
    idx = tmp_path / "index.json"
    idx.write_text(json.dumps({"price_history": {"dates": dates, "close": [100, 101, 102, 103]}}))
    source = tmp_path / "breadth.json"
    source.write_text(
        json.dumps(
            {
                "history": [{"date": dates[0], "sh": 100.001, "red": 0.8}],
                "latest": {"date": dates[2], "red": 0.33, "trin_vol": 0.5},
            }
        )
    )
    panel = study.read_panel(source, idx, asof=dates[1])
    assert [r["date"] for r in panel] == dates[:2]
    assert panel[0]["sh"] == 100.001 and panel[0]["label_close"] == 100
    assert panel[1].get("red") is None
    panel = study.read_panel(source, idx)
    assert panel[-1]["date"] == dates[2]
    assert panel[-1]["trin_vol"] == 0.5
    source.write_text("date,red\n2026-09-21,0.8\n2026-09-21,0.7\n")
    with pytest.raises(ValueError, match="duplicate breadth"):
        study.read_panel(source.rename(tmp_path / "breadth.csv"), idx)


def test_budget_cannot_move_earlier_alert_and_records_forced_or_pending():
    op = [
        (1, {"a": False, "b": False}),
        (3, {"a": True, "b": False}),
        (8, {"a": False, "b": False}),
        (9, {"a": True, "b": False}),
        (11, {"a": False, "b": True}),
    ]
    short = study.select_pairs(op[:2], ("a", "b"))
    full = study.select_pairs(op, ("a", "b"))
    assert short["a"] == [(3, False, False)] and not short["b"]
    assert full["a"] == [(3, False, True)]
    assert full["b"] == [(9, True, True), (11, False, False)]


@pytest.mark.parametrize("task", ["rebound_end", "stage_top", "rebound"])
def test_unneeded_long_breadth_does_not_discard_otherwise_observed_days(task):
    prev = dict(red=0.8, MCL=200.0, P20=0.52, P60=0.51)
    cur = dict(red=0.4, MCL=100.0, P20=0.45, P60=0.47, trin_amt=0.8, amount_ratio20=0.9)
    if task == "rebound":
        prev = {}  # This width condition uses today's values only.
    incomplete = study.signals(task, "mixed", prev, cur)
    complete = study.signals(task, "mixed", dict(prev, P250=0.2), dict(cur, P250=0.25))
    assert incomplete == complete
    assert incomplete["breadth"] is True and incomplete["amount"] is not None
    assert incomplete["shares"] is None and incomplete["amount_basis"] is None


def test_reversal_with_missing_long_average_keeps_three_valued_logic():
    prev = dict(P20=0.2, P60=0.2)
    cur = dict(red=0.7, P20=0.3, P60=0.25, trin_amt=0.8, amount_ratio20=1.1)
    assert study.signals("reversal", "mixed", prev, cur)["breadth"] is True
    unresolved = study.signals("reversal", "mixed", prev, dict(cur, P60=0.19))
    assert unresolved["breadth"] is None and unresolved["amount"] is None
    assert (
        study.signals("reversal", "mixed", prev, dict(cur, P60=0.19, red=0.4))["breadth"] is False
    )
    # A known rising P250 suffices when P60 is missing.
    assert (
        study.signals("reversal", "mixed", dict(prev, P250=0.1), dict(cur, P250=0.2, P60=None))[
            "breadth"
        ]
        is True
    )


def test_stale_roll_or_incomplete_individual_contracts_are_unscorable():
    a = {"basis": {p: {"symbol": p + "2612", "pct": -2} for p in study.PRODUCTS}}
    b = {"basis": {p: {"symbol": p + "2612", "pct": -1} for p in study.PRODUCTS}}
    assert study.basis_move(a, b) == 1
    b["basis"]["IF"]["symbol"] = "IF2701"
    assert study.basis_move(a, b) is None
    assert study.basis_move({}, {"basis_ann_mean": -6.0}) is None


def test_top_uses_window_not_drawdown_and_counts_one_alert_per_event():
    # A 1% upswing across 125 sessions peaks, then declines less than 0.1%.
    p = [100 + i * 0.01 for i in range(131)]
    high = p[-1]
    p.extend(high - 0.001 * i for i in range(1, 24))
    assert 130 in study.top_dates(p, "stage_top")
    possible, mature = study.eligible_peaks([126, 129, len(p) - 1], {130}, 10, 20, len(p))
    # At this cutoff even signal 126 is censored: its 10-day window needs 20 right days.
    assert possible == set() and mature == []
    assert study.match_peaks([123, 125, 130], {130}, 10) == {123: 130}


def test_forward_excursion_separates_high_from_ordered_close_recovery():
    prices = [100, 120, 80, 84, 88, 86, 85, 84, 84, 83, 82]
    rows = [dict(label_close=p, label_high=p + 2) for p in prices]
    r = study.followup(rows, 0, "rebound")
    assert r["best_intraday_high_ret10"] == pytest.approx(0.22)
    assert r["max_close_rebound10"] == pytest.approx(0.10)  # 80 -> 88; 120 predates 80.
    rows[5]["label_high"] = None
    assert study.followup(rows, 0, "rebound")["best_intraday_high_ret10"] is None
    assert study.followup(rows[:-1], 0, "rebound")["max_close_rebound10"] is None


def test_rebound_and_reversal_have_different_outcomes_and_missingness():
    rows = [
        {"label_close": px, "P60": 0.4}
        for px in ([98] * 19 + [100, 103, 101, 99, 96, 95] + [96] * 15)
    ]
    rebound = study.followup(rows, 19, "rebound")
    assert rebound["ret1"] > 0 > rebound["ret5"] and rebound["best_close_ret10"] == pytest.approx(
        0.03
    )
    rev = study.followup(rows, 19, "reversal")
    assert rev["status"] == "mature" and not rev["held"] and not rev["reversal"]
    rows[-1]["P60"] = None
    assert study.followup(rows, 19, "reversal")["status"] == "missing_followup_breadth"
    assert study.followup(rows[:-1], 19, "reversal")["status"] == "immature"


def test_equal_budget_groups_share_phase_maturity_and_complete_outcomes(monkeypatch):
    # Varying maturity and a final censored block must not benefit the earlier issuer.
    days = [date(2025, 1, 1) + timedelta(days=i) for i in range(160)]
    rows = [
        {"date": d.isoformat(), "label_close": 100 + i * 0.01, "P60": 0.4, "red": 0.5}
        for i, d in enumerate(days)
    ]

    def fixture(_rows, _start):
        daily = []
        for i in range(126, len(_rows)):
            criterion = {layer: i % (len(layer) + 1) == 0 for layer in study.LAYERS}
            daily.append(
                (
                    i,
                    "medium_up",
                    "early" if i % 2 else "middle_late",
                    {t: criterion for t in study.TASKS},
                )
            )
        return daily, 0

    monkeypatch.setattr(study, "feature_days", fixture)
    summary, comparisons, alerts, _ = study.study(rows)
    for maturity in ("early", "middle_late"):
        subset = [
            r
            for r in comparisons
            if r["phase"] == "medium_up"
            and r["maturity"] == maturity
            and r["task"] == "rebound"
            and r["pair"] == "stage_vs_breadth"
        ]
        assert len(subset) == 2
        assert {r["quota_alerts"] for r in subset} == {4}
        assert {r["paired_scored_alerts"] for r in subset} == {3}
        assert {r["ret10_n"] for r in subset} == {3}
    assert summary["sessions_with_phase_and_breadth"] == 34
    assert any(r["mode"] == "equal_budget" and r["forced"] for r in alerts)
