from __future__ import annotations

import inspect
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from research.eval.top_time.claim_boundary import classify_interval
from research.eval.top_time.contracts import (
    LABEL_VERSION,
    SCORING_CONTRACT_VERSION,
    LabelBook,
    LabelState,
    Protocol,
    TopEvent,
)
from research.eval.top_time.labels import build_labels
from research.eval.top_time.t02 import (
    AppendOnlyClaimLedger,
    action_session_after_close,
    formal_interval_gate,
    score_t02,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "top_time_t02" / "hand_cases.json")
    .read_text(encoding="utf-8")
)
CASES = {case["id"]: case for case in FIXTURE["cases"]}


def _event(scope: str, peak: int, event_id: str | None = None) -> TopEvent:
    return TopEvent(
        event_id or f"{scope}-{peak}",
        "X",
        scope,
        peak,
        peak,
        (peak,),
        "100",
        peak - 2,
        peak + 2,
        peak + 2,
        label_available_session=peak + 2,
        label_version=LABEL_VERSION,
    )


def _book(*events: TopEvent, unknown: tuple[tuple[str, int], ...] = (), n: int = 140) -> LabelBook:
    sessions = tuple((date(2020, 1, 1) + timedelta(days=i)).isoformat() for i in range(n))
    states = {scope: [LabelState.NO_EVENT] * n for scope in ("short", "stage")}
    known = {scope: [True] * n for scope in ("short", "stage")}
    for event in events:
        states[event.scale][event.peak_session] = LabelState.MATURE_EVENT
    for scope, session in unknown:
        states[scope][session] = LabelState.UNKNOWN
        known[scope][session] = False
    return LabelBook(
        "X",
        sessions,
        n - 1,
        list(events),
        {scope: tuple(values) for scope, values in known.items()},
        states={scope: tuple(values) for scope, values in states.items()},
    )


def _claim(
    claim_id: str,
    *,
    episode: str = "episode-1",
    scope: str = "stage",
    action: int = 45,
    interval: tuple[int, int] = (50, 59),
    kind: str = "new",
    parent: str | None = None,
    first_interval: tuple[int, int] | None = None,
    first_clock: int | None = None,
    expiry: int | None = None,
) -> dict:
    first = first_interval or interval
    clock = action if first_clock is None else first_clock
    return {
        "claim_id": claim_id,
        "parent_claim_id": parent,
        "episode_id": episode,
        "kind": kind,
        "scope": scope,
        "interval_start": interval[0],
        "interval_end": interval[1],
        "first_interval_start": first[0],
        "first_interval_end": first[1],
        "first_clock_session": clock,
        "fixed_expiry_session": action + 63 if expiry is None else expiry,
        "action_session": action,
        "mode": "historical_replay",
        "first_visible_at": None,
        "simulated_available_at": action - 1,
        "simulated_action_session": action,
        "delay_assumption": "saved full-close value available at close; action next session",
    }


@pytest.mark.parametrize("case_id", ["lead_4", "lead_5", "width_10", "width_11"])
def test_hand_geometry_cases_match_written_expectations(case_id):
    case = CASES[case_id]
    result = formal_interval_gate(
        case["action_session"], case["interval_start"], case["interval_end"]
    )
    legacy_status, _ = classify_interval(
        case["action_session"] - 1, case["interval_start"], case["interval_end"]
    )
    assert result["formal"] is (legacy_status == "FORMAL")
    assert result["formal"] is case["expected"]["formal"]
    if not result["formal"]:
        assert case["expected"]["primary_cause"] in {
            "insufficient_lead" if "insufficient_lead" in result["reasons"] else "",
            "too_wide" if "too_wide" in result["reasons"] else "",
        }
    assert result["inclusive_width"] == case["interval_end"] - case["interval_start"] + 1


def test_late_action_cannot_claim_a_past_event():
    case = CASES["late_action"]
    book = _book(_event("stage", case["event_session"]))
    ledger = AppendOnlyClaimLedger()
    ledger.append(_claim(
        "late", action=case["action_session"],
        interval=(case["interval_start"], case["interval_end"]),
    ))
    result = score_t02(book, ledger)["scopes"]["stage"]
    assert result["metrics"]["no_formal_alert_rate"] == 1
    assert result["claims"][0]["target_status"] == "no_event"


def test_reversed_interval_is_rejected_as_geometry():
    result = formal_interval_gate(45, 60, 59)
    assert result["formal"] is False
    assert result["reasons"] == ["reversed"]


def test_first_wrong_window_cannot_be_rescued_by_revision():
    case = CASES["wrong_first_then_revision"]
    ledger = AppendOnlyClaimLedger()
    ledger.append(_claim(
        "first",
        action=case["action_session"],
        interval=(case["interval_start"], case["interval_end"]),
    ))
    ledger.append(_claim(
        "revision",
        action=50,
        interval=tuple(case["revision_interval"]),
        kind="revision",
        parent="first",
        first_interval=(case["interval_start"], case["interval_end"]),
        first_clock=case["action_session"],
        expiry=case["action_session"] + 63,
    ))
    result = score_t02(_book(_event("stage", case["event_session"])), ledger)["scopes"]["stage"]
    assert result["events"][0]["first_window_covered"] is case["expected"]["first_window_covered"]
    assert result["events"][0]["strict_success"] is case["expected"]["strict_success"]
    assert result["metrics"]["revisions"] == case["expected"]["revisions"]


