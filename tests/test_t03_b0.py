from __future__ import annotations

import inspect
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from research.eval.top_time.contracts import LabelState
from research.lppls.core import design
from research.lppls.future_contract import LogPrice, fit_window
from research.lppls.window_clusters import SCALE_WINDOWS, selected_windows
from scripts.research import t03_b0_scan, t03_merge_and_score


def test_random_placement_expectation_matches_hand_enumeration():
    assert t03_merge_and_score.random_placement_expectation(0, 10, 30, 10) == 30 / 54


def test_hit_k_includes_exact_distance_boundary_and_requires_future_event():
    assert t03_merge_and_score.hit_k(29, 0, 10, 19, 10) == 1
    assert t03_merge_and_score.hit_k(29, 0, 10, 19, 9) == 0
    assert t03_merge_and_score.hit_k(0, 0, 1, 10, 10) == 0


def test_year_block_bootstrap_is_deterministic():
    years = [2010, 2010, 2011, 2012, 2012]
    values = [0.1, -0.2, 0.3, 0.4, -0.1]
    first = t03_merge_and_score.year_block_bootstrap(years, values, n_resamples=250)
    second = t03_merge_and_score.year_block_bootstrap(years, values, n_resamples=250)
    assert first == second


def test_w1_fits_are_exact_thin_subset_of_b0_fits():
    thin = selected_windows("thin")
    expected_thin = {
        "short": (30, 35, 40, 45, 50, 55, 60),
        "mid": (65, 75, 85, 95, 105, 115, 125),
        "medium": (130, 150, 170, 190, 210, 230, 250),
        "long": (255, 295, 335, 375, 420, 460, 500),
    }
    assert thin == expected_thin
    assert len({window for values in thin.values() for window in values}) == 28
    grid = [window for values in SCALE_WINDOWS.values() for window in values]
    rows = [
        {
            "date": pd.Timestamp("2015-01-05"),
            "n": window,
            "tc": window - 1 + 10,
            "m": 0.5,
            "w": 10.0,
            "B": -1.0,
            "t01_qualified": True,
        }
        for window in grid
    ]
    fits = pd.DataFrame(rows)
    arms = t03_merge_and_score._asof_arms(
        "sh000300", "2015-01-05", 1000, fits, grid
    )
    b0 = {row["n"]: row for row in arms["B0"]["analysis"]["fits"]}
    w1 = {row["n"]: row for row in arms["W1"]["analysis"]["fits"]}
    assert set(w1) == {window for values in expected_thin.values() for window in values}
    fit_fields = ("n", "ahead", "osc_cycles", "osc_cycles_status", "qualified", "expected")
    assert all(
        {field: w1[window][field] for field in fit_fields}
        == {field: b0[window][field] for field in fit_fields}
        for window in w1
    )


def test_t01_qualification_does_not_add_ahead_90_cap():
    grid = [window for values in SCALE_WINDOWS.values() for window in values]
    fits = pd.DataFrame([
        {
            "date": pd.Timestamp("2015-01-05"),
            "n": window,
            "tc": window - 1 + 95,
            "m": 0.5,
            "w": 10.0,
            "B": -1.0,
            "t01_qualified": window == 500,
        }
        for window in grid
    ])
    arms = t03_merge_and_score._asof_arms("sh000300", "2015-01-05", 1000, fits, grid)
    long_fit = next(
        row for row in arms["B0"]["analysis"]["fits"] if row["n"] == 500
    )
    assert long_fit["ahead"] == 95
    assert long_fit["qualified"] is True


def test_conservation_rejects_missing_window():
    with pytest.raises(ValueError, match="window conservation failed"):
        t03_merge_and_score.validate_conservation(95, 91, 2, 1)
    grid = [window for values in SCALE_WINDOWS.values() for window in values]
    scan = [{
        "symbol": "sh000300",
        "asof": "2015-01-05",
        "planned": 95,
        "done": 0,
        "failed": 0,
        "ineligible": 95,
        "unresolved": 0,
    }]
    windows = [
        {"symbol": "sh000300", "asof": "2015-01-05", "n": window, "status": "ineligible"}
        for window in grid[:-1]
    ]
    with pytest.raises(ValueError, match="expected exactly 95"):
        t03_merge_and_score._assert_scan_conservation(scan, windows)


def test_scanner_rejects_preregistration_sha_mismatch(tmp_path, monkeypatch):
    path = tmp_path / "preregistration.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(t03_b0_scan, "PREREG_PATH", path)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        t03_b0_scan.verify_prereg()


def test_synthetic_fit_has_stable_attempt_and_cache_identity():
    t = np.arange(30, dtype=float)
    matrix = design(t, 34.0, 0.5, 8.0, allow_inside=False)
    assert matrix is not None
    log_price = matrix @ np.asarray([5.0, -1.0, 0.2, 0.1])
    kwargs = {
        "data_hash": "a" * 64,
        "asof": "2015-01-05",
        "window_start": "2014-11-24",
        "window_end": "2015-01-05",
        "lookback_L": len(log_price),
        "bar_to_session_index": tuple(range(len(log_price))),
        "seed_retries": ((0, 0),),
    }
    first = fit_window(LogPrice.from_log_price(log_price), **kwargs)
    second = fit_window(LogPrice.from_log_price(log_price), **kwargs)
    assert first.status in {"fit_ok", "all_attempts_failed"}
    assert len(first.attempts) == 1
    assert first.attempts[0].to_dict() == second.attempts[0].to_dict()
    assert first.attempts[0].cache_key == second.attempts[0].cache_key


def test_claim_state_construction_does_not_consume_scoring_outputs():
    source = inspect.getsource(t03_merge_and_score.build_claims)
    assert "score_t02" not in source
    assert "_event_scores" not in source


def test_data_failure_stays_in_primary_denominator_with_zero_score():
    event = SimpleNamespace(
        scale="stage",
        event_id="event-1",
        peak_session=20,
        support_end=25,
        label_available_session=30,
        label_version="labels-v1",
    )
    states = [LabelState.NO_EVENT] * 100
    states[event.peak_session] = LabelState.MATURE_EVENT
    book = SimpleNamespace(
        symbol="sh000300",
        sessions=tuple(f"2015-01-{index:02d}" for index in range(1, 101)),
        asof_session=99,
        events=[event],
        state_at=lambda scope, session: states[session],
    )
    rows, _ = t03_merge_and_score._event_scores(
        book,
        [{
            "episode_id": "episode-1",
            "scope": "stage",
            "action_session": 10,
            "claim_id": "claim-1",
            "kind": "observation",
            "interval_start": 20,
            "interval_end": 25,
        }],
        start_session=0,
        end_session=99,
        data_evaluable_ids=set(),
    )
    assert len(rows) == 1
    assert rows[0]["data_evaluable"] is False
    assert rows[0]["first_claim_id"] == "claim-1"
    assert rows[0]["hit_10"] == 0
    assert rows[0]["r_10"] == 0.0
    assert rows[0]["S10"] == 0.0
