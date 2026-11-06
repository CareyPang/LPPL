"""Hand-scored contract cases, independent of the price-label implementation.

Expected counts come from the review's S01-S24 table, not from evaluator output.
The synthetic dates only give abstract T-sessions timezone-aware publication
timestamps; they do not stand in for an exchange calendar or market data.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from research.eval.top_time.contracts import (
    Forecast,
    LabelBook,
    Protocol,
    ScheduledRun,
    TopEvent,
)
from research.eval.top_time.scoring import evaluate

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "top_time" / "scoring_cases.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
CASES = FIXTURE["cases"]
BY_ID = {case["id"]: case for case in CASES}


def make_book(name: str) -> LabelBook:
    """Build dataclasses from explicit fixture truth, never from price labels."""
    data = FIXTURE["books"][name]
    calendar = FIXTURE["calendar"]
    origin = date.fromisoformat(calendar["origin"])
    sessions = tuple(
        (origin + timedelta(days=i)).isoformat() for i in range(calendar["session_count"])
    )
    events = []
    for event_id in data["events"]:
        row = dict(FIXTURE["events"][event_id])
        row["candidate_sessions"] = tuple(row["candidate_sessions"])
        events.append(TopEvent(**row))
    return LabelBook(
        symbol=FIXTURE["symbol"],
        sessions=sessions,
        asof_session=data["asof_session"],
        events=events,
        known={
            scale: tuple(FIXTURE["known_masks"][mask])
            for scale, mask in data["known"].items()
        },
        pending=[dict(row) for row in data["pending"]],
        metadata={"truth_source": "manual_scoring_contract_fixture"},
    )


def make_forecasts(case: dict) -> list[Forecast]:
    return [Forecast(**row) for row in case["forecasts"]]


def score_case(case: dict):
    return evaluate(
        make_book(case["book"]),
        make_forecasts(case),
        [ScheduledRun(**row) for row in case["runs"]],
        config=Protocol(**FIXTURE["protocol"]),
        mode="strict",
        start_session=0,
        end_session=None,
    )


def assert_fields(actual: dict, expected: dict, context: str) -> None:
    for key, value in expected.items():
        assert key in actual, f"{context}: missing output field {key!r}"
        assert actual[key] == value, f"{context}.{key}: {actual[key]!r} != {value!r}"


def test_fixture_is_complete_manual_truth_with_explicit_maturity_masks():
    assert [case["id"] for case in CASES] == [f"S{i:02d}" for i in range(1, 25)]
    assert FIXTURE["evidence_status"] == "MANUAL_CONTRACT_FIXTURE_NOT_MODEL_PERFORMANCE"
    assert FIXTURE["protocol"] == {"stage_right": 21, "require_stage_rise": False}
    # Old hand-scored T126 maturity must not silently alter the research default.
    assert Protocol().stage_right == 42
    for mask in FIXTURE["known_masks"].values():
        assert len(mask) == 201
        assert all(type(value) is bool for value in mask)
    for name in FIXTURE["books"]:
        book = make_book(name)
        assert all(event.available_session <= book.asof_session for event in book.events)
        for mask in book.known.values():
            assert not any(mask[book.asof_session + 1 :])
    assert make_book("PENDING_AT_110").known["short"][100] is False
    assert make_book("PENDING_AT_110").known["stage"][100] is False
    assert make_book("PENDING_STAGE_AT_120").known["short"][100] is True
    assert make_book("PENDING_STAGE_AT_120").known["stage"][100] is False


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_hand_scored_s01_through_s24(case):
    result = score_case(case)
    expected = case["expected"]
    assert_fields(result.metrics["stage"], expected["stage"], f"{case['id']}.stage")
    assert_fields(
        result.metrics["stage"]["event_only"],
        expected["event_only_stage"],
        f"{case['id']}.stage.event_only",
    )
    for section in ("short", "diagnostics", "family"):
        if section in expected:
            assert_fields(result.metrics[section], expected[section], f"{case['id']}.{section}")
    claims = {claim["prediction_id"]: claim for claim in result.claims}
    for prediction_id, fields in expected.get("claims", {}).items():
        assert prediction_id in claims
        assert_fields(claims[prediction_id], fields, f"{case['id']}.{prediction_id}")
    stage = result.metrics["stage"]
    if expected["stage"]["P"] == 0:
        assert stage["precision"] is None, "No issued mature stage claim means NA, not 0 or 1."
    if expected["stage"]["E"] == 0:
        assert stage["recall"] is None, "No mature stage event means NA, not perfect recall."


@pytest.mark.parametrize(
    ("case_id", "short_events"),
    [("S14", 0), ("S15", 1)],
)
def test_pending_stage_is_not_relabelled_as_mature_absence(case_id, short_events):
    result = score_case(BY_ID[case_id])
    assert result.metrics["stage"]["pending_events"] == 1
    assert result.metrics["short"]["E"] == short_events
    assert result.metrics["diagnostics"]["pending_claims"] == 1
    assert_fields(result.metrics["stage"], {"E": 0, "P": 0, "TP": 0, "FN": 0}, case_id)


@pytest.mark.parametrize(
    ("case_id", "expected"),
    [
        (
            "S11",
            {"scheduled_runs": 6, "on_time_runs": 6, "completed_runs": 6,
             "missing_or_failed_runs": 0, "status_counts": {"NO_SIGNAL": 6}},
        ),
        (
            "S12",
            {"scheduled_runs": 6, "on_time_runs": 0, "completed_runs": 0,
             "missing_or_failed_runs": 6, "status_counts": {"FAILED": 3, "MISSED_RUN": 3}},
        ),
    ],
)
def test_operational_failures_and_no_signal_keep_the_scheduled_denominator(case_id, expected):
    result = score_case(BY_ID[case_id])
    assert_fields(result.metrics["operational"], expected, case_id)
    assert_fields(result.metrics["stage"], {"E": 1, "P": 0, "TP": 0, "FN": 1}, case_id)


@pytest.mark.parametrize("case_id", ["S05", "S13", "S24"])
def test_first_alert_is_chronological_not_whichever_row_is_scored_first(case_id):
    case = BY_ID[case_id]
    result = evaluate(
        make_book(case["book"]),
        list(reversed(make_forecasts(case))),
        config=Protocol(**FIXTURE["protocol"]),
    )
    assert_fields(result.metrics["stage"], case["expected"]["stage"], f"{case_id}.reversed")
    claims = {claim["prediction_id"]: claim for claim in result.claims}
    for prediction_id, fields in case["expected"].get("claims", {}).items():
        assert_fields(claims[prediction_id], fields, f"{case_id}.reversed.{prediction_id}")
    if case_id == "S13":
        assert claims["S13-first"]["strict_hit"] is True
        assert claims["S13-duplicate"]["duplicate_event"] is True
        assert claims["S13-duplicate"]["strict_hit"] is False


def test_renaming_stage_revision_to_both_does_not_reset_the_stage_clock():
    forecasts = make_forecasts(BY_ID["S05"])
    forecasts[1] = replace(forecasts[1], scope="both")
    result = evaluate(make_book("F100"), forecasts, config=Protocol(**FIXTURE["protocol"]))
    assert_fields(result.metrics["stage"], {"E": 1, "P": 1, "TP": 0, "FN": 1}, "stage-to-both")
    revision = next(row for row in result.claims if row["prediction_id"] == "S05-revision")
    assert revision["is_revision"] is True
    assert revision["revision_hit"] is True


def test_unknown_anchor_before_known_peak_blocks_next_event_selection():
    book = make_book("F100")
    stage_known = list(book.known["stage"])
    stage_known[90] = False
    book.known = {**book.known, "stage": tuple(stage_known)}
    # A85 -> unknown T90 -> known F100: F100 is not provably the next event.
    result = evaluate(book, make_forecasts(BY_ID["S02"]), config=Protocol(**FIXTURE["protocol"]))
    assert_fields(result.metrics["stage"], {"E": 1, "P": 0, "TP": 0, "FN": 1}, "unknown-before")
    assert result.metrics["diagnostics"]["pending_claims"] == 1


def test_unknown_unclaimed_anchors_leave_recall_denominator_incomplete():
    book = make_book("F100")
    stage_known = list(book.known["stage"])
    stage_known[50] = False
    book.known = {**book.known, "stage": tuple(stage_known)}
    result = evaluate(book, make_forecasts(BY_ID["S01"]), config=Protocol(**FIXTURE["protocol"]))
    # The unknown T50 cannot affect the A95 claim's next target, but can hide
    # additional stage events in the evaluation's deployment-wide denominator.
    assert_fields(result.metrics["stage"], {"E": 1, "P": 1, "TP": 1, "FN": 0}, "coverage")
    assert result.metrics["stage"]["known_anchors"] == 200
    assert result.metrics["stage"]["unknown_anchors"] == 1
    assert result.metrics["stage"]["complete_recall_denominator_established"] is False
    assert result.metadata["scored_claim_ledger_closed"] is True
    assert result.metadata["complete_recall_denominator_established"] is False
    assert result.metadata["incomplete_scoring"] is True


def test_unknown_in_no_event_horizon_is_not_a_false_positive():
    book = make_book("NO_EVENTS")
    stage_known = list(book.known["stage"])
    stage_known[120] = False
    book.known = {**book.known, "stage": tuple(stage_known)}
    result = evaluate(book, make_forecasts(BY_ID["S17"]), config=Protocol(**FIXTURE["protocol"]))
    assert_fields(result.metrics["stage"], {"E": 0, "P": 0, "TP": 0, "FN": 0}, "unknown-absence")
    assert result.metrics["diagnostics"]["pending_claims"] == 1


def test_claim_actionable_on_inclusive_range_end_remains_pending():
    book = make_book("NO_EVENTS")
    forecast = replace(
        make_forecasts(BY_ID["S17"])[0],
        prediction_id="last-session-claim",
        episode_id="last-session-episode",
        interval_start=205,
        interval_end=214,
        data_cutoff_session=199,
        published_session=199,
        published_at=f"{book.sessions[199]}T17:00:00+08:00",
        action_session=200,
    )
    result = evaluate(book, [forecast], config=Protocol(**FIXTURE["protocol"]), end_session=200)
    assert_fields(result.metrics["stage"], {"E": 0, "P": 0, "TP": 0, "FN": 0}, "inclusive-end")
    assert result.metrics["stage"]["issued_claims"] == 1
    assert result.metrics["diagnostics"]["pending_claims"] == 1
    assert result.metadata["incomplete_scoring"] is True


def test_interval_cannot_skip_an_earlier_stage_event_to_choose_a_hit():
    book = make_book("F85_AND_F100")
    later = next(event for event in book.events if event.scale == "stage")
    book.events.append(
        replace(
            later,
            event_id="stage-F85",
            peak_session=85,
            end_session=85,
            candidate_sessions=(85,),
            support_start=22,
            support_end=111,
            available_session=111,
            family_id="F85",
        )
    )
    result = evaluate(book, make_forecasts(BY_ID["S18"]), config=Protocol(**FIXTURE["protocol"]))
    assert_fields(result.metrics["stage"], {"E": 2, "P": 1, "TP": 0, "FN": 2}, "next-stage")
    claim = next(row for row in result.claims if row["prediction_id"] == "S18-first")
    assert claim["target_event_id"] == "stage-F85"
    assert claim["target_family_id"] == "F85"


def test_correct_stage_anchor_is_not_overstatement_of_another_short_peak():
    book = make_book("F100")
    short = next(event for event in book.events if event.scale == "short")
    book.events.append(
        replace(
            short,
            event_id="short-F91",
            peak_session=91,
            end_session=91,
            candidate_sessions=(91,),
            support_start=81,
            support_end=106,
            available_session=106,
            family_id="F91",
        )
    )
    # NEXT_STAGE_FAMILY legitimately points to T100. The same ten-day interval
    # also containing a different short-only T91 does not change its scope.
    result = evaluate(book, make_forecasts(BY_ID["S02"]), config=Protocol(**FIXTURE["protocol"]))
    assert_fields(result.metrics["stage"], {"E": 1, "P": 1, "TP": 1, "FN": 0}, "stage-scope")
    assert result.metrics["diagnostics"]["overstatement_count"] == 0
    claim = next(row for row in result.claims if row["prediction_id"] == "S02-first")
    assert claim["target_family_id"] == "F100"
    assert claim["overstatement"] is False


def test_future_publication_is_not_visible_to_asof_scoring():
    book = make_book("PENDING_STAGE_AT_120")
    forecast = replace(
        make_forecasts(BY_ID["S01"])[0],
        prediction_id="future-publication",
        episode_id="future-episode",
        interval_start=135,
        interval_end=144,
        data_cutoff_session=129,
        published_session=129,
        published_at=f"{book.sessions[129]}T17:00:00+08:00",
        action_session=130,
    )
    result = evaluate(book, [forecast], config=Protocol(**FIXTURE["protocol"]))
    assert_fields(result.metrics["stage"], {"E": 0, "P": 0, "TP": 0, "FN": 0}, "future-pub")
    assert result.metrics["diagnostics"]["total_notifications"] == 0
    assert not any(row["strict_hit"] for row in result.claims)


def test_future_label_cannot_be_smuggled_into_a_mature_event_book():
    book = make_book("PENDING_STAGE_AT_120")
    future_stage = next(event for event in make_book("F100").events if event.scale == "stage")
    book.events.append(future_stage)  # T126 availability cannot be read at asof T120.
    with pytest.raises(ValueError):
        evaluate(book, make_forecasts(BY_ID["S15"]), config=Protocol(**FIXTURE["protocol"]))


def test_missing_action_time_is_pending_action_not_a_fabricated_early_alert():
    forecast = replace(make_forecasts(BY_ID["S01"])[0], action_session=None, actionability="unknown")
    result = evaluate(make_book("F100"), [forecast], config=Protocol(**FIXTURE["protocol"]))
    assert_fields(result.metrics["stage"], {"E": 1, "P": 0, "TP": 0, "FN": 1}, "unknown-action")
    assert result.metrics["diagnostics"]["pending_action"] == 1
    assert result.metrics["diagnostics"]["total_notifications"] == 1


def test_new_episode_after_unknown_first_action_cannot_establish_complete_scores():
    later = make_forecasts(BY_ID["S01"])[0]
    first = replace(
        later,
        prediction_id="unknown-first-action",
        episode_id="unknown-first-episode",
        data_cutoff_session=89,
        published_session=89,
        published_at=f"{make_book('F100').sessions[89]}T17:00:00+08:00",
        action_session=None,
        actionability="unknown",
    )
    result = evaluate(make_book("F100"), [first, later], config=Protocol(**FIXTURE["protocol"]))
    # The unknown claim cannot be assigned a target by guessing its action day.
    # A known-subset result must still disclose the unresolved original claim.
    assert result.metrics["diagnostics"]["pending_action"] == 1
    assert result.metrics["diagnostics"]["total_notifications"] == 2
    assert result.metadata["incomplete_scoring"] is True
    assert result.metadata["complete_strict_precision_established"] is False


def test_theoretical_actionability_cannot_receive_strict_success():
    forecast = replace(make_forecasts(BY_ID["S01"])[0], actionability="theoretical")
    result = evaluate(make_book("F100"), [forecast], config=Protocol(**FIXTURE["protocol"]))
    assert_fields(result.metrics["stage"], {"E": 1, "P": 1, "TP": 0, "FN": 1}, "theoretical-action")


def test_publication_timestamp_must_be_timezone_aware():
    forecast = replace(make_forecasts(BY_ID["S01"])[0], published_at="2020-04-04T17:00:00")
    with pytest.raises(ValueError):
        evaluate(make_book("F100"), [forecast], config=Protocol(**FIXTURE["protocol"]))


def test_publication_calendar_day_must_match_published_session():
    forecast = replace(make_forecasts(BY_ID["S01"])[0], published_at="2020-01-02T17:00:00+08:00")
    with pytest.raises(ValueError):
        evaluate(make_book("F100"), [forecast], config=Protocol(**FIXTURE["protocol"]))
