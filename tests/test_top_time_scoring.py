from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from research.eval.top_time.contracts import Forecast, LabelBook, ScheduledRun, TopEvent
from research.eval.top_time.scoring import evaluate


def book(*, unknown=(), asof=200):
    events = [TopEvent("short100", "X", "short", 100, 100, (100,), "140", 90, 115, 115, "F100"),
              TopEvent("stage100", "X", "stage", 100, 100, (100,), "140", 37, 147, 147, "F100")]
    known = {s: [i <= asof for i in range(221)] for s in ("short", "stage")}
    for scale, i in unknown:
        known[scale][i] = False
    return LabelBook("X", tuple(f"T{i}" for i in range(221)), asof,
                     [e for e in events if e.available_session <= asof],
                     {s: tuple(v) for s, v in known.items()})


def forecast(pid="p", *, episode="e", scope="stage", action=95, left=100, right=109,
             published=None, actionability="verified", on_time=True):
    published = action-1 if published is None and action is not None else (94 if published is None else published)
    stamp = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=published)
    return Forecast(pid, episode, "X", scope, left, right, published, published, stamp.isoformat(),
                    action, actionability, on_time)


def test_strict_boundary_and_event_only_disagreement():
    result = evaluate(book(), [forecast(left=99, right=108)])
    assert result.metrics["stage"]["TP"] == 0
    assert result.metrics["stage"]["event_only"]["TP"] == 1
    assert "insufficient_window_lead" in result.claims[0]["failure_reasons"]
    assert evaluate(book(), [forecast()]).metrics["stage"]["TP"] == 1
    assert evaluate(book(), [forecast(right=110)]).metrics["stage"]["FP"] == 1


def test_unknown_before_event_blocks_target_without_deleting_event_denominator():
    result = evaluate(book(unknown=(("stage", 96),)), [forecast()])
    assert result.metrics["stage"]["E"] == 1
    assert result.metrics["stage"]["P"] == 0
    assert result.metrics["stage"]["FN"] == 1
    assert result.claims[0]["unknown_blocker_session"] == 96
    assert result.metadata["incomplete_scoring"]


def test_no_event_requires_whole_horizon_and_respects_action_boundary():
    labels = book()
    labels.events = []
    complete = evaluate(labels, [forecast()], start_session=90, end_session=110)
    assert complete.metrics["stage"]["P"] == 1
    labels.known["stage"] = tuple(i <= labels.asof_session and i != 150 for i in range(221))
    pending = evaluate(labels, [forecast()], start_session=90, end_session=110)
    assert pending.metrics["stage"]["P"] == 0
    assert pending.claims[0]["status"] == "pending_labels"


def test_scope_upgrade_keeps_independent_stage_clock_and_short_denominator():
    result = evaluate(book(), [forecast("s", scope="short", action=91), forecast("g", action=95)])
    assert result.metrics["short"]["TP"] == result.metrics["short"]["P"] == 1
    assert result.metrics["stage"]["TP"] == 1
    assert result.claims[1]["lead"] == 5
    assert result.metrics["family"]["successful_families_strict"] == 1
    assert result.metrics["operational"]["total_notifications"] == 2
    late = evaluate(book(), [forecast("s", scope="short", action=91), forecast("g", action=98)])
    assert late.metrics["short"]["TP"] == 1
    assert late.metrics["stage"]["TP"] == 0


def test_first_wrong_claim_cannot_be_repaired_by_revision_or_new_episode():
    result = evaluate(book(), [forecast("first", action=90, left=101, right=110),
                              forecast("revision", action=94),
                              forecast("new", episode="different", action=95)])
    assert result.metrics["stage"]["P"] == 2
    assert result.metrics["stage"]["TP"] == 0
    assert result.claims[0]["revision_hit"]
    assert result.claims[1]["is_revision"]
    assert result.claims[2]["duplicate_event"]


def test_both_short_subclaim_shares_existing_short_first_and_same_family():
    first = forecast("s", scope="short", action=90, left=101, right=110)
    result = evaluate(book(), [first, forecast("b", scope="both", action=95)])
    assert result.metrics["short"]["P"] == 1
    assert result.metrics["short"]["TP"] == 0
    assert result.metrics["stage"]["TP"] == 1
    assert result.claims[1]["short_affiliate"]["is_revision"]
    labels = book()
    labels.events.append(TopEvent("short85", "X", "short", 85, 85, (85,), "125", 75, 100, 100, "F85"))
    early = evaluate(labels, [forecast(scope="both", action=75)])
    assert early.metrics["short"]["E"] == 2
    assert early.metrics["short"]["TP"] == 1
    assert early.claims[0]["short_affiliate"]["target_family_id"] == "F100"


