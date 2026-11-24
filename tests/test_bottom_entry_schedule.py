from __future__ import annotations

import pytest

from research.eval.bottom_entry_schedule import (
    eligible_event_positions,
    evaluate_strategy,
    first_confirmation_position,
    maximum_drawdown,
    resolve_buy_position,
)


def test_s_fixed_uses_30_30_40_weights_at_weeks_zero_four_and_eight() -> None:
    closes = [100.0] * 51
    closes[4] = 90.0
    closes[8] = 80.0
    closes[50] = 110.0

    result = evaluate_strategy("S_fixed", closes, 0)

    expected_value = 0.3 * 110 / 100 + 0.3 * 110 / 90 + 0.4 * 110 / 80
    assert result["total_return"] == pytest.approx(expected_value - 1)
    assert result["invested_fraction"] == pytest.approx(1.0)


def test_confirmation_uses_only_closes_through_candidate_week() -> None:
    closes = [100.0] * 51
    closes[10] = 110.0
    changed_after_confirmation = closes.copy()
    changed_after_confirmation[11:] = [1000.0] * 40

    assert first_confirmation_position(closes, 0) == 10
    assert first_confirmation_position(changed_after_confirmation, 0) == 10


def test_no_confirmation_leaves_only_probe_invested() -> None:
    closes = [100.0] * 51

    result = evaluate_strategy("S_confirm", closes, 0, confirmation_position=None)

    assert result["invested_fraction"] == pytest.approx(0.3)
    assert result["total_return"] == pytest.approx(0.0)
    assert result["average_capital_occupied"] == pytest.approx(0.3)
    assert evaluate_strategy(
        "S_confirm_full", closes, 0, confirmation_position=None
    )["invested_fraction"] == pytest.approx(0.0)


def test_maximum_drawdown_uses_running_peak() -> None:
    assert maximum_drawdown([1.0, 1.2, 0.9, 1.1, 0.8]) == pytest.approx(1 - 0.8 / 1.2)


def test_event_crossing_segment_boundary_is_excluded() -> None:
    frames = [{"split": "dev"} for _ in range(60)] + [
        {"split": "cal"} for _ in range(60)
    ]
    closes = [100.0] * len(frames)

    assert eligible_event_positions(frames, closes, [10], "dev") == []


def test_empty_scheduled_close_defers_purchase_to_next_nonempty_week() -> None:
    closes = [100.0, None, None, 95.0, 96.0]

    assert resolve_buy_position(closes, planned_position=1, end_position=4) == 3