def test_short_and_stage_use_independent_clocks_and_targets():
    case = CASES["local_early_stage_late"]
    ledger = AppendOnlyClaimLedger()
    ledger.append(_claim(
        "short", episode="short-episode", scope="short",
        action=case["short_action_session"], interval=(50, 59),
    ))
    ledger.append(_claim(
        "stage", episode="stage-episode", scope="stage",
        action=case["stage_action_session"], interval=(80, 89),
    ))
    result = score_t02(
        _book(_event("short", case["short_event_session"]),
              _event("stage", case["stage_event_session"])),
        ledger,
    )
    assert result["scopes"]["short"]["events"][0]["strict_success"] is case["expected"]["short_success"]
    assert result["scopes"]["stage"]["events"][0]["strict_success"] is case["expected"]["stage_success"]
    assert result["scopes"]["stage"]["claims"][0]["action_session"] == case["expected"]["stage_first_clock"]


def test_new_episode_cannot_rescue_an_event_already_claimed_by_first_episode():
    case = CASES["episode_switch"]
    ledger = AppendOnlyClaimLedger()
    ledger.append(_claim(
        "first", episode="episode-1", action=case["action_session"],
        interval=tuple(case["first_interval"]),
    ))
    ledger.append(_claim(
        "second", episode="episode-2", action=case["second_action_session"],
        interval=tuple(case["second_interval"]),
    ))
    result = score_t02(_book(_event("stage", case["event_session"])), ledger)["scopes"]["stage"]
    assert result["events"][0]["first_window_covered"] is case["expected"]["first_window_covered"]
    assert result["events"][0]["strict_success"] is case["expected"]["strict_success"]
    assert result["metrics"]["duplicate_notices"] == case["expected"]["duplicate_notices"]


def test_unknown_anchor_blocks_later_same_scope_event():
    case = CASES["unknown_anchor"]
    ledger = AppendOnlyClaimLedger()
    ledger.append(_claim(
        "blocked", action=case["action_session"],
        interval=(case["interval_start"], case["interval_end"]),
    ))
    result = score_t02(
        _book(_event("stage", case["event_session"]),
              unknown=(("stage", case["unknown_session"]),)),
        ledger,
    )["scopes"]["stage"]
    assert result["claims"][0]["target_status"] == case["expected"]["target_status"]
    assert result["events"][0]["strict_success"] is case["expected"]["strict_success"]


def test_resolved_no_event_and_data_failure_denominators_are_explicit():
    no_event = CASES["no_event"]
    ledger = AppendOnlyClaimLedger()
    ledger.append(_claim(
        "empty", action=no_event["action_session"],
        interval=(no_event["interval_start"], no_event["interval_end"]),
    ))
    result = score_t02(_book(), ledger)["scopes"]["stage"]
    assert result["claims"][0]["target_status"] == no_event["expected"]["target_status"]
    assert result["metrics"]["resolved_claims_denominator"] == no_event["expected"]["resolved_claims_denominator"]
    empty = score_t02(_book(), [])["scopes"]["stage"]["metrics"]
    assert empty["E"] == 0
    assert empty["no_formal_alert_rate"] is None
    assert empty["strict_stage_miss_rate"] is None

    failure = CASES["data_failure"]
    result = score_t02(
        _book(_event("stage", failure["event_session"])),
        [],
        data_evaluable_event_ids=set(),
    )["scopes"]["stage"]
    assert result["metrics"]["E"] == failure["expected"]["E"]
    assert result["metrics"]["no_formal_alert_rate"] == failure["expected"]["no_formal_alert_rate"]
    assert result["metrics"]["data_evaluable_subset"]["E"] == failure["expected"]["subset_E"]
    assert result["metrics"]["data_evaluable_subset"]["StrictStageRecall5W10"] is None


def test_append_only_ledger_rejects_mutation_and_requires_historical_vintage_fields():
    ledger = AppendOnlyClaimLedger()
    row = _claim("sealed")
    returned = ledger.append(row)
    with pytest.raises(TypeError):
        returned["interval_start"] = 9
    changed_copy = ledger.to_list()
    changed_copy[0]["interval_start"] = 9
    assert ledger.to_list()[0]["interval_start"] == 50
    with pytest.raises(ValueError, match="already exists"):
        ledger.append(row)
    with pytest.raises(TypeError, match="append-only"):
        ledger.update("sealed", interval_start=9)
    assert ledger.rows[0]["first_visible_at"] is None
    assert ledger.rows[0]["vintage_status"] == "HISTORICAL_VINTAGE_NOT_ESTABLISHED"
    with pytest.raises(ValueError, match="delay_assumption"):
        AppendOnlyClaimLedger().append({
            **_claim("bad", episode="bad-episode"),
            "delay_assumption": "",
        })


