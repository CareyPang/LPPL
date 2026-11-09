"""Window/cluster runner respects shared opportunities and real event timing."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.lppls.window_clusters import SCALE_WINDOWS
from tools.lppl_window_cluster_research import (
    ARMS,
    aggregate_asofs,
    evaluate_alarms,
    evaluate_events,
    expected_windows,
    interval_iou,
    paired,
    run,
    summaries,
)


def _fits(dates, positions, missing=()):
    records = []
    for pos in positions:
        for n in (n for ns in SCALE_WINDOWS.values() for n in ns):
            if (pos, n) in missing:
                continue
            # The same absolute tc remains across scans; relative h falls 5 bars.
            h = 520 - pos
            qualified = n in (30, 65, 130)
            records.append(dict(date=dates[pos], n=n, tc=n - 1 + h,
                                m=.5, w=13., B=-1. if qualified else 1.))
    return pd.DataFrame(records)


def test_expected_grid_includes_short_windows_and_checks_original_gap_rule():
    global_dates = pd.bdate_range("1998-01-01", periods=900)
    dates = global_dates[400:]
    result = expected_windows(dates, global_dates, global_dates[550])
    assert result == list(range(30, 151, 5))
    # A sparse series cannot pretend its 30 observations are 30 calendar sessions.
    sparse = global_dates[::2]
    assert expected_windows(sparse, global_dates, global_dates[800]) == []
    assert expected_windows(dates, global_dates, global_dates[100]) == []


def test_interval_iou_uses_absolute_positions_and_handles_degenerate_points():
    assert interval_iou((10., 20.), (15., 25.)) == pytest.approx(1 / 3)
    assert interval_iou((10., 10.), (10., 10.)) == 1.
    assert interval_iou((10., 10.), (11., 11.)) == 0.
    assert interval_iou(None, (10., 20.)) == 0.


def test_all_nine_arms_keep_zero_dates_and_stability_resets_on_missing_scan():
    dates = pd.bdate_range("2000-01-03", periods=550)
    source = _fits(dates, (500, 505, 515))  # Missing planned 510 must reset persistence.
    a, scales, clusters, members = aggregate_asofs(source, dates, dates, "synthetic")
    assert a.groupby("date").arm.nunique().eq(9).all()
    stable = a[a.arm == "cluster_cross_stable2"].set_index("position")
    assert not stable.loc[500, "own_alarm"]
    assert not stable.loc[500, "own_evaluable"]  # Previous input is absent, not observed no-cluster.
    assert stable.loc[505, "own_alarm"]
    assert stable.loc[505, "stability_iou"] == 1.
    assert not stable.loc[510, "own_evaluable"]
    assert not stable.loc[515, "own_alarm"]  # Cannot join across the absent planned scan.
    assert not stable.loc[515, "own_evaluable"]
    assert not a[a.position == 510].common_evaluable.any()
    assert set(a[(a.position == 500) & (a.arm != "cluster_cross_stable2")].status) == {"ok"}
    assert scales[(scales.date == dates[500]) & (scales["mode"] == "full")].denominator.sum() == 95
    assert scales[(scales.date == dates[500]) & (scales["mode"] == "thin")].denominator.sum() == 28
    assert len(clusters) > 0 and len(members) >= 3
    assert set(members["n"]) <= {30, 65, 130}


def test_stable_previous_valid_no_cluster_is_evaluable_unlike_missing_previous_input():
    dates = pd.bdate_range("2000-01-03", periods=550)
    source = _fits(dates, (500, 505, 510))
    source.loc[source.date == dates[500], "B"] = 1.
    a, _, _, _ = aggregate_asofs(source, dates, dates, "synthetic")
    stable = a[a.arm == "cluster_cross_stable2"].set_index("position")
    assert stable.loc[505, "own_evaluable"]
    assert not stable.loc[505, "own_alarm"]
    assert stable.loc[510, "own_evaluable"] and stable.loc[510, "own_alarm"]


def test_incomplete_full_grid_is_not_hidden_by_thinning_and_own_coverage_is_separate():
    dates = pd.bdate_range("2000-01-03", periods=550)
    source = _fits(dates, (500,), missing=((500, 260),))
    a, _, _, _ = aggregate_asofs(source, dates, dates, "synthetic")
    a = a[a.position == 500].set_index("arm")
    assert a.loc["ref_6_12m", "own_evaluable"]
    assert not a.loc["ref_12_24m", "own_evaluable"]
    assert a.loc["or4_thin", "own_evaluable"]  # 260 is not a fixed thin anchor.
    assert not a.common_evaluable.any()  # Primary comparison keeps one opportunity set.
    assert not a.common_alarm.any()


def _asofs():
    dates = pd.bdate_range("2000-01-03", periods=350)
    rows = []
    for arm in ARMS:
        for pos in range(30, 151, 5):
            alarm = pos in (90, 95, 140)
            low, high = (59., 80.) if pos == 90 else (9., 11.)
            rows.append(dict(symbol="x", arm=arm, date=dates[pos], position=pos,
                             scheduled=True, plan_order=(pos - 30) // 5, status="ok",
                             own_evaluable=True, common_evaluable=True,
                             own_alarm=alarm, common_alarm=alarm,
                             interval_lo=low, interval_hi=high, interval_width=high - low,
                             interval_support=3))
    return dates, pd.DataFrame(rows)


def test_first_alarm_and_next_session_action_are_not_replaced_by_later_narrow_cluster():
    dates, a = _asofs()
    e = evaluate_events(a, [dates[150]], dates, "x")
    assert e.evaluable.all() and e.hit.all()
    assert set(e.first_alarm) == {dates[90]}
    assert set(e.actionable_lead) == {59}
    assert set(e.execution_date) == {dates[91]}
    assert e.hit_actionable_5.all()
    assert not e.joint_hit.any()  # Later narrow interval cannot rescue broad first alert.
    a["own_alarm"], a["common_alarm"] = False, False
    extra = a[a.position == 140].copy()
    extra["position"], extra["date"] = 144, dates[144]
    extra["own_alarm"], extra["common_alarm"] = True, True
    extra["interval_lo"], extra["interval_hi"], extra["interval_width"] = 5., 7., 2.
    e = evaluate_events(pd.concat([a, extra]), [dates[150]], dates, "x")
    assert set(e.actionable_lead) == {5}
    assert e.joint_hit.all()
    extra["interval_support"] = 1
    e = evaluate_events(pd.concat([a, extra]), [dates[150]], dates, "x")
    assert e.hit_actionable_5.all() and not e.joint_hit.any()


def test_shared_event_opportunities_and_own_coverage_do_not_turn_missing_into_miss():
    dates, a = _asofs()
    a.loc[a.position == 100, "common_evaluable"] = False
    a.loc[a.position == 100, "common_alarm"] = False
    a.loc[(a.position == 100) & (a.arm == ARMS[1]), "own_evaluable"] = False
    e = evaluate_events(a, [dates[150]], dates, "x")
    assert not e[e.scope == "common"].evaluable.any()
    assert e[e.scope == "common"].hit.isna().all()
    assert e[(e.scope == "own") & (e.arm == ARMS[0])].evaluable.all()
    assert not e[(e.scope == "own") & (e.arm == ARMS[1])].evaluable.any()
    unknown = evaluate_events(a, [pd.Timestamp("2000-01-01")], dates, "x")
    assert not unknown.evaluable.any() and unknown.hit.isna().all()


def test_alarm_cost_keeps_non_alarm_denominator_and_counts_contiguous_plan_episodes():
    dates, a = _asofs()
    o = evaluate_alarms(a, [], dates)
    part = o[(o.arm == ARMS[0]) & (o.scope == "common") & (o.H == 60)]
    assert len(part) == 25 and part.evaluable.all()
    assert part.alarm.sum() == 3
    assert part.episode_start.sum() == 2  # 90+95 is one episode, 140 another.
    assert part[part.alarm].false_alarm.all()
    assert part[~part.alarm].false_alarm.isna().all()
    a.loc[a.position == 95, "common_evaluable"] = False
    o = evaluate_alarms(a, [], dates[:170])
    assert o[o.date == dates[140]].status.eq("incomplete_future_H").all()
    assert o.loc[~o.evaluable, "false_alarm"].isna().all()


def test_paired_first_alerts_and_zero_alarm_summary_preserve_common_denominator():
    dates, a = _asofs()
    later = a.arm == "or4_full"
    a.loc[later & (a.position < 140), ["own_alarm", "common_alarm"]] = False
    a.loc[a.arm == "cluster_cross_stable2", ["own_alarm", "common_alarm"]] = False
    e = evaluate_events(a, [dates[150]], dates, "x")
    o = evaluate_alarms(a, [dates[150]], dates)
    p = paired(e)
    part = p[p.arm == "or4_full"]
    assert part.common_hit.all() and set(part.actionable_lead_delta) == {-50.}
    no_alert = p[p.arm == "cluster_cross_stable2"]
    assert no_alert.lost_hit.all() and not no_alert.common_hit.any()
    s = summaries(a, e, o)
    common = s[s.scope == "common"]
    assert common.groupby(["symbol", "H"]).n_evaluable.nunique().eq(1).all()
    zero = s[s.arm == "cluster_cross_stable2"]
    assert zero.n_hit.eq(0).all() and zero.n_evaluable.eq(1).all()
    assert zero.n_alert_asofs.eq(0).all() and zero.n_alert_episodes.eq(0).all()
    assert zero.false_alert_fraction.isna().all()
    assert zero.alerts_per_100_asofs.eq(0).all()


def test_runner_refuses_to_overwrite_before_reading_any_input(tmp_path):
    output = tmp_path / "old"
    output.mkdir()
    marker = output / "preserved.txt"
    marker.write_text("old")
    with pytest.raises(FileExistsError, match="never overwrite"):
        run(Path("missing"), Path("missing"), Path("missing"), output)
    assert marker.read_text() == "old"


def test_no_event_label_is_needed_for_signal_generation():
    dates = pd.bdate_range("2000-01-03", periods=550)
    a, _, _, _ = aggregate_asofs(_fits(dates, (500, 505)), dates, dates, "synthetic")
    before = a.drop(columns="analysis_seconds").copy(deep=True)
    evaluate_events(a, [dates[520]], dates, "synthetic")
    evaluate_events(a, [dates[530]], dates, "synthetic")
    pd.testing.assert_frame_equal(a.drop(columns="analysis_seconds"), before)
    assert np.isfinite(a.analysis_seconds).all()
