import numpy as np

from research.eval.bottom_calibration import (
    _random_baseline,
    _summary,
    bucket_membership,
    independent_positions,
)


def test_score_buckets_follow_the_published_boundaries():
    assert bucket_membership(29.9, False) == {
        "B0": True, "B1": True, "B2": False, "B3": False, "B4": False,
    }
    assert bucket_membership(30.0, False)["B2"] is True
    assert bucket_membership(49.9, False)["B2"] is True
    assert bucket_membership(50.0, False)["B3"] is True
    assert bucket_membership(50.0, True)["B4"] is True
    assert bucket_membership(None, True)["B0"] is True
    assert bucket_membership(None, True)["B1"] is False


def test_independent_events_skip_repeats_within_twelve_weeks():
    assert independent_positions([0, 1, 11, 12, 23, 24, 36]) == [0, 12, 24, 36]


def test_bucket_summary_separates_candidate_weeks_from_independent_events():
    rows = []
    for position in range(13):
        candidate = position in {0, 5, 12}
        rows.append({
            "candidate": candidate,
            "buckets": {"B0": candidate, "B1": candidate},
            "outcomes": {24: {"ret": 0.1 if position == 0 else -0.1}},
        })
    result = _summary({"sh000001": rows}, "B1", 24)
    assert result["n_weeks"] == 3
    assert result["n_events"] == 2
    assert result["win_rate"] == 0.5


def test_random_baseline_is_reproducible_with_fixed_seed():
    by_index = {
        "a": [
            {"candidate": True, "buckets": {"B0": True, "B1": i % 2 == 0},
             "outcomes": {24: {"ret": 0.1 if i % 3 else -0.1}}}
            for i in range(40)
        ],
        "b": [
            {"candidate": True, "buckets": {"B0": True, "B1": i % 3 == 0},
             "outcomes": {24: {"ret": 0.05 if i % 2 else -0.05}}}
            for i in range(40)
        ],
    }
    first = _random_baseline(by_index, "B1", 24, np.random.default_rng(20261124))
    second = _random_baseline(by_index, "B1", 24, np.random.default_rng(20261124))
    assert first == second