def test_verified_strict_and_conditional_diagnostic_are_not_conflated():
    theoretical = forecast(actionability="theoretical")
    strict = evaluate(book(), [theoretical])
    assert strict.metrics["stage"]["P"] == 1 and strict.metrics["stage"]["TP"] == 0
    conditional = evaluate(book(), [theoretical], mode="diagnostic")
    assert conditional.metrics["stage"]["TP"] == 1
    assert conditional.metadata["evidence_status"] == "CONDITIONAL_DIAGNOSTIC_NOT_PROSPECTIVE"
    unknown = evaluate(book(), [forecast(action=None)])
    assert unknown.claims[0]["status"] == "pending_action"
    assert not unknown.metadata["complete_strict_precision_established"]


def test_empty_schedule_results_do_not_remove_event_denominator():
    runs = [ScheduledRun("r1", "X", 90, "NO_SIGNAL"), ScheduledRun("r2", "X", 91, "FAILED")]
    result = evaluate(book(), [], runs)
    assert result.metrics["stage"]["E"] == result.metrics["stage"]["FN"] == 1
    assert result.metrics["operational"]["scheduled_runs"] == 2
    assert result.metrics["operational"]["on_time_runs"] == 1
    assert result.metrics["operational"]["missing_or_failed_runs"] == 1


def test_timezone_sorting_and_id_tiebreak_choose_original_claim():
    first = replace(forecast("a", action=90, left=101, right=110), published_at="2020-04-01T08:00:00+08:00")
    second = replace(forecast("b", action=95), published_at="2020-04-01T00:00:00Z")
    result = evaluate(book(), [second, first])
    assert result.claims[0]["prediction_id"] == "a"
    assert result.metrics["stage"]["TP"] == 0


def test_malformed_types_cross_symbol_duplicate_ids_and_future_labels_fail_closed():
    for forecasts in ([forecast(), forecast()], [replace(forecast(), symbol="Y")],
                      [replace(forecast(), interval_start=True)],
                      [replace(forecast(), published_at="2020-01-01")],
                      [replace(forecast(), action_session=90)]):
        with pytest.raises(ValueError):
            evaluate(book(), forecasts)
    labels = book()
    labels.events[1].available_session = 201
    with pytest.raises(ValueError):
        evaluate(labels, [])


def test_future_publication_is_retained_but_not_scored_and_bad_interval_is_a_failure():
    result = evaluate(book(), [forecast(action=211, published=210)])
    assert result.claims[0]["status"] == "not_yet_published"
    assert result.metrics["operational"]["total_notifications"] == 0
    invalid = evaluate(book(), [forecast(left=110, right=100)])
    assert invalid.metrics["stage"]["P"] == 1
    assert invalid.metrics["stage"]["TP"] == 0


def test_pre_boundary_forecast_can_be_first_for_in_range_event():
    result = evaluate(book(), [forecast(action=85)], start_session=95, end_session=105)
    assert result.metrics["stage"]["P"] == result.metrics["stage"]["TP"] == 1
    outside = evaluate(book(), [forecast(action=85)], start_session=101, end_session=120)
    assert outside.metrics["stage"]["E"] == outside.metrics["stage"]["P"] == 0


def test_unknown_label_regions_are_not_counted_as_discovered_pending_events():
    labels = book()
    labels.pending = [{"scale": "stage", "kind": "unresolved_anchor_range",
                       "start_session": 190, "end_session": 200}]
    result = evaluate(labels, [])
    assert result.metrics["stage"]["pending_events"] == 0
    assert result.metrics["stage"]["pending_label_regions"] == 1
    assert result.metadata["incomplete_scoring"]


@pytest.mark.parametrize("status,on_time", [("FAILED", True), ("NO_SIGNAL", True),
                                            ("LATE", True), ("ON_TIME_INTERVAL", False)])
def test_linked_schedule_cannot_contradict_published_prediction(status, on_time):
    f = replace(forecast(on_time=on_time), run_id="run")
    with pytest.raises(ValueError):
        evaluate(book(), [f], [ScheduledRun("run", "X", 94, status)])


def test_manual_ledger_cannot_mark_future_anchors_known():
    labels = book()
    labels.known["stage"] = (True,) * len(labels.sessions)
    with pytest.raises(ValueError):
        evaluate(labels, [])


def test_daily_close_cannot_become_a_same_session_action():
    f = replace(forecast(), data_cutoff_session=95, published_session=95)
    result = evaluate(book(), [f])
    assert result.metrics["stage"]["P"] == 1
    assert result.metrics["stage"]["TP"] == 0
    assert "same_session_daily_data_action" in result.claims[0]["failure_reasons"]


def test_unknown_outside_claim_horizon_still_limits_total_event_recall():
    result = evaluate(book(unknown=(("stage", 50),)), [forecast()])
    assert result.metrics["stage"]["TP"] == 1
    assert result.metrics["stage"]["unknown_anchors"] == 1
    assert not result.metrics["stage"]["complete_recall_denominator_established"]
    assert result.metadata["scored_claim_ledger_closed"]
    assert result.metadata["complete_strict_precision_established"]
    assert not result.metadata["complete_recall_denominator_established"]
