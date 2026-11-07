from datetime import date, timedelta

import pytest

from research.eval.top_time.replay import (
    BASELINE,
    build_replay,
    common_event_opportunity,
    outward_interval,
)


def fixture(rows=None, arm="ref", end=19):
    sessions = [(date(2020, 1, 1)+timedelta(days=i)).isoformat() for i in range(100)]
    rows = rows if rows is not None else [(0, True, True, 5.1, 14.1), (5, True, True, 3., 8.),
                                          (10, True, False, None, None), (15, True, True, 6., 15.)]
    records = [{"symbol": "X", "arm": arm, "date": sessions[i], "position": i,
                "own_evaluable": available, "own_alarm": alarm, "status": "ok" if available else "history_insufficient",
                "interval_lo": lo, "interval_hi": hi} for i, available, alarm, lo, hi in rows]
    result = build_replay("X", sessions, records if arm != BASELINE else [],
                          scheduled_dates={sessions[i] for i in (0, 5, 10, 15)},
                          fit_dates={sessions[i] for i in (0, 5, 10, 15)}, arm=arm,
                          scope="stage", source_id="source-hash", protocol_hash="protocol-hash",
                          generated_at="2026-11-06T12:00:00Z", start_session=0, end_session=end)
    return sessions, result


def test_outward_rounding_preserves_eleven_day_and_past_edge_failures():
    assert outward_interval(100, 5.1, 14.1) == (105, 115)
    assert outward_interval(100, .01, 9.2) == (100, 110)
    with pytest.raises(ValueError):
        outward_interval(100, float("nan"), 2.)


def test_daily_ledger_does_not_invent_daily_scans_or_real_publication():
    _, result = fixture()
    assert len(result.daily) == 20
    assert len(result.runs) == 4
    assert sum(r["status"] == "NOT_SCHEDULED" for r in result.daily) == 16
    assert all(not r["original_published_at"] for r in result.daily)
    assert all(f.actionability == "theoretical" for f in result.forecasts)
    assert all(r["replay_generated_at"].startswith("2026-") for r in result.daily)
    assert result.forecasts[0].published_at.startswith("2020-")


def test_episode_expiry_is_original_and_not_reset_by_revision_or_empty_day():
    _, result = fixture()
    assert [r["claim_change"] for r in result.forecast_audit] == ["FIRST_CLAIM", "REVISION", "REVISION"]
    assert len({f.episode_id for f in result.forecasts}) == 1
    assert result.daily[15]["episode_original_expiry_session"] == 15
    _, extended = fixture(rows=[(0, True, True, 1., 4.), (5, True, True, 6., 15.)])
    assert len({f.episode_id for f in extended.forecasts}) == 2


def test_missing_saved_fit_is_not_a_no_signal_and_scopes_are_independent():
    sessions, _ = fixture()
    bundle = build_replay("X", sessions, [], scheduled_dates={sessions[0]}, fit_dates=set(),
                          arm="ref", scope="short", source_id="s", protocol_hash="p",
                          generated_at="2026-11-06T12:00:00Z", start_session=0, end_session=5)
    assert bundle.daily[0]["status"] == "NO_CACHED_FIT"
    assert bundle.runs[0].status == "FAILED"
    assert not bundle.forecasts


def test_builder_has_no_future_price_input_and_prefix_does_not_change():
    _, short = fixture(end=9)
    _, long = fixture(end=19)
    assert short.daily == long.daily[:10]
    assert short.forecasts == long.forecasts[:2]


def test_calendar_baseline_obeys_ten_inclusive_days_and_next_session_lead():
    _, result = fixture(arm=BASELINE)
    first = result.forecasts[0]
    assert first.interval_end-first.interval_start+1 == 10
    assert first.interval_start-first.action_session == 5


def test_paired_subset_checks_all_arms_without_rematching_events():
    sessions, _ = fixture()
    planned = {sessions[i] for i in (0, 5, 10, 15)}
    assert common_event_opportunity(16, sessions, scheduled_dates=planned,
                                   common_evaluable_dates=planned, first_schedule_session=0,
                                   horizon=10) == (True, "ok", 2)
    assert not common_event_opportunity(16, sessions, scheduled_dates=planned,
                                       common_evaluable_dates=planned-{sessions[10]},
                                       first_schedule_session=0, horizon=10)[0]


@pytest.mark.parametrize("value", ["False", "True", float("nan"), 0, 1])
def test_boolean_saved_statuses_must_not_be_coerced(value):
    with pytest.raises(ValueError):
        fixture(rows=[(0, value, True, 5., 10.)])


def test_saved_alarm_requires_raw_fit_identity_and_exact_calendar_mapping():
    sessions, _ = fixture()
    record = {"symbol": "X", "arm": "ref", "date": sessions[0], "position": 0,
              "own_evaluable": True, "own_alarm": True, "status": "ok", "interval_lo": 6., "interval_hi": 15.}
    args = dict(scheduled_dates={sessions[0]}, fit_dates=set(), arm="ref", scope="stage", source_id="s",
                protocol_hash="p", generated_at="2026-11-06T12:00:00Z", start_session=0, end_session=5)
    with pytest.raises(ValueError, match="missing raw fit"):
        build_replay("X", sessions, [record], **args)
    args["fit_dates"] = {sessions[0]}
    record["position"] = 1
    with pytest.raises(ValueError, match="price calendar"):
        build_replay("X", sessions, [record], **args)
