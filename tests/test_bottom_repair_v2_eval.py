from __future__ import annotations

import csv
import gzip
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from research.eval.bottom_repair_v2_eval import (
    BOOLEAN_METRICS,
    LEDGER_COLUMNS,
    METRIC_NAMES,
    SEGMENTS,
    STATES,
    V2_STATES,
    _bootstrap_difference,
    _random_baselines_by_state,
    _select_v2_variant,
    compute_features,
    ema,
    event_metrics,
    f4_from_volatility,
    label_window_after_sample_start,
    label_window_valid,
    old50_signal,
    report_without_event_rows,
    scores_from_features,
    select_state_positions,
    write_event_ledger,
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


def test_label_window_must_start_on_or_after_first_weekly_frame() -> None:
    dates = list(pd.date_range("2000-01-01", periods=8))

    assert not label_window_after_sample_start(
        dates,
        position=3,
        sample_start=dates[2],
        lookback=2,
        forward=2,
    )
    assert label_window_after_sample_start(
        dates,
        position=3,
        sample_start=dates[1],
        lookback=2,
        forward=2,
    )


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


def test_head_to_head_bootstrap_uses_joint_calendar_quarter_blocks() -> None:
    left_by_index = {
        "sh000001": [
            {"date": "2020-01-10", "metrics": {"within5_60": True}},
            {"date": "2020-03-10", "metrics": {"within5_60": False}},
        ],
        "sz399001": [{"date": "2020-04-10", "metrics": {"within5_60": True}}],
    }
    right_by_index = {
        "sh000016": [{"date": "2020-04-20", "metrics": {"within5_60": False}}],
    }

    result = _bootstrap_difference(
        left_by_index,
        right_by_index,
        "within5_60",
        np.random.default_rng(20261124),
        repeats=100,
    )

    assert result["difference"] == pytest.approx(2 / 3)
    assert result["left_events"] == 3
    assert result["right_events"] == 1
    assert result["quarter_blocks"] == 2
    assert result["valid_draws"] + result["skipped_draws"] == 100
    assert result["valid_draws"] > 0
    assert result["skipped_draws"] > 0


def test_test_segment_events_do_not_change_dev_random_baselines() -> None:
    def make_event(value: int) -> dict[str, object]:
        return {
            "metrics": {
                name: bool(value % 2) if name in BOOLEAN_METRICS else value / 100.0
                for name in METRIC_NAMES
            }
        }

    def make_events_by_state(test_event_count: int):
        events_by_state = {
            state: {segment: {"sh000001": []} for segment in SEGMENTS} for state in STATES
        }
        for segment in SEGMENTS:
            events_by_state["B0"][segment]["sh000001"] = [make_event(value) for value in range(10)]
        events_by_state[STATES[0]]["dev"]["sh000001"] = [
            make_event(20),
            make_event(21),
        ]
        events_by_state[STATES[0]]["test"]["sh000001"] = [
            make_event(value) for value in range(30, 30 + test_event_count)
        ]
        events_by_state[STATES[1]]["dev"]["sh000001"] = [
            make_event(40),
            make_event(41),
        ]
        return events_by_state

    original = _random_baselines_by_state(make_events_by_state(2), repeats=5)
    changed_test = _random_baselines_by_state(make_events_by_state(4), repeats=5)

    assert original[STATES[1]]["dev"] == changed_test[STATES[1]]["dev"]


def _sample_ledger_events() -> list[dict[str, object]]:
    metrics = {
        "entry_open": 12.5,
        "R5": 0.05,
        "R10": 0.1,
        "R20": 0.2,
        "R60": 0.3,
        "win_R20": True,
        "MAE20": -0.1,
        "entry_dist_20": 0.02,
        "within5_20": True,
        "range_pos_20": 0.1,
        "in_zone_20": True,
        "low_offset_20": -2,
        "entry_dist_60": 0.03,
        "within5_60": True,
        "range_pos_60": None,
        "in_zone_60": None,
        "low_offset_60": 4,
    }
    return [
        {
            "state": "V2_low_shock_50",
            "segment": "test",
            "symbol": "sh000001",
            "date": "2023-01-05",
            "score": 75.0,
            "metrics": metrics,
        },
        {
            "state": "B0",
            "segment": "dev",
            "symbol": "sh000300",
            "date": "2018-01-03",
            "score": None,
            "metrics": metrics,
        },
    ]


def test_event_ledger_writer_is_deterministic(tmp_path) -> None:
    events = _sample_ledger_events()
    first_path = tmp_path / "first.csv.gz"
    second_path = tmp_path / "second.csv.gz"

    first_reference = write_event_ledger(events, first_path)
    second_reference = write_event_ledger(list(reversed(events)), second_path)
    first_bytes = first_path.read_bytes()
    second_bytes = second_path.read_bytes()
    csv_bytes = gzip.decompress(first_bytes)
    rows = list(csv.DictReader(csv_bytes.decode("utf-8").splitlines()))

    assert first_bytes == second_bytes
    assert first_reference["row_count"] == second_reference["row_count"] == 2
    assert first_reference["sha256_uncompressed_csv"] == second_reference["sha256_uncompressed_csv"]
    assert hashlib.sha256(csv_bytes).hexdigest() == first_reference["sha256_uncompressed_csv"]
    assert rows[0]["state"] == "B0"
    assert rows[1]["state"] == "V2_low_shock_50"
    assert tuple(rows[0]) == LEDGER_COLUMNS


def test_compact_json_references_ledger_without_serializing_rows() -> None:
    ledger_reference = {
        "path": "bottom_repair_v2_eval_events.csv.gz",
        "row_count": 2,
        "sha256_uncompressed_csv": "abc123",
    }
    report = {
        "study": "bottom_repair_v2_eval",
        "results": {"B0": {"dev": {"n_events": 2}}},
        "event_ledger": _sample_ledger_events(),
    }

    payload = json.loads(json.dumps(report_without_event_rows(report, ledger_reference), indent=2))

    assert payload["results"] == report["results"]
    assert payload["event_ledger"] == ledger_reference
    assert isinstance(payload["event_ledger"], dict)
    assert "metrics" not in payload["event_ledger"]