def test_forward_delivery_evidence_and_close_cutoff_are_required():
    sessions = tuple((date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(10))
    assert action_session_after_close(sessions, 4) == 5
    row = _claim("forward")
    row.update(
        mode="forward",
        action_session=5,
        first_clock_session=5,
        fixed_expiry_session=68,
        first_visible_at="2024-01-05T17:01:00+08:00",
        delivery_evidence="delivery-log:row-1",
        published_session=4,
        published_session_close_at="2024-01-05T15:00:00+08:00",
        full_close_data=True,
    )
    with pytest.raises(ValueError, match="next session"):
        AppendOnlyClaimLedger().append({**row, "action_session": 4, "first_clock_session": 4})
    assert AppendOnlyClaimLedger().append({**row, "action_session": 5})["first_visible_at"]
    with pytest.raises(ValueError, match="delivery evidence"):
        AppendOnlyClaimLedger().append({**row, "delivery_evidence": ""})
    with pytest.raises(ValueError, match="before the session close"):
        AppendOnlyClaimLedger().append({
            **row,
            "first_visible_at": "2024-01-05T14:59:00+08:00",
        })


def test_future_data_only_matures_pending_label_and_does_not_change_sealed_claims():
    config = Protocol(
        short_left=1, short_right=1, stage_left=2, stage_right=2,
        merge_gap=1, trough_left=1, trough_right=1,
        rise_min=2, rise_max=6, require_stage_rise=False,
    )
    sessions = tuple((date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(41))
    prices = [50 + max(0, 10 - abs(i - 20)) for i in range(41)]
    pending = build_labels("X", sessions, prices, config=config, asof_session=21)
    mature = build_labels("X", sessions, prices, config=config, asof_session=40)
    assert pending.state_at("stage", 20) is LabelState.PENDING
    assert mature.state_at("stage", 20) is LabelState.MATURE_EVENT
    for i in range(22):
        if pending.state_at("stage", i) != mature.state_at("stage", i):
            assert pending.state_at("stage", i) is LabelState.PENDING

    ledger = AppendOnlyClaimLedger()
    ledger.append(_claim("sealed", action=10, interval=(15, 24)))
    before = ledger.to_list()
    score_t02(pending, ledger)
    score_t02(mature, ledger)
    assert ledger.to_list() == before
    assert "score" not in inspect.signature(AppendOnlyClaimLedger.append).parameters
    with pytest.raises(ValueError, match="missing fields"):
        ledger.append(score_t02(mature, ledger))


def test_t02_contract_version_and_manual_fixture_identity_are_frozen():
    assert SCORING_CONTRACT_VERSION == FIXTURE["scoring_contract_version"]
    assert len(FIXTURE["cases"]) == 11
    assert all(isinstance(case.get("reason"), str) and case["reason"] for case in FIXTURE["cases"])


def test_legacy_known_mask_maps_to_distinct_pending_and_unknown_states():
    book = LabelBook(
        "X",
        ("2024-01-01", "2024-01-02", "2024-01-03"),
        2,
        [],
        {"short": (True, False, False), "stage": (True, False, False)},
        pending=[{
            "scale": "short",
            "kind": "unresolved_anchor_range",
            "start_session": 1,
            "end_session": 1,
            "reason": "UNMATURED_RIGHT_CONTEXT",
        }],
    )
    assert book.states["short"] == (
        LabelState.NO_EVENT, LabelState.PENDING, LabelState.UNKNOWN,
    )
    assert book.states["stage"][1] is LabelState.UNKNOWN


def test_observation_interval_is_kept_full_width_and_event_maturity_fields_exist():
    ledger = AppendOnlyClaimLedger()
    observation = _claim("wide-observation", interval=(50, 64), kind="observation")
    ledger.append(observation)
    stored = ledger.to_list()[0]
    assert (stored["interval_start"], stored["interval_end"]) == (50, 64)
    event = _event("stage", 60)
    assert event.support_end == 62
    assert event.label_available_session == 62
    assert event.label_version == LABEL_VERSION
    assert "fit_window" not in inspect.signature(build_labels).parameters


def test_observations_append_without_changing_the_first_formal_claim():
    ledger = AppendOnlyClaimLedger()
    ledger.append(_claim(
        "observation-before-formal",
        action=5,
        interval=(20, 34),
        kind="observation",
    ))
    ledger.append(_claim(
        "formal",
        action=6,
        interval=(12, 21),
        kind="formal",
        parent="observation-before-formal",
        first_clock=6,
        expiry=21,
    ))
    ledger.append(_claim(
        "observation-after-formal",
        action=7,
        interval=(13, 23),
        kind="observation",
        parent="formal",
        first_interval=(12, 21),
        first_clock=6,
        expiry=21,
    ))
    ledger.append(_claim(
        "revision-after-observation",
        action=8,
        interval=(13, 22),
        kind="revision",
        parent="observation-after-formal",
        first_interval=(12, 21),
        first_clock=6,
        expiry=21,
    ))
    assert ledger.to_list()[-1]["first_interval_start"] == 12
