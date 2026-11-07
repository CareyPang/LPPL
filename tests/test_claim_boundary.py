from dataclasses import replace

from research.eval.top_time.claim_boundary import (
    ClaimMachine,
    build_claims,
    classify_interval,
    formal_dates,
    integer_date_cluster,
    visible_units,
)
from research.eval.top_time.contracts import Forecast, LabelBook, Protocol, TopEvent
from research.eval.top_time.scoring import evaluate


def row(i, low=6., high=15.):
    return dict(position=i, date=f"T{i}", own_evaluable=True, own_alarm=True,
                interval_lo=low, interval_hi=high)


def test_gate_separates_early_from_late_and_inclusive_width():
    assert classify_interval(10, 16, 25) == ("FORMAL", [])
    assert classify_interval(10, 16, 26) == ("EARLY_OBSERVATION", ["width_exceeded"])
    assert classify_interval(10, 74, 75) == ("EARLY_OBSERVATION", ["beyond_horizon"])
    assert classify_interval(10, 15, 20) == ("NONFORMAL_OBSERVATION", ["insufficient_window_lead"])
    assert "not_future" in classify_interval(10, 8, 12)[1]


def test_observation_does_not_claim_episode_revision_cannot_extend_it():
    machine = ClaimMachine("s", "a")
    early, _ = machine.step(row(0, 6, 20))
    assert early["state"] == "EARLY_OBSERVATION" and not early["episode_id"]
    first, _ = machine.step(row(5))
    revision, _ = machine.step(row(10, 6, 15))
    assert first["state"] == "NEW_FORMAL"
    assert revision["state"] == "FORMAL_REVISION"
    assert revision["original_expiry"] == first["original_expiry"] == 20
    assert revision["parent_id"] == first["prediction_id"]
    later, _ = machine.step(row(21))
    assert later["state"] == "NEW_FORMAL" and later["episode_id"] != first["episode_id"]


def test_prefix_invariance_and_pairing_uses_current_candidates():
    rows = [row(i) for i in (0, 5, 10, 20, 30)]
    before = build_claims("s", "a", rows[:3])
    after = build_claims("s", "a", rows)
    assert before[0] == after[0][:3]
    assert before[1] == after[1][:3]
    second = [row(0, 1, 3), *rows[1:]]
    dates = formal_dates(rows) & formal_dates(second)
    a = build_claims("s", "a", rows, allowed_dates=dates)
    b = build_claims("s", "b", second, allowed_dates=dates)
    assert len(a[1]) == len(b[1]) == 4
    assert a[0][0]["state"] == "FORMAL_WITHHELD_BY_PAIR"
    assert a[0][1]["state"] == "NEW_FORMAL"


def test_date_cluster_generates_a_new_group_without_cropping_extent():
    records = [dict(n=30+i*5, ahead=a, scale="s", weight=.1, qualified=True)
               for i, a in enumerate([6.1, 8., 14.9, 15.1])]
    records[0]["weight"] = .2
    scales = {"s": {"denominator": 10}}
    chosen = integer_date_cluster(records, scales)
    assert chosen["lo"] == 6.1 and chosen["hi"] == 14.9
    assert chosen["members"] == (30, 35, 40)
    assert integer_date_cluster(records, scales, cross=True) is None


def book():
    return LabelBook("s", tuple(f"T{i}" for i in range(180)), 179,
                     [TopEvent("peak", "s", "stage", 90, 90, (90,), "100", 27, 132, 132)],
                     {"stage": (True,)*180, "short": (True,)*180})


def forecast(name, i, left, right):
    return Forecast(name, "continuous_episode", "s", "stage", left, right,
                    i, i, f"2020-01-{i % 28 + 1:02d}T17:00:00+08:00", i+1, "theoretical")


def test_visible_scoring_allows_first_in_h_revision_without_future_online_reset():
    # Same source episode starts outside H; later visible claim enters H.
    first = forecast("initial", 0, 6, 15)
    revision = replace(forecast("revision", 35, 87, 95), published_at="2020-02-01T17:00:00+08:00")
    old = evaluate(book(), [first, revision], mode="diagnostic")
    new = evaluate(book(), visible_units([first, revision]), mode="diagnostic")
    assert old.metrics["stage"]["TP"] == 0
    assert new.metrics["stage"]["TP"] == 1
    assert first.episode_id == revision.episode_id == "continuous_episode"


def test_visible_scoring_does_not_repair_first_wrong_claim_for_same_event():
    first = forecast("wrong", 30, 70, 79)
    later = replace(forecast("later", 35, 87, 95), published_at="2020-02-01T17:00:00+08:00")
    scored = evaluate(book(), visible_units([first, later]), mode="diagnostic", config=Protocol())
    assert scored.metrics["stage"]["TP"] == 0
    assert scored.metrics["stage"]["P"] == 2
    assert scored.metrics["diagnostics"]["duplicate_claims"] == 1
