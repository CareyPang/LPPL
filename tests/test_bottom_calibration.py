import numpy as np

from research.eval.bottom_calibration import (
    _b3_law_distributions,
    _event_rows,
    _group_contains,
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


def test_law_gate_only_includes_b3_candidate_events():
    rows = [
        {
            "candidate": True,
            "id": "b3",
            "buckets": {"B3": True},
            "laws": {"p": 0.7},
        },
        *[
            {"candidate": False, "buckets": {}, "laws": {}}
            for _ in range(11)
        ],
        {
            "candidate": True,
            "id": "b2",
            "buckets": {"B3": False, "B2": True},
            "laws": {"p": 0.9},
        },
    ]
    events = _event_rows(rows, ("gate", "p", 0.6))
    assert [event["id"] for event in events] == ["b3"]


def test_productivity_gate_and_prototype_read_productivity_ratio():
    row = {
        "buckets": {"B3": True},
        "laws": {"productivity_ratio": 0.5},
    }
    assert _group_contains(row, ("gate", "productivity", 1.0))
    assert _group_contains(row, ("prototype", "productivity", None))


def test_b3_metric_distributions_use_b3_candidate_weeks():
    observations = {
        "sh000001": {
            "dev": [
                {
                    "candidate": True,
                    "buckets": {"B3": True},
                    "laws": {"p": 0.5, "delta_m": 0.3, "productivity_ratio": 1.2},
                },
                {
                    "candidate": True,
                    "buckets": {"B3": False, "B2": True},
                    "laws": {"p": 0.9, "delta_m": 0.8, "productivity_ratio": 0.5},
                },
            ],
            "cal": [],
            "test": [],
        },
        "sh000016": {"dev": [], "cal": [], "test": []},
        "sh000300": {"dev": [], "cal": [], "test": []},
        "sh000905": {"dev": [], "cal": [], "test": []},
        "sh000688": {"dev": [], "cal": [], "test": []},
        "sz399001": {"dev": [], "cal": [], "test": []},
        "sz399006": {"dev": [], "cal": [], "test": []},
    }
    distribution = _b3_law_distributions(observations)["dev"]
    assert distribution["n_b3_candidate_weeks"] == 1
    assert distribution["p"]["count"] == 1
    assert distribution["p"]["p50"] == 0.5
    assert distribution["productivity_ratio"]["p50"] == 1.2
