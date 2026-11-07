"""Audit denominators, calendar timing, censoring, and first-alarm selection."""
import pandas as pd
import pytest

from tools.lppl_repo_oscillation_refilter import (
    ARMS,
    REFERENCE,
    SCALES,
    aggregate_asofs,
    evaluate_alarms,
    evaluate_events,
    paired,
    prepare,
    summaries,
)


def test_same_parameter_rows_use_four_gates_without_fit_selection():
    d = pd.DataFrame(dict(date=pd.to_datetime(["2010-01-04"] * 5),
                         n=[130, 135, 140, 145, 150], tc=[219, 144, 130, 144, 159],
                         m=[.5] * 5, w=[6.] * 5, B=[-1., -1., -1., -1., 1.]))
    got = prepare(d)
    assert got[ARMS[0]].tolist() == [True, True, False, False, False]
    assert got[ARMS[1]].tolist() == [True, True, False, False, False]
    assert got[ARMS[2]].tolist() == [False, True, False, False, False]
    assert got[ARMS[3]].tolist() == [False, True, False, False, False]
    assert len(got) == len(d) and "ahead" not in d
    with pytest.raises(ValueError, match="duplicate"):
        prepare(pd.concat([d, d.iloc[:1]]))


def test_all_original_windows_stay_in_denominator_and_zero_dates_remain():
    dates = pd.bdate_range("1998-01-01", periods=1000)
    date = dates[600]
    rows = [dict(date=date, n=n, tc=n + 9, m=.5 if n in (130, 135) else 1.3, w=8., B=-1.)
            for n in range(130, 505, 5)]
    result = aggregate_asofs(pd.DataFrame(rows), dates, dates, "synthetic")
    a = result[(result.date == date) & (result.arm == ARMS[0])].set_index("scale")
    assert a.loc["6-12m", "status"] == "ok"
    assert a.loc["6-12m", "stored_windows"] == 25
    assert a.loc["6-12m", "accepted_windows"] == 2
    assert a.loc["6-12m", "fraction"] == .08
    assert a.loc["6-12m", "alarm"]
    assert a.loc["12-24m", "status"] == "ok"
    assert a.loc["12-24m", "fraction"] == 0.
    assert not a.loc["12-24m", "alarm"]
    assert (result.status == "missing_scan").any()
    assert (result[result.status == "missing_scan"].fraction.isna()).all()
    incomplete = aggregate_asofs(pd.DataFrame(rows[1:]), dates, dates, "synthetic")
    a = incomplete[(incomplete.date == date) & (incomplete.scale == "6-12m")]
    assert set(a.status) == {"incomplete_window_grid"}
    assert not a.alarm.any()


def test_young_asset_smaller_eligible_grid_is_not_mislabeled_missing():
    global_dates = pd.bdate_range("1998-01-01", periods=1000)
    dates = global_dates[400:]
    date = global_dates[600]  # 201 available observations, windows through 200.
    rows = [dict(date=date, n=n, tc=n + 9, m=.5, w=8., B=-1.) for n in range(130, 201, 5)]
    result = aggregate_asofs(pd.DataFrame(rows), dates, global_dates, "young")
    a = result[result.date == date]
    assert set(a[a.scale == "6-12m"].status) == {"ok"}
    assert set(a[a.scale == "6-12m"].expected_windows) == {15}
    assert set(a[a.scale == "12-24m"].status) == {"insufficient_window_history"}


def _asofs():
    dates = pd.bdate_range("2000-01-03", periods=300)
    rows = []
    for scale in SCALES:
        for arm in ARMS:
            for pos in range(30, 151, 5):
                alarm = pos in (90, 140)
                # First alarm has a broad interval; later narrower one must not be selected.
                low, high = (59., 80.) if pos == 90 else (9., 11.)
                rows.append(dict(symbol="x", scale=scale, arm=arm, date=dates[pos], position=pos,
                                 status="ok", scheduled=True, alarm=alarm, tc_q20=low, tc_q80=high,
                                 tc_width=high - low, accepted_windows=2 if alarm else 0))
    return dates, pd.DataFrame(rows)


