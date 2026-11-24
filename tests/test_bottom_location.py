from __future__ import annotations

import numpy as np
import pytest

from research.eval.bottom_calibration import SEED
from research.eval.bottom_location import (
    eligible_group_positions,
    random_baseline,
    window_metrics,
)


def test_window_metrics_calculate_distance_position_and_past_trough() -> None:
    metrics = window_metrics([1.0, 2.0, 3.0], t0=1, window=1)

    assert metrics is not None
    assert metrics["dist_to_trough"] == pytest.approx(1.0)
    assert metrics["range_pos"] == pytest.approx(0.5)
    assert metrics["in_bottom_zone"] is False
    assert metrics["trough_offset"] == -1
    assert metrics["trough_ahead"] is False
    assert metrics["within_4_weeks"] is True


def test_window_metrics_use_earliest_tied_trough_and_detect_future_trough() -> None:
    metrics = window_metrics([5.0, 6.0, 7.0, 2.0, 2.0], t0=2, window=2)

    assert metrics is not None
    assert metrics["dist_to_trough"] == pytest.approx(2.5)
    assert metrics["range_pos"] == pytest.approx(1.0)
    assert metrics["trough_offset"] == 1
    assert metrics["trough_ahead"] is True
    assert metrics["within_4_weeks"] is True


def test_flat_window_has_no_range_position() -> None:
    metrics = window_metrics([5.0] * 5, t0=2, window=2)

    assert metrics is not None
    assert metrics["dist_to_trough"] == pytest.approx(0.0)
    assert metrics["range_pos"] is None
    assert metrics["in_bottom_zone"] is None
    assert metrics["trough_offset"] == -2


def test_events_with_out_of_bounds_or_cross_split_windows_are_excluded() -> None:
    frames = [{"split": "dev"} for _ in range(5)] + [
        {"split": "cal"} for _ in range(5)
    ]
    closes = [100.0] * len(frames)

    assert eligible_group_positions(frames, closes, [1], "dev", window=2) == []
    assert eligible_group_positions(frames, closes, [3], "dev", window=2) == []


def test_random_baseline_is_reproducible_from_the_specified_seed() -> None:
    pool = {
        "index": [
            {
                "dist_to_trough": value,
                "range_pos": value,
                "in_bottom_zone": value <= 0.2,
                "trough_offset": offset,
                "trough_ahead": offset > 0,
                "within_4_weeks": abs(offset) <= 4,
            }
            for value, offset in ((0.1, -3), (0.3, 2), (0.5, 7), (0.2, 0))
        ]
    }
    event_counts = {"index": 2}

    first = random_baseline(
        pool, event_counts, np.random.default_rng(SEED), repeats=20
    )
    second = random_baseline(
        pool, event_counts, np.random.default_rng(SEED), repeats=20
    )

    assert first == second
