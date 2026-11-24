from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from research.eval.bottom_repair_v2_eval import (
    V2_STATES,
    _select_v2_variant,
    compute_features,
    ema,
    event_metrics,
    f4_from_volatility,
    label_window_valid,
    old50_signal,
    scores_from_features,
    select_state_positions,
)


def test_ema_seeds_with_sma_of_first_period_closes() -> None:
    values = ema([1.0, 2.0, 3.0, 4.0], period=3)

    assert np.isnan(values[0])
    assert np.isnan(values[1])
    assert values[2] == pytest.approx(2.0)
    assert values[3] == pytest.approx(3.0)


def test_a_t_uses_true_ranges_through_the_previous_session_only() -> None:
    closes = np.full(140, 100.0)
    highs = closes + 1.0
    lows = closes - 1.0
    changed_highs = highs.copy()
    position = 130
    changed_highs[position] = 10000.0

    original = compute_features(highs, lows, closes)
    changed = compute_features(changed_highs, lows, closes)

    assert original["a"][position] == pytest.approx(2.0)
    assert changed["a"][position] == pytest.approx(2.0)
    assert changed["a"][position + 1] > original["a"][position + 1]


def test_f4_zero_volatility_edges() -> None:
    assert f4_from_volatility(0.0, 0.2) == 1.0
    assert f4_from_volatility(0.0, 0.0) is None
    assert f4_from_volatility(0.1, 0.0) is None


def test_missing_feature_does_not_reweight_scores() -> None:
    scores = scores_from_features(f1=0.4, f2=None, f3=0.8, f4=0.6)
    assert scores["low_shock"] == pytest.approx(50.0)
    assert scores["short"] is None
    assert scores["medium"] is None

    missing_shock = scores_from_features(f1=0.4, f2=0.7, f3=0.8, f4=None)
    assert missing_shock == {"low_shock": None, "short": None, "medium": None}


def test_event_entry_uses_next_session_open() -> None:
    size = 140
    opens = np.full(size, 25.0)
    highs = np.full(size, 60.0)
    lows = np.full(size, 10.0)
    closes = np.full(size, 30.0)
    position = 61
    opens[position] = 9999.0
    opens[position + 1] = 20.0
    opens[position + 21] = 30.0

    metrics = event_metrics(position, opens, highs, lows, closes)

    assert metrics is not None
    assert metrics["entry_open"] == pytest.approx(20.0)
    assert metrics["R20"] == pytest.approx(0.5)


def test_label_window_cannot_cross_segment_or_data_boundary() -> None:
    labels = ["dev"] * 5 + ["cal"] * 5

    assert not label_window_valid(labels, position=3, lookback=2, forward=2)
    assert not label_window_valid(labels, position=1, lookback=2, forward=1)
    assert label_window_valid(["dev"] * 8, position=3, lookback=2, forward=2)


def test_state_cooldown_skips_only_differences_below_20_sessions() -> None:
    candidate_positions = [0, 19, 20, 39, 40]
    flags = np.ones(41, dtype=bool)

    assert select_state_positions(candidate_positions, flags) == [0, 20, 40]


def test_old50_uses_latest_frame_and_ten_calendar_day_staleness() -> None:
    frame_dates = [pd.Timestamp("2020-01-01"), pd.Timestamp("2020-01-05")]
    frame_scores = [80.0, 60.0]

    is_fresh, score = old50_signal("2020-01-15", frame_dates, frame_scores)
    is_stale, _ = old50_signal("2020-01-16", frame_dates, frame_scores)

    assert is_fresh is True
    assert score == 60.0
    assert is_stale is False


def test_v2_selection_is_json_serializable_and_uses_specified_tiebreaks() -> None:
    results = {
        state: {
            "dev": {
                "n_events": 30,
                "metrics": {"within5_60": {"value": 0.75}},
                "random_baseline": {"metrics": {"within5_60": {"median": 0.25}}},
            }
        }
        for state in V2_STATES
    }

    selection = _select_v2_variant(results)
    serialized = json.dumps(selection)

    assert selection["state"] == "V2_low_shock_70"
    assert len(selection["eligible_variants"]) == len(V2_STATES)
    assert json.loads(serialized)["state"] == selection["state"]