def test_first_alarm_and_next_actual_session_define_actionable_lead_and_interval():
    dates, asofs = _asofs()
    events = evaluate_events(asofs, [dates[150]], dates, "x")
    assert events.evaluable.all() and events.hit.all()
    assert set(events.first_alarm_lead) == {60}
    assert set(events.actionable_lead) == {59}
    assert set(events.execution_date) == {dates[91]}
    assert events.first_interval_covers_proxy.all()
    assert events.hit_actionable_5.all()
    assert not events.joint_hit.any()  # First interval width21; later width2 cannot rescue it.
    # A six-session as-of lead allows five sessions after next-session execution.
    asofs["alarm"] = False
    extra = asofs[asofs.position == 140].copy()
    extra["position"], extra["date"] = 144, dates[144]
    extra["alarm"], extra["tc_q20"], extra["tc_q80"], extra["tc_width"] = True, 5., 7., 2.
    extra["accepted_windows"] = 3
    events = evaluate_events(pd.concat([asofs, extra]), [dates[150]], dates, "x")
    assert set(events.actionable_lead) == {5}
    assert events.joint_hit.all()
    extra["accepted_windows"] = 1
    events = evaluate_events(pd.concat([asofs, extra]), [dates[150]], dates, "x")
    assert events.hit_actionable_5.all() and not events.joint_hit.any()


def test_missing_scan_and_unknown_event_cannot_be_scored_as_misses():
    dates, asofs = _asofs()
    asofs.loc[asofs.position == 100, "status"] = "missing_scan"
    events = evaluate_events(asofs, [dates[150], pd.Timestamp("2000-01-01")], dates, "x")
    assert not events.evaluable.any()
    assert events.hit.isna().all() and events.hit_actionable_5.isna().all()
    assert events[events.event == dates[150]].observed_hit.all()
    assert events[events.event == pd.Timestamp("2000-01-01")].status.str.contains("unknown_event_date").all()


def test_alarm_future_horizon_censoring_and_zero_event_false_alarms():
    dates, asofs = _asofs()
    # Both historical alarms have complete future H in this calendar.
    alarms = evaluate_alarms(asofs, [dates[150]], dates)
    assert alarms.evaluable.all()
    assert not alarms.false_alarm.any()
    alarms = evaluate_alarms(asofs, [], dates)
    assert alarms.false_alarm.all()
    dates = dates[:160]
    censored = evaluate_alarms(asofs, [dates[150]], dates)
    assert (censored.status == "incomplete_future_H").any()
    assert censored.loc[~censored.evaluable, "false_alarm"].isna().all()


def test_pairing_uses_common_event_hits_and_summaries_include_zero_alarm_arms():
    dates, asofs = _asofs()
    # One arm alerts later and another never alerts; retain both comparisons.
    asofs.loc[(asofs.arm == ARMS[2]) & (asofs.position == 90), "alarm"] = False
    asofs.loc[asofs.arm == ARMS[3], "alarm"] = False
    events = evaluate_events(asofs, [dates[150]], dates, "x")
    pairs = paired(events)
    common = pairs[pairs.arm == ARMS[2]]
    assert common.common_hit.all()
    assert set(common.actionable_lead_delta) == {-50}
    lost = pairs[pairs.arm == ARMS[3]]
    assert lost.lost_hit.all() and not lost.common_hit.any()
    assert set(pairs.reference) == {REFERENCE}
    alarms = evaluate_alarms(asofs, [dates[150]], dates)
    result = summaries(asofs, events, alarms)
    no_alarm = result[result.arm == ARMS[3]]
    assert set(no_alarm.n_evaluable) == {1}
    assert set(no_alarm.n_hit) == {0}
    assert set(no_alarm.n_missed) == {1}
    assert no_alarm.false_alarm_rate.isna().all()  # No alarms is not zero false alarm probability.
